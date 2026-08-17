import datetime
from zoneinfo import ZoneInfo

from morning_brief.http import SourceError
from morning_brief.numeric import finite_float


def _number(value):
    if value in (None, "", "-") or isinstance(value, bool):
        return None
    try:
        return finite_float(value)
    except (TypeError, ValueError):
        return None


def _market_date(value):
    if value in (None, "", "-") or isinstance(value, bool):
        return None
    text = str(value).strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    try:
        timestamp = finite_float(value)
    except (TypeError, ValueError):
        return None
    try:
        return datetime.datetime.fromtimestamp(
            timestamp, tz=datetime.timezone.utc
        ).astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None
def parse_eastmoney_snapshot(payload):
    try:
        rows = payload["data"]["diff"]
    except (KeyError, TypeError):
        raise SourceError("Eastmoney snapshot response has no diff list")
    if not isinstance(rows, list):
        raise SourceError("Eastmoney snapshot diff is not a list")
    output = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("f12") or not row.get("f14"):
            continue
        change = _number(row.get("f3"))
        price = _number(row.get("f2"))
        market_date = _market_date(row.get("f124"))
        output.append({
            "code": str(row["f12"]),
            "name": str(row["f14"]),
            "change_pct": change,
            "price": price,
            "market_date": market_date,
            "status": "trading" if change is not None and price is not None and price > 0 else "suspended",
        })
    if not output:
        raise SourceError("Eastmoney snapshot has no usable rows")
    return output
