import datetime

from morning_brief.http import SourceError
from morning_brief.models import Observation
from morning_brief.numeric import finite_float


def parse_tencent_global_quote(
    text, *, instrument, unit, url, as_of, contract=None
):
    raw = str(text or "")
    if '="' not in raw:
        raise SourceError("Tencent quote response is invalid")
    body = raw.split('="', 1)[1].split('"', 1)[0]
    fields = body.split("~")
    try:
        value = finite_float(fields[3])
        previous = finite_float(fields[4])
        market_date = str(fields[30]).strip()[:10]
        provider_change = finite_float(fields[32])
        datetime.date.fromisoformat(market_date)
        cutoff = datetime.datetime.fromisoformat(str(as_of)).date().isoformat()
    except (IndexError, TypeError, ValueError):
        raise SourceError("Tencent quote value or date is invalid")
    if market_date > cutoff:
        raise SourceError("Tencent quote date is after collection time")
    if previous == 0:
        raise SourceError("Tencent previous close is zero")
    computed = round((value / previous - 1) * 100, 2)
    if abs(computed - provider_change) > 0.10:
        raise SourceError("Tencent quote change does not match closes")
    return Observation(
        source="tencent",
        instrument=instrument,
        value=value,
        previous_value=previous,
        change_pct=computed,
        market_date=market_date,
        unit=unit,
        url=url,
        as_of=as_of,
        contract=contract,
    )
