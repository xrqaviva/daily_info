import csv
import datetime
import html
import io
import json
import math
import re
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from morning_brief.http import SourceError
from morning_brief.models import Observation


def _number(value, label="value"):
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise SourceError("%s is invalid" % label)
    if not math.isfinite(result):
        raise SourceError("%s is not finite" % label)
    return result


def _cutoff(as_of):
    try:
        return datetime.datetime.fromisoformat(str(as_of)).date()
    except ValueError:
        raise SourceError("collection timestamp is invalid")


def _official_daily_cutoff(as_of):
    try:
        moment = datetime.datetime.fromisoformat(str(as_of))
    except ValueError:
        raise SourceError("collection timestamp is invalid")
    if moment.tzinfo is None:
        raise SourceError("collection timestamp requires timezone")
    moment = moment.astimezone(ZoneInfo("Asia/Shanghai"))
    return moment.date() - (
        datetime.timedelta(days=1)
        if moment.time() < datetime.time(12, 0)
        else datetime.timedelta()
    )


def _observation(source, instrument, current, previous, current_date, previous_date,
                 *, unit, url, as_of, contract=None, date_quality="explicit"):
    if previous == 0:
        raise SourceError("previous value is zero")
    if current_date > _cutoff(as_of).isoformat() or current_date <= previous_date:
        raise SourceError("market dates are invalid")
    return Observation(
        source=source,
        instrument=instrument,
        value=current,
        previous_value=previous,
        change_pct=round((current / previous - 1) * 100, 4),
        market_date=current_date,
        unit=unit,
        url=url,
        as_of=as_of,
        contract=contract,
        previous_market_date=previous_date,
        date_quality=date_quality,
    )


def parse_tradingview_scan(payload):
    rows = {}
    data = payload.get("data") if isinstance(payload, dict) else None
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict) or not item.get("s"):
            continue
        values = item.get("d")
        if not isinstance(values, list) or len(values) < 5:
            continue
        try:
            value = _number(values[0])
            change_pct = _number(values[1])
            absolute_change = _number(values[2])
        except SourceError:
            continue
        rows[str(item["s"])] = {
            "source": "tradingview",
            "value": value,
            "change_pct": change_pct,
            "absolute_change": absolute_change,
            "current_session": str(values[3] or "unknown"),
            "update_mode": str(values[4] or "unknown"),
            "date_quality": "session_only",
        }
    if not rows:
        raise SourceError("TradingView scan has no valid rows")
    return rows


def parse_tradingview_china(payload):
    rows = []
    venue_map = {"SSE": "sh", "SZSE": "sz"}
    data = payload.get("data") if isinstance(payload, dict) else None
    for item in data if isinstance(data, list) else []:
        symbol = str(item.get("s") or "") if isinstance(item, dict) else ""
        values = item.get("d") if isinstance(item, dict) else None
        if not symbol or not isinstance(values, list) or len(values) < 6:
            continue
        exchange = str(values[3] or symbol.split(":", 1)[0]).upper()
        market = venue_map.get(exchange)
        if not market:
            continue
        try:
            price = _number(values[1], "TradingView China price")
            change = _number(values[2], "TradingView China change")
        except SourceError:
            continue
        rows.append({
            "code": symbol.split(":", 1)[-1],
            "name": str(values[0] or ""),
            "price": price,
            "change_pct": change,
            "market": market,
            "status": "trading" if str(values[4]) in ("closed", "regular") else "unknown",
            "market_date": None,
        })
    return rows


def _boc_row(row):
    keys = ("FXUSDCAD", "FXCNYCAD", "FXEURCAD", "FXJPYCAD", "FXGBPCAD")
    values = {}
    for key in keys:
        cell = row.get(key) if isinstance(row, dict) else None
        values[key] = _number(cell.get("v") if isinstance(cell, dict) else None, key)
        if values[key] <= 0:
            raise SourceError("BoC rate must be positive")
    cad_per_usd = values["FXUSDCAD"]
    return {
        "usdcny": cad_per_usd / values["FXCNYCAD"],
        "usdeur": cad_per_usd / values["FXEURCAD"],
        "usdjpy": cad_per_usd / values["FXJPYCAD"],
        "usdgbp": cad_per_usd / values["FXGBPCAD"],
    }


