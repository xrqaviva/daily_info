import datetime

from morning_brief.http import SourceError
from morning_brief.models import Observation
from morning_brief.numeric import finite_float


def completed_session_cutoff(as_of):
    """国内商品期货"最近已完成交易日"的自然日语义。

    盘前（<15:05，日盘 15:00 收盘）只认前一自然日及以前；盘后当天算完成日。
    周五夜盘（至周六 02:30）并入周五 K 线，周六盘前 cutoff=周五，天然正确。
    """
    try:
        moment = datetime.datetime.fromisoformat(str(as_of))
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone(
            datetime.timezone(datetime.timedelta(hours=8)))
    cutoff = moment.date()
    if moment.time() < datetime.time(15, 5):
        cutoff = cutoff - datetime.timedelta(days=1)
    return cutoff.isoformat()


def parse_eastmoney_futures(
    payload, *, instrument, unit, url, as_of, contract=None,
    expected_market_date=None,
):
    try:
        raw_rows = payload["data"]["klines"]
    except (KeyError, TypeError):
        raise SourceError("Eastmoney futures response has no klines")
    try:
        cutoff = datetime.datetime.fromisoformat(str(as_of)).date().isoformat()
    except ValueError:
        cutoff = None
    # 只认已完成交易日：盘前时段当日行是未完成/夜盘占位数据，不得参与核验
    # 或覆盖上一完整收盘（AGENTS.md 第3条；2026-08-24 上期所镍/锡、铁矿石
    # 双源冲突空缺事故）。expected_market_date 提供时取更严者。
    strict = completed_session_cutoff(as_of)
    if strict:
        cutoff = min(cutoff, strict) if cutoff else strict
    if expected_market_date:
        cutoff = min(cutoff, str(expected_market_date)) if cutoff else str(expected_market_date)
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
