import datetime
import json

from morning_brief.http import SourceError
from morning_brief.models import Observation
from morning_brief.numeric import finite_float


def parse_binance_ticker(payload, *, instrument, unit, as_of, url, contract=None):
    """Binance 24h ticker -> Observation（币/美元现货，无 A 股交易日概念）。"""
    try:
        price = finite_float(payload["lastPrice"])
        prev = finite_float(payload["prevClosePrice"])
    except (KeyError, TypeError, ValueError):
        raise SourceError("Binance ticker has no last/prev price")
    if price is None or price <= 0 or prev is None or prev <= 0:
        raise SourceError("Binance ticker price is invalid")
    try:
        moment = datetime.datetime.fromisoformat(str(as_of))
    except (TypeError, ValueError):
        moment = None
    market_date = moment.date().isoformat() if moment else ""
    return Observation(
        source="binance",
        instrument=instrument,
        value=price,
        previous_value=prev,
        change_pct=round((price / prev - 1) * 100, 2),
        market_date=market_date,
        unit=unit,
        url=url,
        as_of=as_of,
        contract=contract,
    )


def parse_binance_klines(payload, *, limit=30):
    """Binance klines -> [(date, close)] 近 limit 个自然日（日线）。"""
    rows = []
    for raw in payload if isinstance(payload, list) else []:
        try:
            ts = int(raw[0])
            close = finite_float(raw[4])
        except (TypeError, ValueError, IndexError):
            continue
        if close is None or close <= 0:
            continue
        date = datetime.datetime.fromtimestamp(
            ts / 1000.0, tz=datetime.timezone.utc
        ).date().isoformat()
        rows.append((date, close))
    return rows[-limit:]