def parse_boc_cross_rates(payload, *, as_of, url):
    parsed = []
    for row in (payload.get("observations") if isinstance(payload, dict) else []) or []:
        date = str(row.get("d") or "")
        try:
            datetime.date.fromisoformat(date)
            values = _boc_row(row)
        except (TypeError, ValueError, SourceError):
            continue
        if date <= _official_daily_cutoff(as_of).isoformat():
            parsed.append((date, values))
    parsed.sort(key=lambda item: item[0])
    if len(parsed) < 2:
        raise SourceError("BoC requires two complete daily rows")
    previous_date, previous = parsed[-2]
    current_date, current = parsed[-1]
    units = {
        "usdcny": "CNY per USD", "usdeur": "EUR per USD",
        "usdjpy": "JPY per USD", "usdgbp": "GBP per USD",
    }
    return {
        key: _observation(
            "boc", key, current[key], previous[key], current_date, previous_date,
            unit=units[key], url=url, as_of=as_of,
            contract="official daily reference",
            date_quality="derived_official_daily",
        )
        for key in current
    }


def _boe_row(row):
    direct_cny = _number(row.get("XUDLBK73"), "XUDLBK73")
    direct_jpy = _number(row.get("XUDLJYD"), "XUDLJYD")
    direct_eur = _number(row.get("XUDLERD"), "XUDLERD")
    direct_gbp = _number(row.get("XUDLGBD"), "XUDLGBD")
    if min(direct_cny, direct_jpy, direct_eur, direct_gbp) <= 0:
        raise SourceError("BoE rate must be positive")
    return {
        "usdcny": direct_cny,
        "usdeur": direct_eur,
        "usdjpy": direct_jpy,
        "usdgbp": direct_gbp,
    }


def parse_boe_cross_rates(text, *, as_of, url):
    parsed = []
    for row in csv.DictReader(io.StringIO(str(text or ""))):
        date = str(row.get("DATE") or row.get("Date") or "").strip()
        try:
            try:
                normalized_date = datetime.date.fromisoformat(date)
            except ValueError:
                normalized_date = datetime.datetime.strptime(
                    date, "%d %b %Y"
                ).date()
            values = _boe_row(row)
        except (TypeError, ValueError, SourceError):
            continue
        date = normalized_date.isoformat()
        if date <= _official_daily_cutoff(as_of).isoformat():
            parsed.append((date, values))
    parsed.sort(key=lambda item: item[0])
    if len(parsed) < 2:
        raise SourceError("BoE requires two complete daily rows")
    previous_date, previous = parsed[-2]
    current_date, current = parsed[-1]
    units = {
        "usdcny": "CNY per USD", "usdeur": "EUR per USD",
        "usdjpy": "JPY per USD", "usdgbp": "GBP per USD",
    }
    return {
        key: _observation(
            "boe", key, current[key], previous[key], current_date, previous_date,
            unit=units[key], url=url, as_of=as_of,
            contract="official daily reference",
            date_quality="derived_official_daily",
        )
        for key in current
    }


def parse_ecb_cross_rates(text, *, as_of, url):
    body = str(text or "")
    parsed = []
    daily_rates = {}
    if body.lstrip().startswith("<"):
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            raise SourceError("ECB FX XML is invalid")
        for node in root.iter():
            date = str(node.attrib.get("time") or "")
            if not date:
                continue
            rates = daily_rates.setdefault(date, {})
            for child in list(node):
                currency = str(child.attrib.get("currency") or "").upper()
                if currency not in ("USD", "CNY", "JPY", "GBP"):
                    continue
                try:
                    rates[currency] = _number(child.attrib.get("rate"), currency)
                except SourceError:
                    pass
    else:
        for row in csv.DictReader(io.StringIO(body)):
            date = str(row.get("TIME_PERIOD") or "")
            currency = str(row.get("CURRENCY") or "").upper()
            if currency not in ("USD", "CNY", "JPY", "GBP"):
                continue
            try:
                daily_rates.setdefault(date, {})[currency] = _number(
                    row.get("OBS_VALUE"), currency
                )
            except SourceError:
                continue
    for date, rates in daily_rates.items():
        try:
            datetime.date.fromisoformat(date)
        except ValueError:
            continue
        if set(rates) != {"USD", "CNY", "JPY", "GBP"} or min(rates.values()) <= 0:
            continue
        usd_per_eur = rates["USD"]
        values = {
            "usdcny": rates["CNY"] / usd_per_eur,
            "usdeur": 1.0 / usd_per_eur,
            "usdjpy": rates["JPY"] / usd_per_eur,
            "usdgbp": rates["GBP"] / usd_per_eur,
        }
        if date <= _official_daily_cutoff(as_of).isoformat():
            parsed.append((date, values))
    parsed.sort(key=lambda item: item[0])
    if len(parsed) < 2:
        raise SourceError("ECB requires two complete daily rows")
    previous_date, previous = parsed[-2]
    current_date, current = parsed[-1]
    units = {
        "usdcny": "CNY per USD", "usdeur": "EUR per USD",
        "usdjpy": "JPY per USD", "usdgbp": "GBP per USD",
    }
    return {
        key: _observation(
            "ecb", key, current[key], previous[key], current_date, previous_date,
            unit=units[key], url=url, as_of=as_of,
            contract="official daily reference",
            date_quality="derived_official_daily",
        )
        for key in current
    }


