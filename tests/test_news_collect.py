import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from morning_brief.news_collect import (
    DEFAULT_QUERIES,
    CodexNewsProvider,
    NewsCollector,
    YingmiClient,
    parse_article_metadata,
    parse_yingmi_result,
)


class NewsSourceParserTests(unittest.TestCase):
    def test_parses_yingmi_nested_text_and_preserves_url(self):
        inner = {"data": {"items": [{
            "title": "央行发布政策",
            "summary": "摘要",
            "source": "中国人民银行",
            "publishDate": "2026-07-19T10:00:00+08:00",
            "url": "https://www.pbc.gov.cn/a",
        }]}}
        payload = {"result": {"content": [{"text": json.dumps(inner, ensure_ascii=False)}]}}
        rows = parse_yingmi_result(payload, provider="yingmi:SearchFinancialNews")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["publisher"], "中国人民银行")
        self.assertEqual(rows[0]["url"], "https://www.pbc.gov.cn/a")

    def test_extracts_article_title_and_publish_time(self):
        html = '''<html><head>
        <meta property="og:title" content="美联储维持利率不变">
        <meta property="article:published_time" content="2026-07-19T14:00:00Z">
        </head></html>'''
        metadata = parse_article_metadata(html)
        self.assertEqual(metadata["title"], "美联储维持利率不变")
        self.assertEqual(metadata["published_at"], "2026-07-19T14:00:00Z")


class FakeArticleClient:
    def get_text(self, url, **kwargs):
        if url.endswith("/bad"):
            return '<meta property="og:title" content="完全无关内容">'
        if url.endswith("/nodate"):
            return '<meta property="og:title" content="央行发布重要政策">'
        return '''<meta property="og:title" content="央行发布重要政策">
        <meta property="article:published_time" content="2026-07-19T10:00:00+08:00">'''


class FakeProvider:
    def search(self, tool, query):
        return [{
            "title": "央行发布重要政策",
            "summary": "摘要",
            "publisher": "央行",
            "published_at": "2026-07-19T10:00:00+08:00",
            "url": "https://www.pbc.gov.cn/good",
            "provider": tool,
        }, {
            "title": "错误候选",
            "summary": "摘要",
            "publisher": "央行",
            "published_at": "2026-07-19T10:00:00+08:00",
            "url": "https://www.pbc.gov.cn/bad",
            "provider": tool,
        }]


