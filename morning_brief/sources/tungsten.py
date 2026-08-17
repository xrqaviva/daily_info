import re
import datetime

from morning_brief.http import SourceError
from morning_brief.models import Observation


ROW_RE = re.compile(
    r"(黑钨精矿\s*[≥>=]\s*65%)\s+"
    r"([0-9]+(?:\.[0-9]+)?)\s+([0-9]+(?:\.[0-9]+)?)\s+"
    r"([0-9]+(?:\.[0-9]+)?)\s+(元/标吨)\s+([0-9]{4}-[0-9]{2}-[0-9]{2})"
)


def parse_smm_tungsten_rows(
    text, *, as_of, url, instrument="tungsten", unit=None, contract=None
):
    try:
        cutoff = datetime.datetime.fromisoformat(str(as_of)).date().isoformat()
    except ValueError:
        cutoff = None
    rows = []
    for match in ROW_RE.finditer(str(text or "")):
        grade, _low, _high, midpoint, unit, date = match.groups()
        if cutoff is None or date <= cutoff:
            rows.append((date, float(midpoint), unit, grade.replace(" ", "")))
    rows.sort(key=lambda row: row[0])
    if len(rows) < 2:
        raise SourceError("SMM tungsten requires two same-grade history rows")
    previous = rows[-2]
    current = rows[-1]
    if previous[2:] != current[2:] or previous[1] == 0:
        raise SourceError("SMM tungsten grade or unit changed")
    return Observation(
        source="smm",
        instrument=instrument,
        value=current[1],
        previous_value=previous[1],
        change_pct=round((current[1] / previous[1] - 1) * 100, 2),
        market_date=current[0],
        unit=unit or current[2],
        url=url,
        as_of=as_of,
        contract=contract or current[3],
    )


def parse_ganzhou_article_url(text):
    match = re.search(r'href=["\'](/tungsten/content/\d+)["\']', str(text or ""))
    if not match:
        raise SourceError("Ganzhou tungsten article link is missing")
    return "https://hq.smm.cn" + match.group(1)


def parse_ganzhou_forecast(
    text, *, as_of, url, instrument="tungsten",
    unit="CNY/metric-tonne-unit", contract="黑钨精矿55%协会预测价"
):
    raw = re.sub(r"\s+", "", str(text or ""))
    date_match = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", raw)
    iso_date_match = re.search(r"发布时间[：:]?(20\d{2})-(\d{1,2})-(\d{1,2})", raw)
    value_match = re.search(
        r"55%黑钨(?:精矿|矿)([0-9]+(?:\.[0-9]+)?)万元/标吨", raw
    )
    change_match = re.search(
        r"(?:环比[^，。；;]{0,30})?(上调|下调)([0-9]+(?:\.[0-9]+)?)万元/标吨",
        raw,
    )
    stated_match = re.search(r"(?:涨幅|跌幅)([0-9]+(?:\.[0-9]+)?)%", raw)
    if not (date_match or iso_date_match) or not value_match or not change_match:
        raise SourceError("Ganzhou tungsten forecast fields are incomplete")
    year, month, day = (
        int(value) for value in (date_match or iso_date_match).groups()
    )
    try:
        market_date = datetime.date(year, month, day).isoformat()
        cutoff = datetime.datetime.fromisoformat(str(as_of)).date().isoformat()
    except ValueError:
        raise SourceError("Ganzhou tungsten forecast date is invalid")
    if market_date > cutoff:
        raise SourceError("Ganzhou tungsten forecast is future-dated")
    direction, absolute_change = change_match.groups()
    current = float(value_match.group(1)) * 10000
    delta = float(absolute_change) * 10000
    previous = current - delta if direction == "上调" else current + delta
    if previous <= 0:
        raise SourceError("Ganzhou tungsten prior value is invalid")
    computed = round((current / previous - 1) * 100, 2)
    if stated_match:
        stated_pct = float(stated_match.group(1))
        signed_stated = stated_pct if direction == "上调" else -stated_pct
        if abs(computed - signed_stated) > 0.10:
            raise SourceError("Ganzhou tungsten stated change does not match values")
    return Observation(
        source="ganzhou",
        instrument=instrument,
        value=current,
        previous_value=previous,
        change_pct=computed,
        market_date=market_date,
        unit=unit,
        url=url,
        as_of=as_of,
        contract=contract,
    )