def parse_cboe_history(text, *, instrument, as_of, url):
    rows = []
    target_session = latest_completed_nyse_session(as_of).isoformat()
    for row in csv.DictReader(io.StringIO(str(text or ""))):
        normalized = {str(key).upper(): value for key, value in row.items()}
        try:
            raw_date = str(normalized.get("DATE") or "")
            try:
                date = datetime.date.fromisoformat(raw_date)
            except ValueError:
                date = datetime.datetime.strptime(raw_date, "%m/%d/%Y").date()
            close = _number(
                normalized.get("CLOSE") or normalized.get("SPX"),
                "Cboe close",
            )
        except (TypeError, ValueError, SourceError):
            continue
        if date.isoformat() <= target_session:
            rows.append((date.isoformat(), close))
    rows.sort(key=lambda item: item[0])
    if len(rows) < 2:
        raise SourceError("Cboe history requires two complete rows")
    previous_date, previous = rows[-2]
    current_date, current = rows[-1]
    return _observation(
        "cboe", instrument, current, previous, current_date, previous_date,
        unit="points", url=url, as_of=as_of, contract="SPX cash index close",
    )


def parse_hf_quote(text, *, source, instrument, unit, as_of, url, contract):
    raw = str(text or "")
    if '="' not in raw:
        raise SourceError("international futures quote is invalid")
    body = raw.split('="', 1)[1].split('"', 1)[0]
    fields = body.split(",")
    try:
        current = _number(fields[0], "current quote")
        previous = _number(fields[7], "previous settlement")
        market_date = str(fields[12]).strip()
        parsed_date = datetime.date.fromisoformat(market_date)
    except (IndexError, ValueError, SourceError):
        raise SourceError("international futures fields are invalid")
    if parsed_date.weekday() >= 5:
        # provider marks the current calendar day on weekends even though the
        # quote is the last session's close; roll back to Friday
        market_date = (parsed_date - datetime.timedelta(days=parsed_date.weekday() - 4)).isoformat()
    cutoff = _cutoff(as_of).isoformat()
    if market_date > cutoff or previous <= 0:
        raise SourceError("international futures date or previous value is invalid")
    computed = round((current / previous - 1) * 100, 4)
    if source == "tencent" and len(fields) > 1 and str(fields[1]).strip():
        provider_change = _number(fields[1], "provider change")
        if abs(provider_change - computed) > 0.5:
            raise SourceError("international futures change does not match")
    return Observation(
        source=source,
        instrument=instrument,
        value=current,
        previous_value=previous,
        change_pct=computed,
        market_date=market_date,
        unit=unit,
        url=url,
        as_of=as_of,
        contract=contract,
        date_quality="explicit",
    )


def _target_date(expected_market_date, as_of):
    target = str(expected_market_date or "").strip()
    if not target:
        target = latest_completed_international_session(as_of).isoformat()
    try:
        datetime.date.fromisoformat(target)
    except ValueError:
        raise SourceError("expected market date is invalid")
    if target > _cutoff(as_of).isoformat():
        raise SourceError("expected market date is in the future")
    return target


