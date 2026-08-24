import json
import datetime

from morning_brief.http import SourceError
from morning_brief.models import Observation
from morning_brief.numeric import finite_float


def parse_sina_futures_daily(
    text, *, instrument, unit, url, as_of, contract=None,
    expected_market_date=None,
):
    raw = str(text or "")
    start = raw.find("(")
    end = raw.rfind(")")
    if start < 0 or end <= start:
        raise SourceError("Sina futures response is not JSONP")
    try:
        payload = json.loads(raw[start + 1:end])
    except (TypeError, ValueError):
        raise SourceError("Sina futures response has invalid JSONP")
    try:
        cutoff = datetime.datetime.fromisoformat(str(as_of)).date().isoformat()
    except ValueError:
        cutoff = None
    # 只认已完成交易日（与 eastmoney_futures 同规则）
    from morning_brief.sources.eastmoney_futures import completed_session_cutoff
    strict = completed_session_cutoff(as_of)
    if strict:
        cutoff = min(cutoff, strict) if cutoff else strict
    if expected_market_date:
        cutoff = min(cutoff, str(expected_market_date)) if cutoff else str(expected_market_date)
    rows = []
    for row in payload if isinstance(payload, list) else []:
        try:
            if isinstance(row, dict):
                date = str(row["d"]).strip()
                close = finite_float(row["c"])
            else:
                date = str(row[0]).strip()
                close = finite_float(row[4])
        except (IndexError, KeyError, TypeError, ValueError):
            continue
        if date and (cutoff is None or date <= cutoff):
            rows.append((date, close))
    if len(rows) < 2:
        raise SourceError("Sina futures requires two complete daily closes")
    rows.sort(key=lambda item: item[0])
    previous_date, previous = rows[-2]
    current_date, current = rows[-1]
    if current_date <= previous_date or previous == 0:
        raise SourceError("Sina futures dates or previous close are invalid")
    return Observation(
        source="sina_futures",
        instrument=instrument,
        value=current,
        previous_value=previous,
        change_pct=round((current / previous - 1) * 100, 2),
        market_date=current_date,
        unit=unit,
        url=url,
        as_of=as_of,
        contract=contract,
    )
