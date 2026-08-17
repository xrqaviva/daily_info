import datetime
from urllib.parse import quote

from .http import SourceError
from .sources.stooq import parse_stooq_csv
from .sources.sina_futures import parse_sina_futures_daily
from .sources.eastmoney_futures import parse_eastmoney_futures
from .sources.yahoo import parse_yahoo_chart
from .sources.tencent import parse_tencent_global_quote
from .sources.tungsten import (
    parse_ganzhou_article_url,
    parse_ganzhou_forecast,
    parse_smm_tungsten_rows,
)
from .sources.free_market import (
    parse_sina_a_share,
    latest_completed_international_session,
    latest_completed_nyse_session,
    parse_boc_cross_rates,
    parse_boe_cross_rates,
    parse_cboe_history,
    parse_ecb_cross_rates,
    parse_eastmoney_global_history,
    parse_hf_quote,
    parse_professional_price_history,
    parse_sina_diniw,
    parse_sina_global_history,
    parse_tencent_gz_quote,
    parse_tradingview_scan,
)
from .models import Observation, VerificationResult
from .verification import rank_sector_extremes, verify_observations


def synthesize_index(member_results, *, label):
    # 等权合成板块指数：成分收盘均值 + 成分涨跌幅均值
    values = []
    changes = []
    dates = set()
    for result in member_results:
        observations = getattr(result, "observations", None) or ()
        if not observations:
            continue
        obs = observations[0]
        if getattr(obs, "value", None) is None:
            continue
        values.append(float(obs.value))
        if getattr(obs, "change_pct", None) is not None:
            changes.append(float(obs.change_pct))
        if getattr(obs, "market_date", None):
            dates.add(str(obs.market_date))
    if not values:
        return VerificationResult(status="unavailable", consensus_value=None,
                                  consensus_change_pct=None, observations=(), reason="no_sources")
    observation = Observation(
        source="synthetic",
        instrument=label,
        value=round(sum(values) / len(values), 2),
        previous_value=None,
        change_pct=round(sum(changes) / len(changes), 2) if changes else None,
        market_date=sorted(dates)[-1] if dates else "",
        unit="USD",
        url="",
        as_of=None,
        contract="synthetic equal-weight index",
    )
    return VerificationResult(status="single_source", consensus_value=observation.value,
                              consensus_change_pct=observation.change_pct,
                              observations=(observation,))