def _dated_close_observation(rows, *, source, instrument, unit, as_of, url,
                             contract, expected_market_date):
    target = _target_date(expected_market_date, as_of)
    usable = sorted(
        {(str(date), _number(close, "daily close")) for date, close in rows
         if str(date) <= target},
        key=lambda item: item[0],
    )
    if len(usable) < 2 or usable[-1][0] != target:
        raise SourceError("daily history does not contain target market date")
    previous_date, previous = usable[-2]
    current_date, current = usable[-1]
    return _observation(
        source, instrument, current, previous, current_date, previous_date,
        unit=unit, url=url, as_of=as_of, contract=contract,
    )


def parse_sina_global_history(text, *, instrument, unit, as_of, url, contract,
                              expected_market_date=None, scale=1.0):
    body = str(text or "")
    start, end = body.find("["), body.rfind("]")
    if start < 0 or end <= start:
        raise SourceError("Sina global history has no JSON array")
    try:
        payload = json.loads(body[start:end + 1])
    except (TypeError, ValueError):
        raise SourceError("Sina global history JSON is invalid")
    scale = _number(scale, "Sina global scale")
    if scale <= 0:
        raise SourceError("Sina global scale must be positive")
    rows = []
    for item in payload if isinstance(payload, list) else []:
        try:
            date = str(item.get("date") or "")
            datetime.date.fromisoformat(date)
            close_value = _number(item.get("close"), "Sina global close")
            raw_ohlc = [item.get(field) for field in ("open", "high", "low", "close")]
            if any(value not in (None, "") for value in raw_ohlc[:3]):
                if any(value in (None, "") for value in raw_ohlc):
                    continue
                opening, high, low, closing = (
                    _number(value, "Sina global OHLC") for value in raw_ohlc
                )
                tolerance = max(abs(closing) * 1e-9, 1e-9)
                if low > high + tolerance:
                    continue
                if closing < low - tolerance or closing > high + tolerance:
                    continue
                # open 允许小幅偏离 [low,high]（新浪 LME 偶发电子盘开盘与场内
                # 最低价的毫级矛盾，如 AHD 2026-08-21 open<low 0.1%），但大幅
                # 脱离区间即跨合约换月行，必须整行拒绝（AGENTS.md 第3条，
                # 见 test_sina_global_history_rejects_impossible_ohlc_roll_row）。
                open_tolerance = max(abs(closing) * 0.02, tolerance)
                if opening < low - open_tolerance or opening > high + open_tolerance:
                    continue
            close = round(close_value * scale, 10)
        except (AttributeError, TypeError, ValueError, SourceError):
            continue
        rows.append((date, close))
    return _dated_close_observation(
        rows,
        source="sina_global_history",
        instrument=instrument,
        unit=unit,
        as_of=as_of,
        url=url,
        contract=contract,
        expected_market_date=expected_market_date,
    )


def parse_eastmoney_global_history(payload, *, instrument, unit, as_of, url,
                                   contract, expected_market_date=None):
    try:
        raw_rows = payload["data"]["klines"]
    except (KeyError, TypeError):
        raise SourceError("Eastmoney global history has no klines")
    target = _target_date(expected_market_date, as_of)
    rows = []
    for raw in raw_rows if isinstance(raw_rows, list) else []:
        fields = str(raw).split(",")
        try:
            date = fields[0].strip()
            datetime.date.fromisoformat(date)
            close = _number(fields[2], "Eastmoney global close")
        except (IndexError, TypeError, ValueError, SourceError):
            continue
        if date <= target:
            rows.append((date, close, fields))
    rows.sort(key=lambda item: item[0])
    if len(rows) < 2 or rows[-1][0] != target:
        raise SourceError("Eastmoney global history lacks target market date")
    previous_date, row_previous = rows[-2][0], rows[-2][1]
    current_date, current, fields = rows[-1]
    provider_pct = None
    provider_absolute = None
    try:
        provider_pct = _number(fields[8], "Eastmoney global change")
        provider_absolute = _number(fields[9], "Eastmoney global absolute change")
    except (IndexError, SourceError):
        pass
    settlement_previous = None
    if provider_absolute is not None:
        settlement_previous = current - provider_absolute
        if settlement_previous <= 0:
            raise SourceError("Eastmoney global settlement baseline is invalid")
    if provider_pct is not None:
        denominator = 1 + provider_pct / 100
        if denominator <= 0:
            raise SourceError("Eastmoney global change is invalid")
        pct_previous = current / denominator
        if settlement_previous is None:
            settlement_previous = pct_previous
        else:
            implied_pct = (current / settlement_previous - 1) * 100
            if abs(implied_pct - provider_pct) > 0.10:
                raise SourceError("Eastmoney global change fields do not agree")
    previous = settlement_previous if settlement_previous is not None else row_previous
    if previous == 0:
        raise SourceError("Eastmoney global previous close is zero")
    return _observation(
        "eastmoney_global_history",
        instrument,
        current,
        previous,
        current_date,
        previous_date,
        unit=unit,
        url=url,
        as_of=as_of,
        contract=contract,
    )


