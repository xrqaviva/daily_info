import json
import unittest

from morning_brief.market import MarketCollector


STOOQ = """Date,Open,High,Low,Close,Volume
2026-07-16,99,101,98,100,1
2026-07-17,100,103,99,102,2
"""

YAHOO = {
    "chart": {"result": [{
        "timestamp": [1784160000, 1784246400],
        "indicators": {"quote": [{"close": [100.0, 102.0]}]},
    }], "error": None}
}

SINA_FUTURES = 'callback=([["2026-07-16","20000","20100","19900","20050","1","2","20010"],["2026-07-17","20050","20400","20000","20300","3","4","20250"]]);'

EASTMONEY_FUTURES = {"data": {"klines": [
    "2026-07-16,20000,20050,20100,19900,1,2,0,0.25,50,0,0,3,0",
    "2026-07-17,20050,20300,20400,20000,3,4,0,1.25,250,0,0,5,0",
]}}


class FakeClient:
    def __init__(self, fail=()):
        self.fail = set(fail)
        self.urls = []

    def get_text(self, url, **kwargs):
        self.urls.append(url)
        if "stooq" in self.fail:
            raise RuntimeError("stooq down")
        return SINA_FUTURES if "sina.com.cn/futures" in url else STOOQ

    def get_json(self, url, **kwargs):
        self.urls.append(url)
        if "yahoo" in self.fail:
            raise RuntimeError("yahoo down")
        return EASTMONEY_FUTURES if "push2his.eastmoney.com" in url else YAHOO


