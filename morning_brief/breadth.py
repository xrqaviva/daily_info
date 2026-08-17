from typing import Iterable

from .models import BreadthResult, VerificationResult
from .numeric import finite_float


def _excluded_name(name):
    text = str(name or "").strip().upper()
    if text.startswith(("XD", "XR", "DR")):
        text = text[2:]
    return (
        text.startswith(("ST", "*ST", "S*ST"))
        or "退市" in text
        or text.endswith("退")
    )


def _venue(row):
    market = str(row.get("market") or "").strip().lower()
    aliases = {
        "sh": "sh", "sha": "sh", "sse": "sh", "shanghai": "sh",
        "sz": "sz", "sze": "sz", "szse": "sz", "shenzhen": "sz",
        "bj": "bj", "bse": "bj", "beijing": "bj",
    }
    if market in aliases:
        return aliases[market]
    code = str(row.get("code") or row.get("symbol") or "").strip().lower()
    if code.startswith(("sh", "sz", "bj")):
        return code[:2]
    digits = "".join(character for character in code if character.isdigit())
    if not digits:
        return None
    if digits.startswith("6"):
        return "sh"
    if digits.startswith(("0", "3")):
        return "sz"
    if digits.startswith(("4", "8", "9")):
        return "bj"
    return None


def _canonical_code(row):
    venue = _venue(row)
    code = str(row.get("code") or row.get("symbol") or "").strip().lower()
    if not venue or not code:
        return None
    if code.startswith(("sh", "sz", "bj")):
        code = code[2:]
    return "%s:%s" % (venue, code)


def calculate_breadth(rows: Iterable[dict]) -> BreadthResult:
    up = down = flat = 0
    codes = set()
    duplicates = set()
    dates = set()
    missing_market_date = False
    for row in rows or []:
        if _excluded_name(row.get("name")):
            continue
        if str(row.get("status") or "trading").lower() != "trading":
            continue
        price = row.get("price")
        if price is None or isinstance(price, bool):
            continue
        try:
            if finite_float(price) <= 0:
                continue
        except (TypeError, ValueError):
            continue
        change = row.get("change_pct")
        if change is None or isinstance(change, bool):
            continue
        try:
            value = finite_float(change)
        except (TypeError, ValueError):
            continue
        code = _canonical_code(row)
        if code is None:
            continue
        if code in codes:
            duplicates.add(code)
            continue
        codes.add(code)
        market_date = str(row.get("market_date") or "").strip()
        if market_date:
            dates.add(market_date)
        else:
            missing_market_date = True
        if value > 0:
            up += 1
        elif value < 0:
            down += 1
        else:
            flat += 1
    sample = up + down + flat
    return BreadthResult(
        sample_size=sample,
        up=up,
        down=down,
        flat=flat,
        up_rate=(up / sample) if sample else None,
        down_rate=(down / sample) if sample else None,
        market_date=(
            next(iter(dates))
            if len(dates) == 1 and not missing_market_date
            else None
        ),
        codes=tuple(sorted(codes)),
        duplicate_codes=tuple(sorted(duplicates)),
    )


def verify_breadth(
    left: BreadthResult,
    right: BreadthResult,
    *,
    expected_market_date=None,
) -> VerificationResult:
    larger_sample = max(left.sample_size, right.sample_size)
    if larger_sample == 0:
        return VerificationResult(
            "unavailable", None, None, (), "empty_breadth", None
        )
    if not left.market_date or not right.market_date:
        return VerificationResult(
            "conflict", None, None, (), "market_date_missing", None
        )
    if left.market_date != right.market_date:
        return VerificationResult(
            "conflict", None, None, (), "market_date_mismatch", None
        )
    if expected_market_date and left.market_date != str(expected_market_date):
        return VerificationResult(
            "conflict", None, None, (), "unexpected_market_date", None
        )
    venues = {code.split(":", 1)[0] for code in left.codes}
    other_venues = {code.split(":", 1)[0] for code in right.codes}
    if not {"sh", "sz", "bj"}.issubset(venues) or not {"sh", "sz", "bj"}.issubset(other_venues):
        return VerificationResult(
            "conflict", None, None, (), "incomplete_market_coverage", None
        )
    # Full-market snapshots legitimately differ in coverage (venue filters,
    # halted-stock handling), so require near-identical code sets rather than
    # exact equality; a wholly different universe still fails.
    union = set(left.codes) | set(right.codes)
    set_mismatch = (len(set(left.codes) ^ set(right.codes)) / len(union)) if union else 1.0
    if set_mismatch > 0.10:
        return VerificationResult(
            "conflict", None, None, (), "eligible_code_set_mismatch", set_mismatch
        )
    sample_difference = abs(left.sample_size - right.sample_size) / larger_sample
    count_tolerance = max(20, larger_sample * 0.005)
    count_difference = max(
        abs(left.up - right.up),
        abs(left.down - right.down),
        abs(left.flat - right.flat),
    )
    if sample_difference > 0.02 or count_difference > count_tolerance:
        return VerificationResult(
            "conflict",
            None,
            None,
            (),
            "breadth_outside_tolerance",
            sample_difference,
        )
    return VerificationResult(
        "verified", left.to_dict(), None, (), None, sample_difference
    )