def _previous_weekday(day):
    candidate = day - datetime.timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= datetime.timedelta(days=1)
    return candidate


def parse_tencent_gz_quote(text, *, symbol, instrument, unit, as_of, url,
                           contract, market_timezone,
                           market_calendar="international"):
    match = re.search(
        r'v_gz%s="([^"]*)"' % re.escape(str(symbol)), str(text or "")
    )
    if not match:
        raise SourceError("Tencent global index quote is missing")
    fields = match.group(1).split("~")
    try:
        timestamp = datetime.datetime.strptime(fields[2], "%Y-%m-%d %H:%M:%S")
        timestamp = timestamp.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        market_date = timestamp.astimezone(ZoneInfo(market_timezone)).date()
        current = _number(fields[3], "Tencent global index close")
        absolute = _number(fields[4], "Tencent global index absolute change")
        change_pct = _number(fields[5], "Tencent global index change")
    except (IndexError, TypeError, ValueError, SourceError, ZoneInfoNotFoundError):
        raise SourceError("Tencent global index fields are invalid")
    previous = current - absolute
    if previous <= 0:
        raise SourceError("Tencent global index previous close is invalid")
    computed = (current / previous - 1) * 100
    if abs(computed - change_pct) > 0.15:
        raise SourceError("Tencent global index change does not match")
    previous_date = _previous_international_session(
        market_date, market_calendar
    ).isoformat()
    return Observation(
        source="tencent",
        instrument=instrument,
        value=current,
        previous_value=previous,
        change_pct=round(change_pct, 4),
        market_date=market_date.isoformat(),
        unit=unit,
        url=url,
        as_of=as_of,
        contract=contract,
        previous_market_date=previous_date,
        date_quality="explicit",
    )


def parse_sina_a_share(text, *, instrument, unit, url, as_of, contract=None):
    """新浪A股行情（hq.sinajs.cn）：fields 0=名称 1=今开 2=昨收 3=现价 30=日期 31=时间。"""
    match = re.search(r'hq_str_[a-z]+\d+="([^"]*)"', str(text or ""))
    if not match:
        raise SourceError("Sina A-share quote is missing")
    fields = match.group(1).split(",")
    if len(fields) < 32:
        raise SourceError("Sina A-share quote is incomplete")
    current = _number(fields[3], "Sina A-share current")
    previous = _number(fields[2], "Sina A-share previous")
    market_date = str(fields[30]).strip()[:10]
    try:
        datetime.date.fromisoformat(market_date)
    except ValueError:
        raise SourceError("Sina A-share date is invalid")
    if current <= 0 or previous <= 0 or market_date > _cutoff(as_of).isoformat():
        raise SourceError("Sina A-share values are invalid")
    return Observation(
        source="sina",
        instrument=instrument,
        value=current,
        previous_value=previous,
        change_pct=round((current / previous - 1) * 100, 2),
        market_date=market_date,
        unit=unit,
        url=url,
        as_of=as_of,
        contract=contract or "A-share stock close",
    )


