import datetime

from morning_brief.http import SourceError
from morning_brief.models import Observation
from morning_brief.numeric import finite_float


def parse_yahoo_chart(payload, *, instrument, unit, url, as_of, contract=None):
    try:
        chart = payload["chart"]
        result = chart["result"][0]
        timestamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError):
        raise SourceError("Yahoo chart response has no usable result")
    try:
        cutoff = datetime.datetime.fromisoformat(str(as_of)).date().isoformat()
    except ValueError:
        cutoff = None
    complete = []
    for timestamp, close in zip(timestamps or [], closes or []):
        if close is None or isinstance(close, bool):
            continue
        try:
            date = datetime.datetime.fromtimestamp(
                int(timestamp), tz=datetime.timezone.utc
            ).date().isoformat()
            if cutoff is None or date <= cutoff:
                complete.append((date, finite_float(close)))
        except (OSError, OverflowError, TypeError, ValueError):
            continue
    if len(complete) < 2:
        raise SourceError("Yahoo chart requires two complete daily closes")
    previous_date, previous = complete[-2]
    current_date, current = complete[-1]
    if current_date <= previous_date or previous == 0:
        raise SourceError("Yahoo chart dates or previous close are invalid")
    return Observation(
        source="yahoo",
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
