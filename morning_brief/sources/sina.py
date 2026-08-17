from morning_brief.http import SourceError
from morning_brief.numeric import finite_float


def _number(value):
    if value in (None, "", "-") or isinstance(value, bool):
        return None
    try:
        return finite_float(value)
    except (TypeError, ValueError):
        return None


def parse_sina_snapshot(payload):
    if not isinstance(payload, list):
        raise SourceError("Sina snapshot response is not a list")
    output = []
    for row in payload:
        if not isinstance(row, dict) or not row.get("code") or not row.get("name"):
            continue
        change = _number(row.get("changepercent"))
        price = _number(row.get("trade"))
        market_date = row.get("date") or row.get("tradedate") or row.get("trade_date")
        market_date = str(market_date).strip()[:10] if market_date else None
        output.append({
            "code": str(row["code"]),
            "name": str(row["name"]),
            "change_pct": change,
            "price": price,
            "market_date": market_date,
            "status": "trading" if change is not None and price is not None and price > 0 else "suspended",
        })
    if not output:
        raise SourceError("Sina snapshot has no usable rows")
    return output