class NewsCollectorTests(unittest.TestCase):
    def test_program_fetches_candidate_urls_before_accepting(self):
        result = NewsCollector(
            [FakeProvider()], FakeArticleClient(), queries={"宏观": "宏观"}
        ).collect(
            since="2026-07-17T08:00:00+08:00",
            as_of="2026-07-20T07:50:00+08:00",
        )
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["title"], "央行发布重要政策")
        self.assertEqual(len(result["rejected"]), 1)

    def test_matching_title_without_page_publish_date_is_rejected(self):
        class NoDateProvider:
            def search(self, tool, query):
                return [{
                    "title": "央行发布重要政策", "summary": "摘要",
                    "publisher": "央行",
                    "published_at": "2026-07-19T10:00:00+08:00",
                    "url": "https://www.pbc.gov.cn/nodate",
                }]

        result = NewsCollector(
            [NoDateProvider()], FakeArticleClient(),
            queries={"宏观": "宏观"}, tools=("one",),
        ).collect(
            since="2026-07-17T08:00:00+08:00",
            as_of="2026-07-20T07:50:00+08:00",
        )
        self.assertEqual(result["items"], [])
        self.assertEqual(result["validated_count"], 0)

    def test_official_feed_rows_are_accepted_without_media_corroboration(self):
        class Official:
            def collect_official(self):
                return ([{
                    "title": "美联储发布政策声明",
                    "summary": "官方摘要",
                    "publisher": "fed",
                    "published_at": "2026-07-19T14:00:00+00:00",
                    "event_time": None,
                    "url": "https://www.federalreserve.gov/newsevents/pressreleases/a.htm",
                    "provider": "official:fed",
                    "category": "美国与主要央行",
                }], [])

        result = NewsCollector(
            [], FakeArticleClient(), official_providers=[Official()],
            queries={"宏观": "宏观"}, tools=("one",), fallback_threshold=0,
        ).collect(
            since="2026-07-17T08:00:00+08:00",
            as_of="2026-07-20T07:50:00+08:00",
        )
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["verification_status"], "official_single_source")
        self.assertEqual(result["items"][0]["sources"][0]["domain"], "federalreserve.gov")

    def test_fallback_is_triggered_by_publishable_count_not_validated_pages(self):
        calls = []

        class Primary:
            tools = ("one",)

            def search(self, tool, query):
                return [{
                    "title": "央行发布重要政策",
                    "summary": "摘要",
                    "publisher": "媒体甲",
                    "published_at": "2026-07-19T10:00:00+08:00",
                    "url": "https://media-one.example.com/good",
                    "provider": tool,
                }]

        class Fallback:
            tools = ("fallback",)

            def search(self, tool, query):
                calls.append((tool, query))
                return [{
                    "title": "央行发布重要政策",
                    "summary": "摘要",
                    "publisher": "媒体乙",
                    "published_at": "2026-07-19T10:02:00+08:00",
                    "url": "https://media-two.example.net/good",
                    "provider": tool,
                }]

        result = NewsCollector(
            [Primary()], FakeArticleClient(),
            queries={"宏观": "宏观"}, tools=("one",),
            fallback_providers=[Fallback()], fallback_threshold=1,
        ).collect(
            since="2026-07-17T08:00:00+08:00",
            as_of="2026-07-20T07:50:00+08:00",
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["verification_status"], "media_two_source")

    def test_default_queries_cover_market_recap_earnings_and_domestic_futures(self):
        combined = " ".join(DEFAULT_QUERIES.values())

        self.assertIn("美股收盘", combined)
        self.assertIn("财报", combined)
        self.assertIn("国内商品期货收盘", combined)

    def test_fallback_runs_for_missing_required_market_categories_even_when_total_is_enough(self):
        calls = []

        class Official:
            def collect_official(self):
                return ([{
                    "title": "央行发布宏观政策",
                    "summary": "官方摘要",
                    "publisher": "pbc",
                    "published_at": "2026-07-19T09:00:00+08:00",
                    "event_time": None,
                    "url": "https://www.pbc.gov.cn/official.htm",
                    "provider": "official:pbc",
                    "category": "中国宏观与政策",
                }], [])

        class Fallback:
            tools = ("fallback",)

            def search(self, tool, query):
                calls.append(query)
                return []

        result = NewsCollector(
            [], FakeArticleClient(), official_providers=[Official()],
            queries={
                "隔夜美股与财报": "美股收盘 财报",
                "国内商品期货": "国内商品期货收盘",
            },
            fallback_providers=[Fallback()], fallback_threshold=1,
        ).collect(
            since="2026-07-17T08:00:00+08:00",
            as_of="2026-07-20T07:50:00+08:00",
        )

        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(calls, ["美股收盘 财报", "国内商品期货收盘"])
        self.assertEqual(
            result["missing_required_categories"],
            ["隔夜美股与财报", "国内商品期货"],
        )

    def test_batch_capable_fallback_searches_missing_categories_once(self):
        calls = []

        class Official:
            def collect_official(self):
                return ([{
                    "title": "央行发布宏观政策",
                    "summary": "官方摘要",
                    "publisher": "pbc",
                    "published_at": "2026-07-19T09:00:00+08:00",
                    "url": "https://www.pbc.gov.cn/official.htm",
                    "provider": "official:pbc",
                    "category": "中国宏观与政策",
                }], [])

        class BatchFallback:
            def search_many(self, queries):
                calls.append(dict(queries))
                return []

            def search(self, tool, query):
                raise AssertionError("batch fallback must not search serially")

        NewsCollector(
            [], FakeArticleClient(), official_providers=[Official()],
            queries={
                "隔夜美股与财报": "美股收盘 财报",
                "国内商品期货": "国内商品期货收盘",
            },
            fallback_providers=[BatchFallback()], fallback_threshold=1,
        ).collect(
            since="2026-07-17T08:00:00+08:00",
            as_of="2026-07-20T07:50:00+08:00",
        )

        self.assertEqual(calls, [{
            "隔夜美股与财报": "美股收盘 财报",
            "国内商品期货": "国内商品期货收盘",
        }])


