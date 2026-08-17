import datetime
from zoneinfo import ZoneInfo


class MorningBriefPipeline:
    def __init__(
        self, *, calendar, market, breadth, news, writer, state, instruments
    ):
        self.calendar = calendar
        self.market = market
        self.breadth = breadth
        self.news = news
        self.writer = writer
        self.state = state
        self.instruments = instruments

    @staticmethod
    def _calendar_evidence(result):
        sources = {}
        for name, item in (result.get("sources") or {}).items():
            closures = item.get("closures") or ()
            sources[name] = {
                "url": item.get("url"),
                "closure_count": len(closures),
            }
        return {
            "status": result.get("status"),
            "is_trading_day": result.get("is_trading_day"),
            "previous_trading_day": result.get("previous_trading_day"),
            "sources": sources,
            "errors": result.get("errors") or [],
        }

    def run(self, *, as_of, force=False):
        moment = datetime.datetime.fromisoformat(str(as_of))
        if moment.tzinfo is None or moment.utcoffset() is None:
            moment = moment.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        moment = moment.astimezone(ZoneInfo("Asia/Shanghai"))
        as_of = moment.isoformat()
        report_date = moment.date().isoformat()
        calendar_result = self.calendar.check(report_date)
        if calendar_result.get("status") != "confirmed":
            return {
                "status": "blocked",
                "reason": "calendar_unconfirmed",
                "calendar": self._calendar_evidence(calendar_result),
            }
        if not calendar_result.get("is_trading_day"):
            if not force:
                return {
                    "status": "skipped",
                    "reason": "non_trading_day",
                    "calendar": self._calendar_evidence(calendar_result),
                }

        previous_trading_day = calendar_result.get("previous_trading_day")
        # Force runs (manual/weekend) use the newest data the market sources
        # actually return (e.g. Friday US close) instead of being locked to the
        # previous trading day; the normal scheduled run keeps the strict
        # expected date. A-share breadth keeps the previous trading day either
        # way (its sources report the last A-share session).
        market_expected = previous_trading_day if not force else None
        market = self.market.collect(
            self.instruments,
            as_of=as_of,
            expected_market_date=market_expected,
        )
        breadth = self.breadth.collect(
            expected_market_date=previous_trading_day,
            as_of=as_of,
        )
        news = self.news.collect(
            since=self.state.news_since(as_of), as_of=as_of, max_items=20
        )
        model = {
            "schema_version": 1,
            "report_date": report_date,
            "as_of": str(as_of),
            "calendar": self._calendar_evidence(calendar_result),
            "market": market,
            "breadth": breadth,
            "news": news,
        }
        paths = self.writer.write(model)
        result = {
            "status": "generated",
            "report_date": report_date,
            "paths": {key: str(value) for key, value in paths.items()},
        }
        warnings = list(getattr(self.writer, "warnings", ()) or ())
        if warnings:
            result["warnings"] = warnings
        return result
