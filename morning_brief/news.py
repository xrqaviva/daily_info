import datetime
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


OFFICIAL_DOMAINS = (
    "gov.cn",
    "pbc.gov.cn",
    "stats.gov.cn",
    "csrc.gov.cn",
    "sse.com.cn",
    "szse.cn",
    "bse.cn",
    "mof.gov.cn",
    "ndrc.gov.cn",
    "mofcom.gov.cn",
    "customs.gov.cn",
    "safe.gov.cn",
    "federalreserve.gov",
    "bls.gov",
    "bea.gov",
    "treasury.gov",
    "sec.gov",
    "ecb.europa.eu",
    "imf.org",
    "worldbank.org",
)

IMPORTANT_TERMS = (
    "央行", "人民银行", "美联储", "利率", "降息", "加息", "通胀",
    "CPI", "PPI", "GDP", "就业", "非农", "财政", "关税", "制裁",
    "证监会", "交易所", "监管", "汇率", "房地产", "地缘", "冲突",
)

DOMESTIC_FUTURES_TERMS = (
    "原油", "LU燃油", "燃油", "钯", "铂", "沪银", "沪金", "沪铜",
    "沪铝", "沪锌", "沪铅", "沪镍", "沪锡", "铁矿石", "碳酸锂",
    "多晶硅", "菜粕", "菜油", "豆油", "豆粕", "豆二", "棕榈油",
    "生猪", "鸡蛋", "烧碱", "锰硅", "对二甲苯", "PTA", "瓶片",
)

REQUIRED_MARKET_NEWS_CATEGORIES = (
    "隔夜美股与财报",
    "国内商品期货",
)


def _host(url):
    try:
        parsed = urlsplit(str(url or ""))
    except ValueError:
        return ""
    if parsed.scheme != "https":
        return ""
    return (parsed.hostname or "").lower().strip(".")


def is_official_url(url):
    host = _host(url)
    return bool(host) and any(
        host == domain or host.endswith("." + domain)
        for domain in OFFICIAL_DOMAINS
    )


def _publisher_domain(url):
    host = _host(url)
    if not host:
        return ""
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    if parts[-2:] in (["com", "cn"], ["org", "cn"], ["net", "cn"], ["gov", "cn"]):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _parse_time(value):
    text = str(value or "").strip()
    if not text:
        return None
    if not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?"
        r"(?:Z|[+-]\d{2}:\d{2})",
        text,
    ):
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(ZoneInfo("Asia/Shanghai"))


def _normal_title(value):
    return re.sub(r"[^0-9A-Za-z\u3400-\u9fff]", "", str(value or "")).lower()


def _shingles(value, size=2):
    if len(value) <= size:
        return {value} if value else set()
    return {value[index:index + size] for index in range(len(value) - size + 1)}


def _similar(left, right):
    left = _normal_title(left)
    right = _normal_title(right)
    if not left or not right:
        return False
    left_numbers = set(re.findall(r"\d+(?:\.\d+)?", left))
    right_numbers = set(re.findall(r"\d+(?:\.\d+)?", right))
    if left_numbers and right_numbers and left_numbers != right_numbers:
        return False
    if left in right or right in left:
        return True
    one, two = _shingles(left), _shingles(right)
    return len(one & two) / max(1, len(one | two)) >= 0.52


def _event_key(item):
    value = _normal_title((item or {}).get("event_key"))
    return value if len(value) >= 8 else ""


def _headline_numbers_agree(left, right):
    left_numbers = set(re.findall(r"\d+(?:\.\d+)?", str(left or "")))
    right_numbers = set(re.findall(r"\d+(?:\.\d+)?", str(right or "")))
    return not left_numbers or not right_numbers or left_numbers == right_numbers


def _same_media_event(left, right):
    left_key = _event_key(left)
    right_key = _event_key(right)
    if left_key and right_key and left_key != right_key:
        return False
    return (
        _similar(left.get("title"), right.get("title"))
        and _headline_numbers_agree(left.get("title"), right.get("title"))
    )


def _importance(item):
    supplied = item.get("importance")
    if isinstance(supplied, (int, float)) and not isinstance(supplied, bool):
        return float(supplied)
    text = "%s %s" % (item.get("title") or "", item.get("summary") or "")
    score = float(sum(
        1 for term in IMPORTANT_TERMS if term.lower() in text.lower()
    ))
    if item.get("category") in REQUIRED_MARKET_NEWS_CATEGORIES:
        score += 10.0
    return score


def _source_record(item):
    return {
        "publisher": str(item.get("publisher") or "unknown"),
        "domain": _publisher_domain(item.get("url")),
        "url": str(item.get("url")),
        "published_at": str(item.get("published_at")),
    }


def _domestic_futures_summary_is_consistent(item):
    text = "%s %s" % (item.get("title") or "", item.get("summary") or "")
    if "国内期货" not in text and "国内商品期货" not in text:
        return True
    movements = []
    for term in sorted(DOMESTIC_FUTURES_TERMS, key=len, reverse=True):
        pattern = re.compile(re.escape(term) + r"[^，。；;]{0,8}?(?:涨|跌|平)")
        movements.extend(term for _ in pattern.finditer(text))
    return len(movements) == len(set(movements))


def build_verified_news(candidates, *, since, as_of, max_items=20):
    since_time = _parse_time(since)
    as_of_time = _parse_time(as_of)
    if since_time is None or as_of_time is None or since_time >= as_of_time:
        raise ValueError("news window is invalid")

    usable = []
    for raw in candidates or []:
        item = dict(raw) if isinstance(raw, dict) else {}
        if not _domestic_futures_summary_is_consistent(item):
            continue
        published = _parse_time(item.get("published_at"))
        domain = _publisher_domain(item.get("url"))
        if not item.get("title") or not domain or published is None:
            continue
        if published <= since_time or published > as_of_time:
            continue
        item["_published"] = published
        item["_domain"] = domain
        usable.append(item)

    groups = []
    for item in sorted(usable, key=lambda row: row["_published"]):
        match = next(
            (
                group for group in groups
                if _same_media_event(item, group[0])
            ),
            None,
        )
        if match is None:
            groups.append([item])
        else:
            match.append(item)

    verified = []
    for group in groups:
        official = [item for item in group if is_official_url(item.get("url"))]
        unique_domains = {}
        for item in group:
            unique_domains.setdefault(item["_domain"], item)
        if official:
            selected = official[0]
            sources = [_source_record(selected)]
            status = "official_single_source"
        elif len(unique_domains) >= 2:
            selected = max(group, key=lambda row: (_importance(row), row["_published"]))
            sources = [_source_record(item) for item in list(unique_domains.values())[:2]]
            status = "media_two_source"
        else:
            continue
        verified.append({
            "title": str(selected["title"]),
            "summary": str(selected.get("summary") or ""),
            "category": selected.get("category"),
            "event_time": selected.get("event_time"),
            "published_at": selected["_published"].isoformat(),
            "verification_status": status,
            "importance": _importance(selected),
            "sources": sources,
        })

    verified.sort(
        key=lambda row: (row["importance"], row["published_at"]), reverse=True
    )
    return verified[:max(0, int(max_items))]
