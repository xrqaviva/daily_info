import csv
import datetime
import io

from morning_brief.http import SourceError
from morning_brief.models import Observation
from morning_brief.numeric import finite_float


def _change_pct(current, previous):
    if previous == 0:
        raise SourceError("previous close is zero")
    return round((current / previous - 1) * 100, 2)


def parse_stooq_csv(text, *, instrument, unit, url, as_of, contract=None):
    try:
        cutoff = datetime.datetime.fromisoformat(str(as_of)).date().isoformat()
    except ValueError:
        cutoff = None
    rows = []
    for row in csv.DictReader(io.StringIO(str(text or ""))):
        try:
            date = str(row.get("Date") or "").strip()
            close = finite_float(row.get("Close"))
        except (TypeError, ValueError):
            continue
        if date and (cutoff is None or date <= cutoff):
            rows.append((date, close))
    if len(rows) < 2:
        raise SourceError("Stooq requires two complete daily rows")
    previous_date, previous = rows[-2]
    current_date, current = rows[-1]
    if current_date <= previous_date:
        raise SourceError("Stooq dates are not increasing")
    return Observation(
        source="stooq",
        instrument=instrument,
        value=current,
        previous_value=previous,
        change_pct=_change_pct(current, previous),
        market_date=current_date,
        unit=unit,
        url=url,
        as_of=as_of,
        contract=contract,
    )