class MarketCollectorTests(unittest.TestCase):
    def config(self):
        return {
            "sp500": {
                "label": "标普500", "unit": "points", "value_tolerance": 0.002,
                "sources": [
                    {"kind": "stooq", "symbol": "^spx"},
                    {"kind": "yahoo", "symbol": "^GSPC"},
                ],
            },
            "gold": {
                "label": "黄金", "unit": "USD/oz", "commodity": True,
                "sources": [
                    {"kind": "stooq", "symbol": "gc.f"},
                    {"kind": "yahoo", "symbol": "GC=F"},
                ],
            },
            "sectors": [
                {"name": name, "symbol": symbol, "sources": ["stooq", "yahoo"]}
                for name, symbol in [
                    ("科技", "XLK"), ("能源", "XLE"), ("金融", "XLF"),
                    ("工业", "XLI"), ("材料", "XLB"), ("地产", "XLRE"),
                ]
            ],
        }

    def test_collects_quotes_and_url_encodes_symbols(self):
        client = FakeClient()
        result = MarketCollector(client).collect(
            self.config(), as_of="2026-07-18T07:45:00+08:00"
        )
        self.assertEqual(result["quotes"]["sp500"].status, "verified")
        self.assertEqual(result["quotes"]["gold"].status, "verified")
        self.assertTrue(any("%5Espx" in url for url in client.urls))
        self.assertTrue(any("%5EGSPC" in url for url in client.urls))
        self.assertEqual(len(result["sector_extremes"]["top"]), 5)
        self.assertEqual(len(result["sector_extremes"]["bottom"]), 5)

    def test_one_failed_provider_is_single_source_and_error_is_recorded(self):
        result = MarketCollector(FakeClient(fail={"yahoo"})).collect(
            self.config(), as_of="2026-07-18T07:45:00+08:00"
        )
        self.assertEqual(result["quotes"]["sp500"].status, "single_source")
        self.assertIsNone(result["quotes"]["sp500"].consensus_value)
        self.assertTrue(any(x["source"] == "yahoo" for x in result["errors"]))
        self.assertNotIn("stooq down", json.dumps(result["errors"]))

    def test_tencent_index_can_be_a_third_independent_source(self):
        config = {"sp500": {
            "label": "标普500", "unit": "points", "value_tolerance": 0.002,
            "sources": [{"kind": "tencent", "symbol": "usINX"}],
        }, "sectors": []}
        fields = [""] * 36
        fields[3], fields[4], fields[30], fields[32] = "102", "100", "2026-07-17 16:00:00", "2.00"

        class TencentClient(FakeClient):
            def get_text(self, url, **kwargs):
                self.urls.append(url)
                return 'v_usINX="%s";' % "~".join(fields)

        result = MarketCollector(TencentClient()).collect(
            config, as_of="2026-07-20T07:40:00+08:00"
        )
        self.assertEqual(result["quotes"]["sp500"].status, "single_source")
        self.assertEqual(result["quotes"]["sp500"].observations[0].source, "tencent")

    def test_us_index_must_match_latest_completed_nyse_session(self):
        config = {"nasdaq": {
            "label": "纳斯达克", "unit": "points",
            "expected_session": "us_previous",
            "sources": [{"kind": "tencent", "symbol": "usIXIC"}],
        }, "sectors": []}
        fields = [""] * 36
        fields[3], fields[4], fields[30], fields[32] = (
            "25137.69", "25690.90", "2026-07-24 16:00:00", "-2.15"
        )

        class Client(FakeClient):
            def get_text(self, url, **kwargs):
                return 'v_usIXIC="%s";' % "~".join(fields)

        result = MarketCollector(Client()).collect(
            config, as_of="2026-07-24T07:40:00+08:00"
        )

        # pre-market provider stamps (future calendar day) are relabeled to
        # the completed session so the quote still shows (2026-08-17 rule)
        self.assertEqual(result["quotes"]["nasdaq"].status, "single_source")
        self.assertEqual(
            result["quotes"]["nasdaq"].observations[0].market_date, "2026-07-23"
        )

    def test_china_futures_are_verified_from_same_main_continuous_contract(self):
        config = {
            "aluminum": {
                "label": "上期所铝", "unit": "CNY/tonne", "commodity": True,
                "expected_session": "a_previous",
                "sources": [
                    {"kind": "sina_futures", "symbol": "AL0"},
                    {"kind": "eastmoney_futures", "symbol": "113.alm"},
                ],
                "contract": "main_continuous",
            },
            "sectors": [],
        }
        result = MarketCollector(FakeClient()).collect(
            config, as_of="2026-07-18T07:45:00+08:00",
            expected_market_date="2026-07-17",
        )
        self.assertEqual(result["quotes"]["aluminum"].status, "verified")
        self.assertEqual(result["quotes"]["aluminum"].consensus_value, 20300.0)
        self.assertEqual(result["errors"], [])
        self.assertTrue(any("symbol=AL0" in url for url in result["quotes"]["aluminum"].observations[0].url.split()))

    def test_eastmoney_futures_query_uses_a_future_safe_end_date(self):
        client = FakeClient()

        MarketCollector(client)._fetch(
            {"kind": "eastmoney_futures", "symbol": "113.i2609"},
            instrument="铁矿石",
            unit="CNY/tonne",
            as_of="2026-07-24T07:40:00+08:00",
            contract="I2609",
        )

        requested = [url for url in client.urls if "eastmoney.com" in url]
        self.assertEqual(len(requested), 1)
        self.assertIn("end=20500101", requested[0])

    def test_domestic_futures_must_match_previous_a_share_session(self):
        config = {
            "aluminum": {
                "label": "上期所铝", "unit": "CNY/tonne", "commodity": True,
                "expected_session": "a_previous", "contract": "main_continuous",
                "sources": [
                    {"kind": "sina_futures", "symbol": "AL0"},
                    {"kind": "eastmoney_futures", "symbol": "113.alm"},
                ],
            },
            "sectors": [],
        }
        result = MarketCollector(FakeClient()).collect(
            config, as_of="2026-07-18T07:45:00+08:00",
            expected_market_date="2026-07-16",
        )
        self.assertEqual(result["quotes"]["aluminum"].status, "conflict")
        self.assertEqual(result["quotes"]["aluminum"].reason, "unexpected_market_date")

    def test_international_history_does_not_publish_same_day_live_quote(self):
        history = '''var=([
          {"date":"2026-07-23","close":"92.360"},
          {"date":"2026-07-24","close":"90.470"},
          {"date":"2026-07-27","close":"85.280"}
        ]);'''

        class Client(FakeClient):
            def get_text(self, url, **kwargs):
                self.urls.append(url)
                return history

        config = {
            "wti": {
                "label": "WTI原油",
                "unit": "USD/barrel",
                "commodity": True,
                "expected_session": "international_previous",
                "contract": "当月连续",
                "sources": [
                    {"kind": "sina_global_history", "symbol": "CL"},
                ],
            },
            "sectors": [],
        }

        result = MarketCollector(Client()).collect(
            config, as_of="2026-07-27T08:42:00+08:00"
        )

        quote = result["quotes"]["wti"]
        self.assertEqual(quote.status, "single_source")
        self.assertEqual(quote.observations[0].market_date, "2026-07-24")
        self.assertEqual(quote.observations[0].value, 90.47)

    def test_sector_etfs_use_completed_nyse_session_lock(self):
        fields = [""] * 36
        fields[3], fields[4], fields[30], fields[32] = (
            "260.00", "250.00", "2026-07-27 10:30:00", "4.00"
        )

        class Client(FakeClient):
            def get_text(self, url, **kwargs):
                return 'v_usXLK="%s";' % "~".join(fields)

        result = MarketCollector(Client()).collect(
            {
                "sectors": [{
                    "name": "信息技术",
                    "symbol": "XLK",
                    "sources": [{"kind": "tencent", "symbol": "usXLK"}],
                }],
            },
            as_of="2026-07-27T22:30:00+08:00",
        )

        sector = result["sectors"]["信息技术"]
        self.assertEqual(sector.status, "conflict")
        self.assertEqual(sector.reason, "unexpected_market_date")
        self.assertEqual(result["sector_extremes"]["single_source_top"], [])


    def test_official_fx_batches_are_reused_and_hf_is_dual_source(self):
        boc = {"observations": [
            {"d": "2026-07-21", "FXUSDCAD": {"v": "1.4000"}, "FXCNYCAD": {"v": "0.2070"}, "FXEURCAD": {"v": "1.6000"}, "FXJPYCAD": {"v": "0.008600"}, "FXGBPCAD": {"v": "1.8800"}},
            {"d": "2026-07-22", "FXUSDCAD": {"v": "1.4088"}, "FXCNYCAD": {"v": "0.2080"}, "FXEURCAD": {"v": "1.6076"}, "FXJPYCAD": {"v": "0.008640"}, "FXGBPCAD": {"v": "1.8840"}},
        ]}
        boe = "DATE,XUDLBK73,XUDLJYD,XUDLERD,XUDLGBD\n2026-07-21,6.7633,162.79,1.1429,1.3429\n2026-07-22,6.7749,163.115,1.1409,1.3374\n"

        class Client:
            def __init__(self):
                self.urls = []

            def get_json(self, url, **kwargs):
                self.urls.append(url)
                return boc

            def get_text(self, url, **kwargs):
                self.urls.append(url)
                if "bankofengland" in url:
                    return boe
                if "qt.gtimg" in url:
                    return 'v_hf_GC="4063.75,0.33,4063.60,4063.70,4065.00,4024.00,18:27:04,4050.20,4053.40,0,2,1,2026-07-22,Gold";'
                return 'var hq_str_hf_GC="4065.000,,4064.700,4065.000,4065.000,4024.000,18:27:51,4050.200,4053.400,0,1,9,2026-07-22,Gold,0";'

            def post_json(self, url, payload, **kwargs):
                self.urls.append(url)
                return {"data": [{"s": "NASDAQ:IXIC", "d": [25690.9, -0.57, -147.1, "closed", "delayed_streaming_900"]}]}

        config = {
            "usdcny": {"label": "美元/人民币", "unit": "CNY per USD", "sources": [{"kind": "boc", "symbol": "usdcny"}, {"kind": "boe", "symbol": "usdcny"}]},
            "usdjpy": {"label": "美元/日元", "unit": "JPY per USD", "sources": [{"kind": "boc", "symbol": "usdjpy"}, {"kind": "boe", "symbol": "usdjpy"}]},
            "gold": {"label": "COMEX黄金", "unit": "USD/troy oz", "commodity": True, "contract": "provider_continuous", "sources": [{"kind": "hf_tencent", "symbol": "GC"}, {"kind": "hf_sina", "symbol": "GC"}]},
            "supplemental": [{"kind": "tradingview", "scanner": "global", "symbols": ["NASDAQ:IXIC"]}],
            "sectors": [],
        }
        client = Client()
        result = MarketCollector(client).collect(config, as_of="2026-07-23T07:40:00+08:00")
        self.assertEqual(result["quotes"]["usdcny"].status, "verified")
        self.assertEqual(result["quotes"]["usdjpy"].status, "verified")
        self.assertEqual(result["quotes"]["gold"].status, "verified")
        self.assertEqual(sum("bankofcanada" in url for url in client.urls), 1)
        self.assertEqual(sum("bankofengland" in url for url in client.urls), 1)
        self.assertEqual(result["supplemental"]["NASDAQ:IXIC"]["date_quality"], "session_only")


if __name__ == "__main__":
    unittest.main()
