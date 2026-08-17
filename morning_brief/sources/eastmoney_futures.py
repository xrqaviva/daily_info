import datetime

from morning_brief.http import SourceError
from morning_brief.models import Observation
from morning_brief.numeric import finite_float


def parse_eastmoney_futures(
    payload, *, instrument, unit, url, as_of, contract=None
):
    try:
        raw_rows = payload["data"]["klines"]
    except (KeyError, TypeError):
        raise SourceError("Eastmoney futures response has no klines")
    try:
        cutoff = datetime.datetime.fromisoformat(str(as_of)).date().isoformat()
    except ValueError:
        cutoff = None
    rows = []
    for raw in raw_rows if isinstance(raw_rows, list) else []:
        fields = str(raw).split(",")
        try:
            date = fields[0].strip()
            close = finite_float(fields[2])
        except (IndexError, TypeError, ValueError):
            continue
        if date and (cutoff is None or date <= cutoff):
            rows.append((date, close))
    if len(rows) < 2:
        raise SourceError("Eastmoney futures requires two complete daily closes")
    rows.sort(key=lambda item: item[0])
    previous_date, previous = rows[-2]
    current_date, current = rows[-1]
    if current_date <= previous_date or previous == 0:
        raise SourceError("Eastmoney futures dates or previous close are invalid")
    return Observation(
        source="eastmoney_futures",
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
