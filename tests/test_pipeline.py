import tempfile
import unittest
from pathlib import Path

from morning_brief.pipeline import MorningBriefPipeline
from morning_brief.state import StateStore


class Stub:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def check(self, value):
        self.calls.append(value)
        return self.result

    def collect(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


class WriterStub:
    def __init__(self):
        self.models = []

    def write(self, model):
        self.models.append(model)
        return {"markdown": Path("report.md"), "html": Path("report.html"), "evidence": Path("evidence.json")}


class PipelineTests(unittest.TestCase):
    def test_pipeline_normalizes_collection_time_to_shanghai_once(self):
        with tempfile.TemporaryDirectory() as directory:
            calendar = Stub({
                "status": "confirmed",
                "is_trading_day": True,
                "previous_trading_day": "2026-07-17",
                "sources": {},
                "errors": [],
            })
            market = Stub({"quotes": {}, "sectors": {}, "sector_extremes": {}, "errors": []})
            breadth = Stub({"sources": {}, "verification": None, "errors": []})
            news = Stub({"items": [], "errors": [], "rejected": []})
            writer = WriterStub()

            MorningBriefPipeline(
                calendar=calendar,
                market=market,
                breadth=breadth,
                news=news,
                writer=writer,
                state=StateStore(Path(directory) / "state.json"),
                instruments={"sectors": []},
            ).run(as_of="2026-07-19T23:50:00-08:00")

            normalized = "2026-07-20T15:50:00+08:00"
            self.assertEqual(calendar.calls, ["2026-07-20"])
            self.assertEqual(market.calls[0][1]["as_of"], normalized)
            self.assertEqual(breadth.calls[0][1]["as_of"], normalized)
            self.assertEqual(news.calls[0][1]["as_of"], normalized)
            self.assertEqual(writer.models[0]["as_of"], normalized)

    def test_closed_day_skips_all_collectors_and_does_not_advance_state(self):
        with tempfile.TemporaryDirectory() as directory:
            calendar = Stub({"status": "confirmed", "is_trading_day": False, "previous_trading_day": "2026-07-17", "sources": {}, "errors": []})
            market, breadth, news = Stub({}), Stub({}), Stub({})
            state = StateStore(Path(directory) / "state.json")
            writer = WriterStub()
            result = MorningBriefPipeline(
                calendar=calendar, market=market, breadth=breadth, news=news,
                writer=writer, state=state, instruments={},
            ).run(as_of="2026-07-18T07:40:00+08:00")
            self.assertEqual(result["status"], "skipped")
            self.assertEqual(market.calls, [])
            self.assertEqual(news.calls, [])
            self.assertFalse(state.path.exists())

    def test_unconfirmed_calendar_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            pipeline = MorningBriefPipeline(
                calendar=Stub({"status": "unconfirmed", "is_trading_day": None, "sources": {}, "errors": []}),
                market=Stub({}), breadth=Stub({}), news=Stub({}), writer=WriterStub(),
                state=StateStore(Path(directory) / "state.json"), instruments={},
            )
            result = pipeline.run(as_of="2026-07-20T07:40:00+08:00")
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["reason"], "calendar_unconfirmed")

    def test_success_uses_last_report_window_and_passes_expected_market_date(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StateStore(Path(directory) / "state.json")
            state.mark_success("2026-07-17T07:50:00+08:00", "2026-07-17")
            calendar = Stub({"status": "confirmed", "is_trading_day": True, "previous_trading_day": "2026-07-17", "sources": {"sse": {"url": "https://sse", "closures": set()}, "szse": {"url": "https://szse", "closures": set()}}, "errors": []})
            market = Stub({"quotes": {}, "sectors": {}, "sector_extremes": {"top": [], "bottom": []}, "errors": []})
            breadth = Stub({"sources": {}, "verification": None, "errors": []})
            news = Stub({"items": [], "errors": [], "rejected": []})
            writer = WriterStub()
            result = MorningBriefPipeline(
                calendar=calendar, market=market, breadth=breadth, news=news,
                writer=writer, state=state, instruments={"sectors": []},
            ).run(as_of="2026-07-20T07:50:00+08:00")
            self.assertEqual(result["status"], "generated")
            news_kwargs = news.calls[0][1]
            self.assertEqual(news_kwargs["since"], "2026-07-17T07:50:00+08:00")
            self.assertEqual(writer.models[0]["report_date"], "2026-07-20")
            self.assertEqual(
                market.calls[0][1]["expected_market_date"], "2026-07-17"
            )
            self.assertEqual(
                breadth.calls[0][1]["expected_market_date"], "2026-07-17"
            )
            saved = state.load()
            self.assertEqual(saved["last_successful_as_of"], "2026-07-17T07:50:00+08:00")


class StateStoreTests(unittest.TestCase):
    def test_first_news_window_is_fourteen_days_and_corrupt_state_is_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = StateStore(path)
            self.assertEqual(
                state.news_since("2026-07-20T08:00:00+08:00"),
                "2026-07-06T08:00:00+08:00",
            )
            path.write_text("not-json", encoding="utf-8")
            self.assertEqual(state.load(), {})


if __name__ == "__main__":
    unittest.main()
