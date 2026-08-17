import threading
import unittest

from morning_brief.breadth_collect import BreadthCollector


def test_collector(client, **kwargs):
    kwargs.setdefault("min_sample_size", 1)
    return BreadthCollector(client, **kwargs)


class FakeClient:
    def __init__(self, fail=()):
        self.fail = set(fail)
        self.urls = []

    def get_json(self, url, **kwargs):
        self.urls.append(url)
        if "sina" in url:
            if "sina" in self.fail:
                raise RuntimeError("private detail must not leak")
            if "node=hs_a" not in url:
                raise RuntimeError("wrong Sina market node")
            page = int(url.split("page=", 1)[1].split("&", 1)[0])
            if page > 1:
                return []
            return [
                {"code": "600001", "name": "沪股", "changepercent": "1", "trade": "10"},
                {"code": "600002", "name": "ST排除", "changepercent": "5", "trade": "2"},
                {"code": "000001", "name": "深股", "changepercent": "-1", "trade": "9"},
                {"code": "920001", "name": "北股", "changepercent": "0", "trade": "8"},
            ]
        if "eastmoney" in url:
            if "eastmoney" in self.fail:
                raise RuntimeError("provider down")
            return {"data": {"total": 3, "diff": [
                {"f12": "600001", "f14": "沪股", "f3": 1, "f2": 10, "f124": "2026-07-17"},
                {"f12": "000001", "f14": "深股", "f3": -1, "f2": 9, "f124": "2026-07-17"},
                {"f12": "920001", "f14": "北股", "f3": 0, "f2": 8, "f124": "2026-07-17"},
            ]}}
        raise AssertionError(url)

    def get_text(self, url, **kwargs):
        self.urls.append(url)
        if "sina" in self.fail:
            raise RuntimeError("private detail must not leak")
        return "\n".join([
            'var hq_str_sh000001="上证指数,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-07-17,15:30:00,00,";',
            'var hq_str_sz399001="深证成指,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-07-17,15:00:00,00";',
            'var hq_str_bj899050="北证50,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-07-17,15:30:00,00,";',
        ])