def parse_sina_diniw(text, *, as_of, url):
    match = re.search(r'hq_str_DINIW="([^"]*)"', str(text or ""))
    if not match:
        raise SourceError("Sina DXY quote is missing")
    fields = match.group(1).split(",")
    if len(fields) < 11:
        raise SourceError("Sina DXY quote is incomplete")
    current = _number(fields[1], "Sina DXY current")
    previous = _number(fields[5], "Sina DXY previous")
    market_date = str(fields[10]).strip()[:10]
    try:
        parsed_date = datetime.date.fromisoformat(market_date)
    except ValueError:
        raise SourceError("Sina DXY date is invalid")
    if parsed_date.weekday() >= 5:
        # DXY trades around the clock; on weekends the provider stamps the
        # current calendar day even though the quote is Friday's session
        market_date = (parsed_date - datetime.timedelta(days=parsed_date.weekday() - 4)).isoformat()
    if current <= 0 or previous <= 0 or market_date > _cutoff(as_of).isoformat():
        raise SourceError("Sina DXY values are invalid")
    return Observation(
        source="sina",
        instrument="美元指数",
        value=current,
        previous_value=previous,
        change_pct=round((current / previous - 1) * 100, 4),
        market_date=market_date,
        unit="points",
        url=url,
        as_of=as_of,
        contract="provider_continuous",
        date_quality="explicit",
    )


def parse_professional_price_history(text, *, source, instrument, contract, unit, as_of, url):
    body = html.unescape(str(text or ""))
    try:
        moment = datetime.datetime.fromisoformat(str(as_of))
    except ValueError:
        raise SourceError("collection timestamp is invalid")
    cutoff = moment.date()
    if moment.hour < 12:
        cutoff -= datetime.timedelta(days=1)
    pattern = re.compile(
        re.escape(contract) + r"\s+([0-9]+(?:\.[0-9]+)?)\s*(?:-\s*)?"
        r"([0-9]+(?:\.[0-9]+)?)\s+([0-9]+(?:\.[0-9]+)?)\s+"
        r"\S+\s+(20\d{2}-\d{2}-\d{2})"
    )
    rows = []
    for low, high, midpoint, date in pattern.findall(body):
        try:
            low_value, high_value = _number(low), _number(high)
            value = _number(midpoint)
            datetime.date.fromisoformat(date)
        except (ValueError, SourceError):
            continue
        if low_value <= value <= high_value and date <= cutoff.isoformat():
            rows.append((date, value))
    pid_match = re.search(
        r'"product_id"\s*:\s*"([0-9]+)"\s*,\s*"product_name"\s*:\s*"%s"'
        % re.escape(contract),
        body,
    )
    trend_rows = []
    if pid_match:
        product_id = pid_match.group(1)
        for average, date in re.findall(
            r'"product_id"\s*:\s*"%s".*?"average"\s*:\s*([0-9]+(?:\.[0-9]+)?).*?'
            r'"renew_date"\s*:\s*"(20\d{2}-\d{2}-\d{2})"'
            % re.escape(product_id),
            body,
            re.DOTALL,
        ):
            try:
                value = _number(average)
                datetime.date.fromisoformat(date)
            except (ValueError, SourceError):
                continue
            if date <= cutoff.isoformat():
                trend_rows.append((date, value))
    if not trend_rows:
        # fallback for fixtures without product_id: product_name directly
        # followed by its own price_detail array
        legacy = re.search(
            r'"product_name"\s*:\s*"%s".{0,500}?'
            r'"price_detail"\s*:\s*\[(.*?)\]'
            % re.escape(contract),
            body,
            re.DOTALL,
        )
        if legacy:
            for average, date in re.findall(
                r'"average"\s*:\s*([0-9]+(?:\.[0-9]+)?).*?'
                r'"renew_date"\s*:\s*"(20\d{2}-\d{2}-\d{2})"',
                legacy.group(1),
                re.DOTALL,
            ):
                try:
                    value = _number(average)
                    datetime.date.fromisoformat(date)
                except (ValueError, SourceError):
                    continue
                if date <= cutoff.isoformat():
                    trend_rows.append((date, value))
    rows.extend(trend_rows)
    rows.sort(key=lambda item: item[0])
    # a provider may repeat the same date with a newer value (latest price vs
    # embedded history); keep only the last value per date so the previous
    # observation is a distinct older day
    deduped = []
    for date, value in rows:
        if deduped and deduped[-1][0] == date:
            deduped[-1] = (date, value)
        else:
            deduped.append((date, value))
    rows = deduped
    if len(rows) < 2:
        raise SourceError("professional price requires two dated table rows")
    previous_date, previous = rows[-2]
    current_date, current = rows[-1]
    return _observation(
        source, instrument, current, previous, current_date, previous_date,
        unit=unit, url=url, as_of=as_of, contract=contract,
    )


