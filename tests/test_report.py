import json
import copy
import dataclasses
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from morning_brief import report as report_module
from morning_brief.models import BreadthResult, Observation, VerificationResult
from morning_brief.report import ReportWriter, render_html, render_markdown


def observation(source, value, change, url):
    return Observation(
        source=source,
        instrument="标普500",
        value=value,
        previous_value=6200.0,
        change_pct=change,
        market_date="2026-07-17",
        unit="points",
        url=url,
        as_of="2026-07-20T07:50:00+08:00",
    )


def fixture_model():
    first = observation("stooq", 6300.0, 1.61, "https://stooq.com/spx")
    second = observation("yahoo", 6301.0, 1.62, "https://finance.yahoo.com/spx")
    verified = VerificationResult("verified", 6300.0, 1.61, (first, second))
    conflict = VerificationResult(
        "conflict", None, None,
        (first, observation("yahoo", 6400.0, 3.23, "https://finance.yahoo.com/conflict")),
        "outside_tolerance", 0.0156,
    )
    breadth = BreadthResult(
        5000, 3000, 1900, 100, 0.6, 0.38,
        market_date="2026-07-17",
    )
    return {
        "report_date": "2026-07-20",
        "as_of": "2026-07-20T07:50:00+08:00",
        "calendar": {"status": "confirmed", "previous_trading_day": "2026-07-17"},
        "market": {
            "quotes": {"sp500": verified, "dxy": conflict},
            "sectors": {},
            "sector_extremes": {"top": [], "bottom": []},
            "errors": [],
        },
        "breadth": {
            "sources": {"sina": breadth, "eastmoney": breadth},
            "verification": VerificationResult("verified", breadth.to_dict(), None, ()),
            "errors": [],
        },
        "news": {"items": [{
            "title": "央行发布政策",
            "summary": "重要摘要",
            "published_at": "2026-07-19T10:00:00+08:00",
            "event_time": None,
            "verification_status": "official_single_source",
            "importance": 5,
            "sources": [{"publisher": "央行", "domain": "pbc.gov.cn", "url": "https://www.pbc.gov.cn/a", "published_at": "2026-07-19T10:00:00+08:00"}],
        }], "errors": [], "rejected": []},
    }