class MarketCollector:
    def __init__(self, client):
        self.client = client
        self._batch_cache = {}

    @staticmethod
    def _date_range(as_of):
        try:
            end = datetime.datetime.fromisoformat(as_of).date()
        except (TypeError, ValueError):
            end = datetime.date.today()
        start = end - datetime.timedelta(days=14)
        return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")

    def _fetch(self, source, *, instrument, unit, as_of, contract=None,
               expected_market_date=None, market_calendar=None):
        kind = source.get("kind")
        symbol = str(source.get("symbol") or "")
        if kind == "boc":
            cache_key = ("boc", str(as_of)[:10])
            if cache_key not in self._batch_cache:
                url = (
                    "https://www.bankofcanada.ca/valet/observations/"
                    "FXUSDCAD,FXEURCAD,FXJPYCAD,FXGBPCAD,FXCNYCAD/json?recent=5"
                )
                self._batch_cache[cache_key] = parse_boc_cross_rates(
                    self.client.get_json(url), as_of=as_of, url=url
                )
            try:
                return self._batch_cache[cache_key][symbol]
            except KeyError:
                raise SourceError("BoC FX symbol is unsupported")
        if kind == "boe":
            cache_key = ("boe", str(as_of)[:10])
            if cache_key not in self._batch_cache:
                try:
                    end = datetime.datetime.fromisoformat(str(as_of)).date()
                except ValueError:
                    raise SourceError("BoE collection timestamp is invalid")
                start = end - datetime.timedelta(days=14)
                url = (
                    "https://www.bankofengland.co.uk/boeapps/database/"
                    "_iadb-fromshowcolumns.asp?csv.x=yes&Datefrom=%s&Dateto=%s"
                    "&SeriesCodes=XUDLBK73,XUDLJYD,XUDLERD,XUDLGBD"
                    "&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N"
                    % (start.strftime("%d/%b/%Y"), end.strftime("%d/%b/%Y"))
                )
                self._batch_cache[cache_key] = parse_boe_cross_rates(
                    self.client.get_text(url), as_of=as_of, url=url
                )
            try:
                return self._batch_cache[cache_key][symbol]
            except KeyError:
                raise SourceError("BoE FX symbol is unsupported")
        if kind == "ecb":
            try:
                end = datetime.datetime.fromisoformat(str(as_of)).date()
            except ValueError:
                raise SourceError("ECB collection timestamp is invalid")
            start = end - datetime.timedelta(days=14)
            url = (
                "https://data-api.ecb.europa.eu/service/data/"
                "EXR/D.CNY+USD+JPY+GBP.EUR.SP00.A?"
                "startPeriod=%s&format=csvdata" % start.isoformat()
            )
            cache_key = ("ecb", str(as_of)[:10])
            if cache_key not in self._batch_cache:
                self._batch_cache[cache_key] = parse_ecb_cross_rates(
                    self.client.get_text(url), as_of=as_of, url=url
                )
            try:
                return self._batch_cache[cache_key][symbol]
            except KeyError:
                raise SourceError("ECB FX symbol is unsupported")
        if kind == "cboe":
            url = str(source.get("url") or "https://cdn.cboe.com/api/global/us_indices/daily_prices/SPX_History.csv")
            cache_key = ("cboe", url)
            if cache_key not in self._batch_cache:
                self._batch_cache[cache_key] = parse_cboe_history(
                    self.client.get_text(url), instrument=instrument,
                    as_of=as_of, url=url,
                )
            return self._batch_cache[cache_key]
        if kind == "sina_global_history":
            url = (
                "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/"
                "var=/GlobalFuturesService.getGlobalFuturesDailyKLine?symbol=%s"
                % quote(symbol, safe="")
            )
            return parse_sina_global_history(
                self.client.get_text(url),
                instrument=instrument,
                unit=unit,
                as_of=as_of,
                url=url,
                contract=contract or "provider_continuous",
                expected_market_date=expected_market_date,
                scale=source.get("scale", 1.0),
            )
        if kind == "eastmoney_global_history":
            url = (
                "https://push2his.eastmoney.com/api/qt/stock/kline/get"
                "?secid=%s&klt=101&fqt=1&lmt=30&end=20500000&iscca=1"
                "&fields1=f1%%2Cf2%%2Cf3%%2Cf4%%2Cf5%%2Cf6%%2Cf7%%2Cf8"
                "&fields2=f51%%2Cf52%%2Cf53%%2Cf54%%2Cf55%%2Cf56%%2Cf57%%2Cf58%%2Cf59%%2Cf60%%2Cf61%%2Cf62%%2Cf63%%2Cf64"
                "&ut=f057cbcbce2a86e2866ab8877db1d059&forcect=1"
                % quote(symbol, safe=".")
            )
            return parse_eastmoney_global_history(
                self.client.get_json(url, headers={"Referer": "https://quote.eastmoney.com/"}),
                instrument=instrument,
                unit=unit,
                as_of=as_of,
                url=url,
                contract=contract or "provider_continuous",
                expected_market_date=expected_market_date,
            )
        if kind == "tencent_gz":
            code = "gz%s" % symbol
            url = "https://qt.gtimg.cn/q=%s" % quote(code, safe="")
            return parse_tencent_gz_quote(
                self.client.get_text(
                    url, headers={"Referer": "https://finance.qq.com"}
                ),
                symbol=symbol,
                instrument=instrument,
                unit=unit,
                as_of=as_of,
                url=url,
                contract=contract or "cash index close",
                market_timezone=str(
                    source.get("market_timezone") or "Europe/London"
                ),
                market_calendar=str(
                    source.get("market_calendar") or market_calendar or "international"
                ),
            )
        if kind in ("hf_tencent", "hf_sina"):
            provider = "tencent" if kind == "hf_tencent" else "sina"
            code = "hf_%s" % symbol
            if provider == "tencent":
                url = "https://qt.gtimg.cn/q=%s" % quote(code, safe="_")
                text = self.client.get_text(url, headers={"Referer": "https://finance.qq.com"})
            else:
                url = "https://hq.sinajs.cn/list=%s" % quote(code, safe="_")
                text = self.client.get_text(url, headers={"Referer": "https://finance.sina.com.cn"})
            return parse_hf_quote(
                text, source=provider, instrument=instrument, unit=unit,
                as_of=as_of, url=url, contract=contract or "provider_continuous",
            )
        if kind == "sina_a":
            url = "https://hq.sinajs.cn/list=%s" % quote(symbol, safe="")
            return parse_sina_a_share(
                self.client.get_text(
                    url, headers={"Referer": "https://finance.sina.com.cn"}
                ),
                instrument=instrument,
                unit=unit,
                url=url,
                as_of=as_of,
                contract=contract,
            )
        if kind == "sina_diniw":
            url = "https://hq.sinajs.cn/list=DINIW"
            return parse_sina_diniw(
                self.client.get_text(
                    url, headers={"Referer": "https://finance.sina.com.cn"}
                ),
                as_of=as_of,
                url=url,
            )
        if kind == "professional":
            url = str(source.get("url") or "")
            if not url or not contract:
                raise SourceError("professional quote URL or contract is missing")
            return parse_professional_price_history(
                self.client.get_text(url), source=str(source.get("provider") or "professional"),
                instrument=instrument, contract=contract, unit=unit,
                as_of=as_of, url=url,
            )
        if kind == "stooq":
            start, end = self._date_range(as_of)
            url = (
                "https://stooq.com/q/d/l/?s=%s&i=d&d1=%s&d2=%s"
                % (quote(symbol, safe=""), start, end)
            )
            return parse_stooq_csv(
                self.client.get_text(url),
                instrument=instrument,
                unit=unit,
                url=url,
                as_of=as_of,
                contract=contract,
            )
        if kind == "yahoo":
            url = (
                "https://query1.finance.yahoo.com/v8/finance/chart/%s"
                "?range=15d&interval=1d&events=history"
                % quote(symbol, safe="")
            )
            return parse_yahoo_chart(
                self.client.get_json(url),
                instrument=instrument,
                unit=unit,
                url=url,
                as_of=as_of,
                contract=contract,
            )
        if kind == "tencent":
            url = "https://qt.gtimg.cn/q=%s" % quote(symbol, safe="")
            return parse_tencent_global_quote(
                self.client.get_text(
                    url, headers={"Referer": "https://finance.qq.com"}
                ),
                instrument=instrument,
                unit=unit,
                url=url,
                as_of=as_of,
                contract=contract,
            )
        if kind == "sina_futures":
            try:
                query_date = datetime.datetime.fromisoformat(as_of).date()
            except (TypeError, ValueError):
                query_date = datetime.date.today()
            date_token = query_date.strftime("%Y_%m_%d")
            callback = "brief_%s" % query_date.strftime("%Y%m%d")
            url = (
                "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/%s="
                "/InnerFuturesNewService.getDailyKLine?symbol=%s&type=%s"
                % (callback, quote(symbol, safe=""), date_token)
            )
            return parse_sina_futures_daily(
                self.client.get_text(url),
                instrument=instrument,
                unit=unit,
                url=url,
                as_of=as_of,
                contract=contract,
            )
        if kind == "eastmoney_futures":
            url = (
                "https://push2his.eastmoney.com/api/qt/stock/kline/get"
                "?secid=%s&klt=101&fqt=1&lmt=30&end=20500101&iscca=1"
                "&fields1=f1%%2Cf2%%2Cf3%%2Cf4%%2Cf5%%2Cf6%%2Cf7%%2Cf8"
                "&fields2=f51%%2Cf52%%2Cf53%%2Cf54%%2Cf55%%2Cf56%%2Cf57%%2Cf58%%2Cf59%%2Cf60%%2Cf61%%2Cf62%%2Cf63%%2Cf64"
                "&ut=7eea3edcaed734bea9cbfc24409ed989&forcect=1"
                % quote(symbol, safe=".")
            )
            return parse_eastmoney_futures(
                self.client.get_json(url, headers={"Referer": "https://quote.eastmoney.com/"}),
                instrument=instrument,
                unit=unit,
                url=url,
                as_of=as_of,
                contract=contract,
            )
        if kind == "smm":
            url = str(source.get("url") or "")
            if not url:
                raise SourceError("SMM source URL is missing")
            return parse_smm_tungsten_rows(
                self.client.get_text(url),
                instrument=instrument,
                unit=unit,
                url=url,
                as_of=as_of,
                contract=contract,
            )
        if kind == "ganzhou_association":
            url = str(source.get("url") or "")
            if not url:
                raise SourceError("Ganzhou source URL is missing")
            article_url = parse_ganzhou_article_url(self.client.get_text(url))
            return parse_ganzhou_forecast(
                self.client.get_text(article_url),
                instrument=instrument,
                unit=unit,
                url=article_url,
                as_of=as_of,
                contract=contract or "黑钨精矿55%协会预测价",
            )
        raise SourceError("unsupported source adapter: %s" % (kind or "missing"))

    def _collect_one(self, key, item, as_of, errors, expected_market_date=None):
        required_date = None
        if item.get("expected_session") == "a_previous":
            required_date = expected_market_date
        elif item.get("expected_session") == "us_previous":
            required_date = latest_completed_nyse_session(as_of).isoformat()
        elif item.get("expected_session") == "international_previous":
            required_date = latest_completed_international_session(
                as_of,
                market_calendar=str(item.get("market_calendar") or "international"),
            ).isoformat()
        observations = []
        for source in item.get("sources") or []:
            try:
                observations.append(
                    self._fetch(
                        source,
                        instrument=item.get("label") or key,
                        unit=item.get("unit") or "unknown",
                        as_of=as_of,
                        contract=source.get("contract", item.get("contract")),
                        expected_market_date=required_date,
                        market_calendar=item.get("market_calendar"),
                    )
                )
            except Exception as exc:
                errors.append({
                    "instrument": key,
                    "source": source.get("kind") or "unknown",
                    "error": type(exc).__name__,
                })
        tolerance = item.get("value_tolerance")
        if tolerance is None:
            tolerance = 0.005 if item.get("commodity") else 0.002
        return verify_observations(
            observations,
            value_tolerance=float(tolerance),
            change_tolerance=0.10,
            max_age_days=int(
                item.get("max_age_days", 45 if key == "tungsten" else 4)
            ),
            expected_market_date=required_date,
        )

    def collect(self, config, *, as_of, expected_market_date=None):
        self._batch_cache = {}
        errors = []
        quotes = {}
        for key, item in (config or {}).items():
            if key in ("sectors", "supplemental", "us_stock_groups"):
                continue
            quotes[key] = self._collect_one(
                key, item, as_of, errors, expected_market_date
            )

        sectors = {}
        for row in (config or {}).get("sectors") or []:
            symbol = row.get("symbol")
            source_rows = []
            for source in row.get("sources") or []:
                if isinstance(source, dict):
                    source_rows.append(dict(source))
                    continue
                kind = str(source)
                source_rows.append({
                    "kind": kind,
                    "symbol": symbol + (".us" if kind == "stooq" else ""),
                })
            item = {
                "label": row.get("name"),
                "unit": "USD",
                "sources": source_rows,
                "expected_session": row.get("expected_session") or "us_previous",
                "contract": row.get("contract") or "US sector ETF close",
            }
            sectors[row.get("name")] = self._collect_one(
                "sector:%s" % row.get("name"), item, as_of, errors,
                expected_market_date,
            )
        supplemental = {}
        for scanner in (config or {}).get("supplemental") or []:
            if scanner.get("kind") != "tradingview":
                continue
            region = str(scanner.get("scanner") or "global")
            symbols = [str(value) for value in scanner.get("symbols") or [] if value]
            if not symbols or len(symbols) > 6000:
                errors.append({"instrument": "supplemental", "source": "tradingview", "error": "SourceError"})
                continue
            url = "https://scanner.tradingview.com/%s/scan" % quote(region, safe="")
            payload = {
                "symbols": {"tickers": symbols, "query": {"types": []}},
                "columns": ["close", "change", "change_abs", "current_session", "update_mode"],
            }
            try:
                supplemental.update(parse_tradingview_scan(self.client.post_json(url, payload)))
            except Exception as exc:
                errors.append({"instrument": "supplemental", "source": "tradingview", "error": type(exc).__name__})
        stock_groups = {}
        for group_key, group in ((config or {}).get("us_stock_groups") or {}).items():
            group_quotes = {}
            for stock in group.get("stocks") or []:
                item = {
                    "label": stock.get("name"),
                    "unit": stock.get("unit") or "USD",
                    "sources": [{"kind": stock.get("source") or "tencent", "symbol": stock.get("symbol")}],
                    "expected_session": "us_previous",
                    "contract": "US stock close",
                }
                group_quotes[stock.get("symbol")] = self._collect_one(
                    "us_group:%s:%s" % (group_key, stock.get("symbol")),
                    item, as_of, errors, expected_market_date,
                )
            group_index = None
            index_cfg = group.get("index")
            if index_cfg:
                if index_cfg.get("kind") == "tencent":
                    item = {
                        "label": index_cfg.get("label"),
                        "unit": "USD",
                        "sources": [{"kind": "tencent", "symbol": index_cfg.get("symbol")}],
                        "expected_session": "us_previous",
                        "contract": "US sector index close",
                    }
                    group_index = self._collect_one(
                        "us_group:%s:index" % group_key,
                        item, as_of, errors, expected_market_date,
                    )
                elif index_cfg.get("kind") == "synthetic":
                    members = [str(value) for value in index_cfg.get("members") or []]
                    member_quotes = []
                    for symbol in members:
                        if symbol not in group_quotes:
                            continue
                        member_quotes.append(group_quotes[symbol])
                    group_index = synthesize_index(
                        member_quotes, label=index_cfg.get("label"),
                    )
            stock_groups[group_key] = {
                "name": group.get("name"),
                "stocks": group_quotes,
                "index": group_index,
            }
        return {
            "quotes": quotes,
            "sectors": sectors,
            "sector_extremes": rank_sector_extremes(sectors, limit=5),
            "supplemental": supplemental,
            "stock_groups": stock_groups,
            "errors": errors,
        }
