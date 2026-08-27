import datetime
from dataclasses import replace as replace_dataclass
from typing import Dict, Iterable
from zoneinfo import ZoneInfo

from .models import Observation, VerificationResult
from .numeric import finite_float


def _relative_difference(left, right):
    denominator = max(abs(float(left)), abs(float(right)))
    if denominator == 0:
        return 0.0
    return abs(float(left) - float(right)) / denominator


def _result(status, observations, reason=None, relative_difference=None):
    return VerificationResult(
        status=status,
        consensus_value=None,
        consensus_change_pct=None,
        observations=tuple(observations),
        reason=reason,
        relative_difference=relative_difference,
    )


def verify_observations(
    observations: Iterable[Observation],
    *,
    value_tolerance: float = 0.002,
    change_tolerance: float = 0.10,
    max_age_days: int = 4,
    expected_market_date=None,
) -> VerificationResult:
    unique = []
    seen_sources = set()
    for item in observations or []:
        if item.source in seen_sources:
            continue
        seen_sources.add(item.source)
        unique.append(item)

    if not unique:
        return _result("unavailable", (), "no_sources")

    try:
        for item in unique:
            finite_float(item.value)
            if item.previous_value is not None:
                finite_float(item.previous_value)
            if item.change_pct is not None:
                finite_float(item.change_pct)
    except (TypeError, ValueError):
        return _result("conflict", unique, "invalid_numeric_value")

    if len(unique) > 1:
        # When sources disagree on the market date, a strict majority sharing
        # the same date wins (one lagging source must not blank the consensus);
        # otherwise the original mismatch classification is kept below.
        by_date = {}
        for item in unique:
            by_date.setdefault(item.market_date, []).append(item)
        if len(by_date) > 1:
            # 2026-08-27 用户报告：美元指数双源日期 08-26/08-27 不一致被判空。
            # expected_market_date 已知时，日期与预期一致的源优先（盘前预刻戳
            # 的当日源不得覆盖最近已完成交易日口径——AGENTS.md 第3/11条）；
            # 仅剩该组即按单源/双源正常校验，不再误报 conflict。
            expected_group = None
            if expected_market_date:
                expected_group = by_date.get(str(expected_market_date))
            if expected_group is not None:
                # 日期与预期一致的源无条件优先（预刻戳/滞后源不参与竞争）
                unique = list(expected_group)
            else:
                groups = sorted(by_date.values(), key=len, reverse=True)
                majority = groups[0]
                rest = sum(len(group) for group in groups[1:])
                if len(majority) >= 2 and len(majority) > rest:
                    unique = list(majority)

    if expected_market_date and any(
        item.market_date != str(expected_market_date) for item in unique
    ):
        # Providers stamp the current calendar day during pre-market/weekend
        # windows although the quote is the last completed session. Accept
        # such future-stamped single-source observations by relabeling them
        # to the expected session date (bounded to a 3-day skew). Multi-source
        # date mixes and same-day live quotes still fail as unexpected.
        expected = str(expected_market_date)
        if len(unique) == 1:
            item = unique[0]
            try:
                item_date = datetime.date.fromisoformat(item.market_date)
                expected_date = datetime.date.fromisoformat(expected)
                as_of = datetime.datetime.fromisoformat(str(item.as_of))
                ny_time = as_of.astimezone(ZoneInfo("America/New_York"))
            except (TypeError, ValueError):
                ny_time = None
            in_trading = (
                ny_time is not None
                and ny_time.weekday() < 5
                and datetime.time(9, 30) <= ny_time.time() < datetime.time(16, 15)
            )
            if (
                item_date > expected_date
                and not in_trading
                and (item_date - expected_date).days <= 3
            ):
                # pre-market/weekend provider stamp: relabel to the completed
                # session so the quote still shows; live intraday stamps fail
                unique = [replace_dataclass(item, market_date=expected)]
            else:
                return _result("conflict", unique, "unexpected_market_date")
        else:
            return _result("conflict", unique, "unexpected_market_date")

    if len(unique) > 1:
        for field in ("instrument", "market_date", "unit", "contract"):
            if len({getattr(item, field) for item in unique}) != 1:
                return _result("conflict", unique, "%s_mismatch" % field)

    market_date = unique[0].market_date
    try:
        session_date = datetime.date.fromisoformat(str(market_date))
        collection_time = datetime.datetime.fromisoformat(str(unique[0].as_of))
    except (TypeError, ValueError):
        return _result("conflict", unique, "invalid_market_date")
    if collection_time.tzinfo is None or collection_time.utcoffset() is None:
        return _result("conflict", unique, "invalid_collection_timestamp")
    collection_date = collection_time.astimezone(
        ZoneInfo("Asia/Shanghai")
    ).date()
    age_days = (collection_date - session_date).days
    if age_days < 0:
        return _result("conflict", unique, "future_market_date")
    if max_age_days is not None and age_days > int(max_age_days):
        return _result("conflict", unique, "stale_market_date")

    if len(unique) == 1:
        return _result("single_source", unique, "only_one_independent_source")

    if any(item.change_pct is None for item in unique):
        return _result(
            "conflict", unique, "change_pct_missing"
        )
    relative_difference = max(
        _relative_difference(left.value, right.value)
        for index, left in enumerate(unique)
        for right in unique[index + 1:]
    )
    changes = [float(item.change_pct) for item in unique]
    change_difference = max(changes) - min(changes)
    if relative_difference > value_tolerance or change_difference > change_tolerance:
        return _result(
            "conflict", unique, "outside_tolerance", relative_difference
        )
    if any(item.previous_value is None for item in unique):
        return _result(
            "conflict", unique, "previous_value_missing"
        )
    previous_difference = max(
        _relative_difference(left.previous_value, right.previous_value)
        for index, left in enumerate(unique)
        for right in unique[index + 1:]
    )
    if previous_difference > value_tolerance:
        return _result(
            "conflict", unique, "previous_value_mismatch", previous_difference
        )
    previous_dates = {
        item.previous_market_date for item in unique
        if item.previous_market_date is not None
    }
    if len(previous_dates) > 1:
        return _result(
            "conflict", unique, "previous_market_date_mismatch"
        )

    left = unique[0]
    return VerificationResult(
        status="verified",
        consensus_value=left.value,
        consensus_change_pct=left.change_pct,
        observations=tuple(unique),
        reason=None,
        relative_difference=relative_difference,
    )


def rank_sector_extremes(
    sectors: Dict[str, VerificationResult], *, limit: int = 3
):
    verified = [
        (name, result.consensus_change_pct)
        for name, result in (sectors or {}).items()
        if result.status == "verified" and result.consensus_change_pct is not None
    ]
    single_source = [
        (name, result.observations[0].change_pct)
        for name, result in (sectors or {}).items()
        if result.status == "single_source"
        and result.observations
        and result.observations[0].change_pct is not None
    ]
    return {
        "top": sorted(verified, key=lambda item: item[1], reverse=True)[:limit],
        "bottom": sorted(verified, key=lambda item: item[1])[:limit],
        "single_source_top": sorted(
            single_source, key=lambda item: item[1], reverse=True
        )[:limit],
        "single_source_bottom": sorted(
            single_source, key=lambda item: item[1]
        )[:limit],
    }