def _nth_weekday(year, month, weekday, nth):
    day = datetime.date(year, month, 1)
    return day + datetime.timedelta(days=(weekday - day.weekday()) % 7 + 7 * (nth - 1))


def _last_weekday(year, month, weekday):
    next_month = datetime.date(year + (month == 12), (month % 12) + 1, 1)
    day = next_month - datetime.timedelta(days=1)
    return day - datetime.timedelta(days=(day.weekday() - weekday) % 7)


def _observed(day):
    if day.weekday() == 5:
        return day - datetime.timedelta(days=1)
    if day.weekday() == 6:
        return day + datetime.timedelta(days=1)
    return day


def _easter(year):
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return datetime.date(year, month, day)


def _nyse_holidays(year):
    holidays = {
        _observed(datetime.date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _easter(year) - datetime.timedelta(days=2),
        _last_weekday(year, 5, 0),
        _observed(datetime.date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed(datetime.date(year, 12, 25)),
    }
    if year >= 2022:
        holidays.add(_observed(datetime.date(year, 6, 19)))
    return holidays


def latest_completed_nyse_session(as_of):
    try:
        moment = datetime.datetime.fromisoformat(str(as_of))
    except ValueError:
        raise SourceError("collection timestamp is invalid")
    if moment.tzinfo is None:
        raise SourceError("collection timestamp requires timezone")
    eastern = moment.astimezone(ZoneInfo("America/New_York"))
    candidate = eastern.date()
    if eastern.time() < datetime.time(16, 15):
        candidate -= datetime.timedelta(days=1)
    holidays = _nyse_holidays(candidate.year) | _nyse_holidays(candidate.year + 1)
    while candidate.weekday() >= 5 or candidate in holidays:
        candidate -= datetime.timedelta(days=1)
        holidays |= _nyse_holidays(candidate.year)
    return candidate


def _uk_christmas_holidays(year):
    christmas = datetime.date(year, 12, 25)
    weekday = christmas.weekday()
    if weekday == 4:
        return {christmas, datetime.date(year, 12, 28)}
    if weekday == 5:
        return {datetime.date(year, 12, 27), datetime.date(year, 12, 28)}
    if weekday == 6:
        return {datetime.date(year, 12, 26), datetime.date(year, 12, 27)}
    return {christmas, datetime.date(year, 12, 26)}


def _international_holidays(year, market_calendar):
    calendar = str(market_calendar or "international").lower()
    easter = _easter(year)
    common = {
        datetime.date(year, 1, 1),
        easter - datetime.timedelta(days=2),
        easter + datetime.timedelta(days=1),
        datetime.date(year, 12, 25),
    }
    if calendar in ("uk", "lme"):
        return {
            _observed(datetime.date(year, 1, 1)),
            easter - datetime.timedelta(days=2),
            easter + datetime.timedelta(days=1),
            _nth_weekday(year, 5, 0, 1),
            _last_weekday(year, 5, 0),
            _last_weekday(year, 8, 0),
        } | _uk_christmas_holidays(year)
    if calendar in ("euronext", "paris"):
        return common | {
            datetime.date(year, 5, 1),
            datetime.date(year, 12, 26),
        }
    if calendar in ("xetra", "frankfurt"):
        return common | {
            datetime.date(year, 5, 1),
            datetime.date(year, 12, 24),
            datetime.date(year, 12, 26),
            datetime.date(year, 12, 31),
        }
    return common


def _previous_international_session(day, market_calendar="international"):
    candidate = day - datetime.timedelta(days=1)
    while True:
        holidays = _international_holidays(candidate.year, market_calendar)
        if candidate.weekday() < 5 and candidate not in holidays:
            return candidate
        candidate -= datetime.timedelta(days=1)


def latest_completed_international_session(
    as_of, market_calendar="international"
):
    try:
        moment = datetime.datetime.fromisoformat(str(as_of))
    except ValueError:
        raise SourceError("collection timestamp is invalid")
    if moment.tzinfo is None:
        raise SourceError("collection timestamp requires timezone")
    shanghai = moment.astimezone(ZoneInfo("Asia/Shanghai"))
    return _previous_international_session(
        shanghai.date(), market_calendar
    )