class BreadthCollectorTests(unittest.TestCase):
    def test_collects_two_full_market_sources_and_verifies(self):
        result = test_collector(FakeClient(), page_size=100).collect(
            expected_market_date="2026-07-17"
        )
        self.assertEqual(result["verification"].status, "verified")
        self.assertEqual(result["sources"]["sina"].sample_size, 3)
        self.assertEqual(result["sources"]["eastmoney"].sample_size, 3)
        self.assertEqual(result["verification"].consensus_value["flat"], 1)

    def test_one_provider_failure_is_single_source_without_consensus(self):
        result = test_collector(FakeClient(fail={"eastmoney"})).collect(
            expected_market_date="2026-07-17"
        )
        self.assertEqual(result["verification"].status, "single_source")
        self.assertIsNone(result["verification"].consensus_value)
        self.assertEqual(result["errors"][0]["error"], "RuntimeError")
        self.assertNotIn("private detail", str(result["errors"]))

    def test_one_provider_with_wrong_date_is_conflict_not_single_source(self):
        class Client(FakeClient):
            def get_json(self, url, **kwargs):
                if "sina" in url:
                    raise RuntimeError("provider down")
                return {"data": {"total": 3, "diff": [
                    {"f12": "600001", "f14": "沪股", "f3": 1, "f2": 10, "f124": "2026-07-18"},
                    {"f12": "000001", "f14": "深股", "f3": -1, "f2": 9, "f124": "2026-07-18"},
                    {"f12": "920001", "f14": "北股", "f3": 0, "f2": 8, "f124": "2026-07-18"},
                ]}}

        result = test_collector(Client(), page_size=100).collect(
            expected_market_date="2026-07-17"
        )

        self.assertEqual(result["verification"].status, "conflict")
        self.assertEqual(result["verification"].reason, "unexpected_market_date")

    def test_single_wrong_date_takes_priority_over_duplicate_codes(self):
        class Client(FakeClient):
            def get_json(self, url, **kwargs):
                if "sina" in url:
                    raise RuntimeError("provider down")
                duplicate = {
                    "f12": "600001", "f14": "沪股", "f3": 1,
                    "f2": 10, "f124": "2026-07-18",
                }
                return {"data": {"total": 4, "diff": [
                    duplicate,
                    dict(duplicate),
                    {"f12": "000001", "f14": "深股", "f3": -1, "f2": 9, "f124": "2026-07-18"},
                    {"f12": "920001", "f14": "北股", "f3": 0, "f2": 8, "f124": "2026-07-18"},
                ]}}

        result = test_collector(Client(), page_size=100).collect(
            expected_market_date="2026-07-17"
        )

        self.assertEqual(result["verification"].reason, "unexpected_market_date")

    def test_eastmoney_is_paged_instead_of_trusting_oversized_page(self):
        class Client(FakeClient):
            def get_json(self, url, **kwargs):
                self.urls.append(url)
                if "sina" in url:
                    raise RuntimeError("provider down")
                page = 1 if "pn=1" in url else 2
                codes = range(1, 101) if page == 1 else range(101, 121)
                return {"data": {"total": 120, "diff": [
                    {
                        "f12": ("6%05d" if index <= 40 else "0%05d" if index <= 80 else "9%05d") % index,
                        "f14": "样本%s" % index,
                        "f3": 1,
                        "f2": 10,
                        "f124": "2026-07-17",
                    }
                    for index in codes
                ]}}

        client = Client()
        result = test_collector(client, page_size=100).collect(
            expected_market_date="2026-07-17"
        )

        self.assertEqual(result["sources"]["eastmoney"].sample_size, 120)
        eastmoney_urls = [url for url in client.urls if "eastmoney" in url]
        self.assertEqual(len(eastmoney_urls), 2)
        self.assertTrue(any("pn=2" in url for url in eastmoney_urls))

    def test_both_fail_are_unavailable(self):
        result = test_collector(FakeClient(fail={"sina", "eastmoney"})).collect(
            expected_market_date="2026-07-17"
        )
        self.assertEqual(result["verification"].status, "unavailable")
        self.assertEqual(result["sources"], {})

    def test_rejects_snapshot_from_wrong_trade_date(self):
        result = test_collector(FakeClient(), page_size=100).collect(
            expected_market_date="2026-07-16"
        )
        self.assertEqual(result["verification"].status, "conflict")
        self.assertEqual(result["verification"].reason, "unexpected_market_date")

    def test_sina_combines_full_market_snapshot_with_three_venue_date_proof(self):
        class Client:
            def __init__(self):
                self.urls = []

            def get_json(self, url, **kwargs):
                self.urls.append(url)
                if "sina" in url and "node=hs_a" in url:
                    page = int(url.split("page=", 1)[1].split("&", 1)[0])
                    if page > 1:
                        return []
                    return [
                        {"code": "600001", "name": "沪股", "changepercent": "1", "trade": "10"},
                        {"code": "000001", "name": "深股", "changepercent": "-1", "trade": "9"},
                        {"code": "920001", "name": "北股", "changepercent": "0", "trade": "8"},
                    ]
                raise RuntimeError("provider down")

            def get_text(self, url, **kwargs):
                self.urls.append(url)
                return "\n".join([
                    'var hq_str_sh000001="上证指数,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-07-17,15:30:00,00,";',
                    'var hq_str_sz399001="深证成指,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-07-17,15:00:00,00";',
                    'var hq_str_bj899050="北证50,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-07-17,15:30:00,00,";',
                ])

            def post_json(self, url, payload, **kwargs):
                raise RuntimeError("provider down")

        client = Client()
        result = test_collector(client, page_size=100).collect(
            expected_market_date="2026-07-17"
        )

        self.assertIn("sina", result["sources"])
        self.assertEqual(result["sources"]["sina"].sample_size, 3)
        self.assertEqual(result["sources"]["sina"].market_date, "2026-07-17")
        self.assertEqual(result["verification"].status, "single_source")

    def test_eastmoney_uses_reachable_delay_snapshot_host(self):
        class Client:
            def get_json(self, url, **kwargs):
                if "push2delay.eastmoney.com" not in url:
                    raise RuntimeError("provider down")
                return {"data": {"total": 3, "diff": [
                    {"f12": "600001", "f14": "沪股", "f3": 1, "f2": 10, "f124": "2026-07-17"},
                    {"f12": "000001", "f14": "深股", "f3": -1, "f2": 9, "f124": "2026-07-17"},
                    {"f12": "920001", "f14": "北股", "f3": 0, "f2": 8, "f124": "2026-07-17"},
                ]}}

            def post_json(self, url, payload, **kwargs):
                raise RuntimeError("provider down")

        result = test_collector(Client(), page_size=100).collect(
            expected_market_date="2026-07-17"
        )

        self.assertIn("eastmoney", result["sources"])
        self.assertEqual(result["sources"]["eastmoney"].sample_size, 3)
        self.assertEqual(result["sources"]["eastmoney"].market_date, "2026-07-17")

    def test_sina_fetches_page_batches_concurrently(self):
        page_two_started = threading.Event()

        class Client(FakeClient):
            def __init__(self):
                super().__init__(fail={"eastmoney"})

            def get_json(self, url, **kwargs):
                if "sina" not in url:
                    return super().get_json(url, **kwargs)
                page = int(url.split("page=", 1)[1].split("&", 1)[0])
                if page == 1 and not page_two_started.wait(0.1):
                    raise RuntimeError("Sina pages were fetched serially")
                if page == 2:
                    page_two_started.set()
                rows = {
                    1: [{"code": "600001", "name": "沪股", "changepercent": "1", "trade": "10"}],
                    2: [{"code": "000001", "name": "深股", "changepercent": "-1", "trade": "9"}],
                    3: [{"code": "920001", "name": "北股", "changepercent": "0", "trade": "8"}],
                }
                return rows.get(page, [])

        result = test_collector(
            Client(), page_size=1, max_pages=4
        ).collect(expected_market_date="2026-07-17")

        self.assertIn("sina", result["sources"])
        self.assertEqual(result["sources"]["sina"].sample_size, 3)

    def test_eastmoney_fetches_page_batches_concurrently(self):
        page_three_started = threading.Event()

        class Client(FakeClient):
            def __init__(self):
                super().__init__(fail={"sina"})

            def get_json(self, url, **kwargs):
                if "eastmoney" not in url:
                    return super().get_json(url, **kwargs)
                page = int(url.split("pn=", 1)[1].split("&", 1)[0])
                if page == 2 and not page_three_started.wait(0.1):
                    raise RuntimeError("Eastmoney pages were fetched serially")
                if page == 3:
                    page_three_started.set()
                codes = {1: "600001", 2: "000001", 3: "920001"}
                code = codes.get(page)
                return {"data": {"total": 3, "diff": [] if code is None else [{
                    "f12": code,
                    "f14": "样本%s" % page,
                    "f3": 1 if page == 1 else -1 if page == 2 else 0,
                    "f2": 10,
                    "f124": "2026-07-17",
                }]}}

        result = test_collector(
            Client(), page_size=1, max_pages=4
        ).collect(expected_market_date="2026-07-17")

        self.assertIn("eastmoney", result["sources"])
        self.assertEqual(result["sources"]["eastmoney"].sample_size, 3)

    def test_matching_truncated_sources_cannot_verify(self):
        class Client(FakeClient):
            def get_json(self, url, **kwargs):
                page_marker = "page=" if "sina" in url else "pn="
                page = int(url.split(page_marker, 1)[1].split("&", 1)[0])
                code = {1: "600001", 2: "000001", 3: "920001", 4: "600004"}[page]
                if "sina" in url:
                    return [{
                        "code": code, "name": "样本", "changepercent": "1", "trade": "10",
                    }]
                return {"data": {"total": 4, "diff": [{
                    "f12": code, "f14": "样本", "f3": 1, "f2": 10,
                    "f124": "2026-07-17",
                }]}}

        result = test_collector(
            Client(), page_size=1, max_pages=3
        ).collect(expected_market_date="2026-07-17")

        self.assertEqual(result["verification"].status, "unavailable")
        self.assertEqual(result["sources"], {})

    def test_eastmoney_rejects_total_drift_between_pages(self):
        class Client(FakeClient):
            def __init__(self):
                super().__init__(fail={"sina"})

            def get_json(self, url, **kwargs):
                if "eastmoney" not in url:
                    return super().get_json(url, **kwargs)
                page = int(url.split("pn=", 1)[1].split("&", 1)[0])
                code = {1: "600001", 2: "000001", 3: "920001"}[page]
                return {"data": {"total": 3 if page == 1 else 4, "diff": [{
                    "f12": code, "f14": "样本", "f3": 1, "f2": 10,
                    "f124": "2026-07-17",
                }]}}

        result = test_collector(
            Client(), page_size=1, max_pages=4
        ).collect(expected_market_date="2026-07-17")

        self.assertNotIn("eastmoney", result["sources"])

    def test_sina_rejects_date_change_across_snapshot_collection(self):
        class Client(FakeClient):
            def __init__(self):
                super().__init__(fail={"eastmoney"})
                self.date_calls = 0

            def get_text(self, url, **kwargs):
                self.date_calls += 1
                date = "2026-07-17" if self.date_calls == 1 else "2026-07-18"
                return "\n".join(
                    'var hq_str_%s="指数,1,%s,15:30:00";' % (symbol, date)
                    for symbol in ("sh000001", "sz399001", "bj899050")
                )

        result = test_collector(
            Client(), page_size=100
        ).collect(expected_market_date="2026-07-17")

        self.assertNotIn("sina", result["sources"])

    def test_sina_short_page_ignores_prefetched_tail_failure(self):
        class Client(FakeClient):
            def __init__(self):
                super().__init__(fail={"eastmoney"})

            def get_json(self, url, **kwargs):
                if "sina" not in url:
                    return super().get_json(url, **kwargs)
                page = int(url.split("page=", 1)[1].split("&", 1)[0])
                if page > 1:
                    raise RuntimeError("tail page unavailable")
                return [
                    {"code": "600001", "name": "沪股", "changepercent": "1", "trade": "10"},
                    {"code": "000001", "name": "深股", "changepercent": "-1", "trade": "9"},
                    {"code": "920001", "name": "北股", "changepercent": "0", "trade": "8"},
                ]

        result = test_collector(
            Client(), page_size=100
        ).collect(expected_market_date="2026-07-17")

        self.assertIn("sina", result["sources"])

    def test_expected_market_date_is_required(self):
        with self.assertRaises(ValueError):
            test_collector(FakeClient()).collect()

    def test_default_minimum_rejects_tiny_matching_snapshots(self):
        result = BreadthCollector(
            FakeClient(), page_size=100
        ).collect(expected_market_date="2026-07-17")

        self.assertEqual(result["verification"].status, "unavailable")
        self.assertEqual(result["sources"], {})

    def test_eastmoney_rejects_fractional_or_boolean_total(self):
        for invalid_total, row_count in ((1000.9, 1000), (True, 1)):
            with self.subTest(total=invalid_total):
                class Client(FakeClient):
                    def __init__(self):
                        super().__init__(fail={"sina"})

                    def get_json(self, url, **kwargs):
                        if "eastmoney" not in url:
                            return super().get_json(url, **kwargs)
                        codes = ["600001", "000001", "920001"]
                        codes.extend(
                            "6%05d" % index for index in range(100, 100 + row_count - 3)
                        )
                        return {"data": {"total": invalid_total, "diff": [
                            {
                                "f12": code, "f14": "样本", "f3": 1,
                                "f2": 10, "f124": "2026-07-17",
                            }
                            for code in codes[:row_count]
                        ]}}

                result = BreadthCollector(
                    Client(), page_size=row_count, max_pages=2
                ).collect(expected_market_date="2026-07-17")

                self.assertNotIn("eastmoney", result["sources"])

    def test_tradingview_china_is_supplemental_without_market_date(self):
        class Client(FakeClient):
            def post_json(self, url, payload, **kwargs):
                self.urls.append(url)
                return {"data": [
                    {"s": "SSE:600001", "d": ["沪股", 10, 1.0, "SSE", "closed", "delayed_streaming_900"]},
                    {"s": "SZSE:000001", "d": ["深股", 9, -1.0, "SZSE", "closed", "delayed_streaming_900"]},
                    {"s": "SSE:600002", "d": ["ST排除", 2, 5.0, "SSE", "closed", "delayed_streaming_900"]},
                ]}

        result = test_collector(Client(), page_size=100).collect(expected_market_date="2026-07-17")
        supplemental = result["supplemental"]["tradingview_china"]
        self.assertEqual(supplemental["coverage"], ["sh", "sz"])
        self.assertEqual(supplemental["sample_size"], 2)
        self.assertIsNone(supplemental["market_date"])
        self.assertEqual(result["verification"].status, "verified")


if __name__ == "__main__":
    unittest.main()
