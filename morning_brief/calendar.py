import datetime
import html
import re


RANGE_RE = re.compile(
    r"(\d{1,2})月(\d{1,2})日[^。；\n]{0,40}?至"
    r"(?:(\d{1,2})月)?(\d{1,2})日[^。；\n]{0,30}?休市"
)


def parse_exchange_closures(text, *, year):
    clean = html.unescape(re.sub(r"<[^>]+>", " ", str(text or "")))
    clean = re.sub(r"\s+", "", clean)
    year = int(year)
    if "%s年" % year not in clean:
        raise ValueError("exchange notice year does not match")
    ranges = []
    for match in RANGE_RE.finditer(clean):
        start_month, start_day, end_month, end_day = match.groups()
        start = datetime.date(year, int(start_month), int(start_day))
        end = datetime.date(year, int(end_month or start_month), int(end_day))
        if end < start or (end - start).days > 31:
            raise ValueError("exchange notice contains invalid range")
        ranges.append((start, end))
    if len(ranges) < 7:
        raise ValueError("exchange annual notice has too few closure ranges")
    dates = set()
    for start, end in ranges:
        current = start
        while current <= end:
            dates.add(current.isoformat())
            current += datetime.timedelta(days=1)
    return dates


class TradingCalendar:
    def __init__(self, client, years):
        self.client = client
        self.years = dict(years or {})

    @staticmethod
    def _previous(date, closures):
        candidate = date - datetime.timedelta(days=1)
        while candidate.weekday() >= 5 or candidate.isoformat() in closures:
            candidate -= datetime.timedelta(days=1)
        return candidate.isoformat()

    def check(self, target):
        date = datetime.date.fromisoformat(str(target))
        year_config = self.years.get(str(date.year)) or {}
        sources = {}
        errors = []
        for source in ("sse", "szse"):
            url = year_config.get(source)
            if not url:
                errors.append({"source": source, "error": "MissingCalendarURL"})
                continue
            try:
                closures = parse_exchange_closures(
                    self.client.get_text(url), year=date.year
                )
                sources[source] = {"url": url, "closures": closures}
            except Exception as exc:
                errors.append({"source": source, "error": type(exc).__name__})

        if len(sources) < 2:
            return {
                "status": "unconfirmed",
                "is_trading_day": None,
                "previous_trading_day": None,
                "sources": sources,
                "errors": errors,
            }
        sse = sources["sse"]["closures"]
        szse = sources["szse"]["closures"]
        if sse != szse:
            return {
                "status": "conflict",
                "is_trading_day": None,
                "previous_trading_day": None,
                "sources": sources,
                "errors": errors,
            }
        is_trading = date.weekday() < 5 and date.isoformat() not in sse
        return {
            "status": "confirmed",
            "is_trading_day": is_trading,
            "previous_trading_day": self._previous(date, sse),
            "sources": sources,
            "errors": errors,
        }