class ReportRenderTests(unittest.TestCase):
    def test_missing_required_news_categories_are_reported_as_alerts(self):
        model = fixture_model()
        model["news"]["missing_required_categories"] = [
            "隔夜美股与财报", "国内商品期货",
        ]

        for output in (render_markdown(model), render_html(model)):
            self.assertIn("新闻核验缺口", output)
            self.assertIn("隔夜美股与财报", output)
            self.assertIn("国内商品期货", output)

    def test_wrong_date_breadth_keeps_date_but_hides_all_counts(self):
        model = fixture_model()
        live = BreadthResult(
            5178, 2617, 2411, 150, 2617 / 5178, 2411 / 5178,
            market_date="2026-07-28",
            codes=("sh:600001", "sz:000001", "bj:920001"),
            duplicate_codes=("sh:600001",),
        )
        model["breadth"] = {
            "sources": {"eastmoney": live},
            "verification": VerificationResult(
                "conflict", None, None, (), "unexpected_market_date"
            ),
            "errors": [],
        }

        for output in (render_markdown(model), render_html(model)):
            self.assertIn("2026-07-28", output)
            self.assertIn("eastmoney", output)
            self.assertIn("unexpected_market_date", output.replace("\\", ""))
            self.assertNotIn("5,178", output)
            self.assertNotIn("2,617", output)
            self.assertNotIn("2,411", output)
            self.assertNotIn("| 5178 |", output)
            self.assertNotIn(">5178<", output)

    def test_unexpected_market_date_keeps_evidence_but_hides_live_value(self):
        model = fixture_model()
        live = Observation(
            source="sina_live",
            instrument="道琼斯工业",
            value=52999.99,
            previous_value=51947.25,
            change_pct=2.03,
            market_date="2026-07-27",
            unit="points",
            url="https://example.com/live-dow",
            as_of="2026-07-27T22:30:00+08:00",
        )
        model["market"]["quotes"]["dow"] = VerificationResult(
            "conflict", None, None, (live,), "unexpected_market_date"
        )

        markdown = render_markdown(model)
        html = render_html(model)

        for output in (markdown, html):
            self.assertIn("2026-07-27", output)
            self.assertIn("https://example.com/live-dow", output)
            self.assertNotIn("52,999.99", output)

    def test_mixed_history_and_live_date_conflict_hides_all_quote_values(self):
        model = fixture_model()
        friday = observation(
            "history", 51947.25, 0.46, "https://example.com/friday-dow"
        )
        friday = dataclasses.replace(friday, instrument="道琼斯工业", market_date="2026-07-24")
        monday = dataclasses.replace(
            friday,
            source="live",
            value=52999.99,
            previous_value=51947.25,
            change_pct=2.03,
            market_date="2026-07-27",
            url="https://example.com/monday-live-dow",
        )
        model["market"]["quotes"]["dow"] = VerificationResult(
            "conflict", None, None, (friday, monday), "market_date_mismatch"
        )

        for output in (render_markdown(model), render_html(model)):
            self.assertIn("https://example.com/friday-dow", output)
            self.assertIn("https://example.com/monday-live-dow", output)
            self.assertNotIn("51,947.25", output)
            self.assertNotIn("52,999.99", output)

    def test_invalid_date_conflicts_hide_values(self):
        model = fixture_model()
        invalid = dataclasses.replace(
            observation("bad", 52999.99, 2.03, "https://example.com/bad-date"),
            instrument="道琼斯工业",
            market_date="not-a-date",
        )
        for reason in ("invalid_market_date", "invalid_collection_timestamp"):
            model["market"]["quotes"]["dow"] = VerificationResult(
                "conflict", None, None, (invalid,), reason
            )
            for output in (render_markdown(model), render_html(model)):
                self.assertIn("https://example.com/bad-date", output)
                self.assertNotIn("52,999.99", output)

    def test_markdown_escapes_untrusted_news_structure(self):
        model = fixture_model()
        model["news"]["items"][0].update({
            "title": "公告\n## 伪造章节 *加粗*",
            "summary": "<script>alert(1)</script>\n---",
            "event_time": "现在\n- 伪造列表",
            "sources": [{
                "publisher": "来源]伪造",
                "domain": "example.com",
                "url": "https://example.com/path_(one)",
                "published_at": "2026-07-19T10:00:00+08:00",
            }],
        })

        markdown = render_markdown(model)

        self.assertNotIn("\n## 伪造章节", markdown)
        self.assertNotIn("<script>", markdown)
        self.assertNotIn("\n- 伪造列表", markdown)
        self.assertIn(r"\#\# 伪造章节", markdown)
        self.assertIn(r"\<script\>", markdown)

    def test_tungsten_forecast_has_friendly_label_in_small_metals_section(self):
        model = fixture_model()
        model["market"]["quotes"]["tungsten_ganzhou_forecast"] = VerificationResult(
            "single_source",
            None,
            None,
            (Observation(
                source="official",
                instrument="tungsten_ganzhou_forecast",
                value=416500.0,
                previous_value=415000.0,
                change_pct=0.36,
                market_date="2026-07-24",
                unit="CNY/metric-ton-unit",
                url="https://example.com/tungsten",
                as_of="2026-07-27T07:40:00+08:00",
            ),),
            "single_source",
        )

        markdown = render_markdown(model)

        self.assertIn("现货价格", markdown)
        self.assertIn("期货价格", markdown)
        self.assertNotIn("tungsten_ganzhou_forecast：", markdown)

    def test_report_uses_performance_labels_and_explicit_fx_reference_heading(self):
        model = fixture_model()
        model["market"]["sector_extremes"] = {
            "top": [("材料", 1.2), ("工业", 0.8), ("金融", 0.5)],
            "bottom": [("信息技术", -1.4), ("公用事业", 0.2), ("能源", 0.4)],
        }

        markdown = render_markdown(model)
        html = render_html(model)

        for output in (markdown, html):
            self.assertIn("官方日度参考汇率", output)
            self.assertIn("第一名", output)
            self.assertIn("倒数第一名", output)
            self.assertNotIn("跌幅前三", output)
            self.assertNotIn("表现前三", output)

    def test_report_has_europe_section_and_commodities_with_spot_gold_first(self):
        model = fixture_model()

        markdown = render_markdown(model)
        html = render_html(model)

        for output in (markdown, html):
            self.assertIn("欧洲市场", output)
            self.assertIn("现货价格", output)

    def test_markdown_and_html_show_values_changes_dates_status_and_sources(self):
        model = fixture_model()
        markdown = render_markdown(model)
        html = render_html(model)
        for expected in ("绝对变化", "6,300.00", "+100.00", "+1.61%", "+60.00%", "2026-07-17", "已双源核验", "待核验", "https://stooq.com/spx", "央行发布政策"):
            self.assertIn(expected, markdown)
        for expected in ("绝对变化", "6,300.00", "+100.00", "+1.61%", "+60.00%", "2026-07-17", "已双源核验", "待核验", "https://stooq.com/spx", "央行发布政策"):
            self.assertIn(expected, html)

    def test_writer_creates_date_artifacts_and_index_with_same_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = ReportWriter(Path(directory)).write(fixture_model())
            self.assertTrue(paths["markdown"].exists())
            self.assertTrue(paths["html"].exists())
            self.assertTrue(paths["evidence"].exists())
            evidence = json.loads(paths["evidence"].read_text(encoding="utf-8"))
            index_evidence = json.loads((Path(directory) / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence, index_evidence)
            self.assertEqual(evidence["market"]["quotes"]["sp500"]["status"], "verified")
            self.assertIn("https://stooq.com/spx", paths["markdown"].read_text(encoding="utf-8"))
            state = json.loads((Path(directory) / "index" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["last_successful_as_of"], "2026-07-20T07:50:00+08:00")
            self.assertTrue((Path(directory) / "index").is_symlink())
            self.assertEqual(
                (Path(directory) / "index.json").resolve().parent,
                (Path(directory) / "index" / "state.json").resolve().parent,
            )
            self.assertTrue((Path(directory) / "report.css").is_file())
            self.assertIn(
                "report.css",
                (Path(directory) / "index" / "A股盘前晨报.html").read_text(encoding="utf-8"),
            )

    def test_failed_publish_keeps_previous_report_and_state_together(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            writer = ReportWriter(root)
            writer.write(fixture_model())
            previous_run = (root / "index").resolve()
            previous_state = json.loads((root / "index" / "state.json").read_text(encoding="utf-8"))

            second = copy.deepcopy(fixture_model())
            second["report_date"] = "2026-07-21"
            second["as_of"] = "2026-07-21T07:50:00+08:00"
            original = report_module._atomic_symlink

            def fail_commit(path, target):
                if Path(path).name == "index":
                    raise OSError("injected publish failure")
                return original(path, target)

            with mock.patch("morning_brief.report._atomic_symlink", side_effect=fail_commit):
                with self.assertRaisesRegex(OSError, "injected"):
                    writer.write(second)

            self.assertEqual((root / "index").resolve(), previous_run)
            self.assertFalse((root / "2026-07-21").exists())
            self.assertEqual(
                json.loads((root / "index" / "state.json").read_text(encoding="utf-8")),
                previous_state,
            )
            self.assertEqual((root / "index.json").resolve().parent, previous_run)

    def test_dated_alias_failure_after_commit_does_not_turn_success_into_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            writer = ReportWriter(root)
            original = report_module._atomic_symlink

            def fail_dated_alias(path, target):
                if Path(path).name == "2026-07-20":
                    raise OSError("injected dated alias failure")
                return original(path, target)

            with mock.patch(
                "morning_brief.report._atomic_symlink",
                side_effect=fail_dated_alias,
            ):
                paths = writer.write(fixture_model())

            self.assertEqual(
                json.loads(paths["evidence"].read_text(encoding="utf-8"))["report_date"],
                "2026-07-20",
            )
            self.assertEqual(
                json.loads((root / "index" / "state.json").read_text(encoding="utf-8"))["last_report_date"],
                "2026-07-20",
            )
            self.assertEqual(writer.warnings[0]["component"], "dated_alias")

    def test_verification_status_moved_out_of_tables_into_bottom_section(self):
        model = fixture_model()
        markdown = render_markdown(model)
        html = render_html(model)
        for output in (markdown, html):
            self.assertNotIn("| 品种 | 核验状态 |", output)
            self.assertIn("已双源核验", output)
            self.assertIn("待核验", output)
        self.assertIn("## 核验状态", markdown)
        self.assertIn("标普500：已双源核验", markdown)
        self.assertIn("美元指数：待核验（双源冲突）", markdown)
        self.assertIn("A股涨跌家数：已双源核验", markdown)

    def test_rerun_same_date_keeps_first_dated_alias_and_updates_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            writer = ReportWriter(root)
            writer.write(fixture_model())
            first_dated = (root / "2026-07-20").resolve()
            first_run = (root / "index").resolve()
            self.assertTrue((root / "2026-07-20").is_symlink())

            second = copy.deepcopy(fixture_model())
            second["as_of"] = "2026-07-20T12:00:00+08:00"
            paths = writer.write(second)

            self.assertEqual((root / "2026-07-20").resolve(), first_dated)
            self.assertNotEqual((root / "index").resolve(), first_run)
            self.assertEqual(
                json.loads((root / "index" / "state.json").read_text(encoding="utf-8"))["last_successful_as_of"],
                "2026-07-20T12:00:00+08:00",
            )
            self.assertEqual(
                json.loads(paths["evidence"].read_text(encoding="utf-8"))["as_of"],
                "2026-07-20T12:00:00+08:00",
            )


if __name__ == "__main__":
    unittest.main()