class YingmiClientTests(unittest.TestCase):
    def test_api_key_is_sent_via_stdin_not_process_arguments(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs.get("input", b"")))
            body = b'{"jsonrpc":"2.0","id":1,"result":{"content":[]}}'
            return subprocess.CompletedProcess(command, 0, stdout=body, stderr=b"")

        with tempfile.TemporaryDirectory() as directory:
            key_path = Path(directory) / "key"
            key_path.write_text("super-secret-value", encoding="utf-8")
            client = YingmiClient(key_file=key_path, runner=runner)
            with mock.patch.dict("os.environ", {"YINGMI_API_KEY": ""}):
                client.search("SearchFinancialNews", "A股")
        self.assertEqual(len(calls), 2)
        self.assertFalse(any("super-secret-value" in arg for call, _ in calls for arg in call))
        self.assertTrue(all(b"super-secret-value" in sent for _, sent in calls))


class CodexFallbackTests(unittest.TestCase):
    def test_codex_returns_url_candidates_only_for_later_page_validation(self):
        output = json.dumps([{
            "event_key": "fed-policy-statement-2026-07-19",
            "title": "美联储发布声明",
            "summary": "摘要",
            "publisher": "媒体甲",
            "published_at": "2026-07-19T10:00:00-04:00",
            "url": "https://media.example.com/fed",
        }], ensure_ascii=False).encode("utf-8")

        commands = []

        def runner(command, **kwargs):
            commands.append(command)
            self.assertIn("read-only", command)
            return subprocess.CompletedProcess(command, 0, stdout=output, stderr=b"")

        rows = CodexNewsProvider(
            Path("."), runner=runner, executable="/opt/codex/bin/codex"
        ).search(
            "codex_web_search", "美联储"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["url"], "https://media.example.com/fed")
        self.assertEqual(rows[0]["provider"], "codex_web_search")
        self.assertEqual(
            rows[0]["event_key"], "fed-policy-statement-2026-07-19"
        )
        self.assertEqual(commands[0][0], "/opt/codex/bin/codex")
        self.assertIn("--skip-git-repo-check", commands[0])
        self.assertIn("--output-schema", commands[0])
        schema_index = commands[0].index("--output-schema") + 1
        self.assertTrue(commands[0][schema_index].endswith("news_candidates.schema.json"))

    def test_codex_batches_categories_into_one_process(self):
        output = json.dumps([{
            "category": "隔夜美股与财报",
            "event_key": "us-market-close-2026-07-18",
            "title": "美股收盘科技股走弱",
            "summary": "摘要",
            "publisher": "媒体甲",
            "published_at": "2026-07-19T06:00:00+08:00",
            "url": "https://media.example.com/us-close",
        }], ensure_ascii=False).encode("utf-8")
        commands = []

        def runner(command, **kwargs):
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, stdout=output, stderr=b"")

        rows = CodexNewsProvider(
            Path("."), runner=runner, executable="/opt/codex/bin/codex"
        ).search_many({
            "隔夜美股与财报": "美股收盘 财报",
            "国内商品期货": "国内商品期货收盘",
        })

        self.assertEqual(len(commands), 1)
        self.assertEqual(rows[0]["category"], "隔夜美股与财报")
        self.assertIn("国内商品期货", commands[0][-1])


if __name__ == "__main__":
    unittest.main()
