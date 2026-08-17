import json
import datetime
import subprocess
import tempfile
import unittest
from pathlib import Path

from morning_brief.config import load_instruments
from morning_brief.http import CurlClient, SourceError
from morning_brief.sources.eastmoney import parse_eastmoney_snapshot
from morning_brief.sources.eastmoney_futures import parse_eastmoney_futures
from morning_brief.sources.sina import parse_sina_snapshot
from morning_brief.sources.sina_futures import parse_sina_futures_daily
from morning_brief.sources.stooq import parse_stooq_csv
from morning_brief.sources.tungsten import (
    parse_ganzhou_forecast,
    parse_ganzhou_article_url,
    parse_smm_tungsten_rows,
)
from morning_brief.sources.tencent import parse_tencent_global_quote
from morning_brief.sources.yahoo import parse_yahoo_chart


class StooqParserTests(unittest.TestCase):
    def test_uses_last_two_complete_daily_rows(self):
        text = """Date,Open,High,Low,Close,Volume
2026-07-16,6200,6260,6190,6250,1
2026-07-17,6250,6360,6240,6350,2
"""
        item = parse_stooq_csv(
            text,
            instrument="S&P 500",
            unit="points",
            url="https://stooq.example/spx",
            as_of="2026-07-18T07:45:00+08:00",
        )
        self.assertEqual(item.market_date, "2026-07-17")
        self.assertEqual(item.value, 6350.0)
        self.assertEqual(item.previous_value, 6250.0)
        self.assertEqual(item.change_pct, 1.6)

    def test_rejects_missing_previous_close(self):
        with self.assertRaisesRegex(SourceError, "two complete"):
            parse_stooq_csv(
                "Date,Open,High,Low,Close\n2026-07-17,1,1,1,1\n",
                instrument="x", unit="x", url="https://x", as_of="now",
            )

    def test_filters_rows_after_collection_date(self):
        text = """Date,Open,High,Low,Close
2026-07-16,1,1,1,100
2026-07-17,1,1,1,102
2026-07-20,1,1,1,999
"""
        item = parse_stooq_csv(
            text, instrument="x", unit="x", url="https://x",
            as_of="2026-07-18T07:40:00+08:00",
        )
        self.assertEqual(item.market_date, "2026-07-17")
        self.assertEqual(item.value, 102.0)


class YahooParserTests(unittest.TestCase):
    def test_ignores_null_close_and_computes_change(self):
        payload = {
            "chart": {"result": [{
                "timestamp": [1784160000, 1784246400, 1784332800],
                "indicators": {"quote": [{"close": [100.0, None, 102.0]}]},
            }], "error": None}
        }
        item = parse_yahoo_chart(
            payload,
            instrument="ETF",
            unit="USD",
            url="https://query1.finance.yahoo.com/chart/X",
            as_of="2026-07-18T07:45:00+08:00",
        )
        self.assertEqual(item.value, 102.0)
        self.assertEqual(item.previous_value, 100.0)
        self.assertEqual(item.change_pct, 2.0)

    def test_rejects_provider_error(self):
        with self.assertRaisesRegex(SourceError, "Yahoo chart"):
            parse_yahoo_chart(
                {"chart": {"result": None, "error": {"description": "bad"}}},
                instrument="x", unit="x", url="https://x", as_of="now",
            )

    def test_filters_timestamps_after_collection_date(self):
        timestamps = [
            int(datetime.datetime(2026, 7, day, tzinfo=datetime.timezone.utc).timestamp())
            for day in (16, 17, 20)
        ]
        payload = {"chart": {"result": [{
            "timestamp": timestamps,
            "indicators": {"quote": [{"close": [100.0, 102.0, 999.0]}]},
        }], "error": None}}
        item = parse_yahoo_chart(
            payload, instrument="x", unit="x", url="https://x",
            as_of="2026-07-18T07:40:00+08:00",
        )
        self.assertEqual(item.market_date, "2026-07-17")
        self.assertEqual(item.value, 102.0)


class TencentParserTests(unittest.TestCase):
    def test_rejects_non_finite_quote_numbers(self):
        for invalid in ("nan", "inf", "-inf"):
            fields = [""] * 36
            fields[3], fields[4], fields[30], fields[32] = (
                invalid, "6200", "2026-07-17 16:00:00", "1.61"
            )
            with self.assertRaisesRegex(SourceError, "invalid"):
                parse_tencent_global_quote(
                    'v_usINX="%s";' % "~".join(fields),
                    instrument="x",
                    unit="points",
                    url="https://example.com/tencent",
                    as_of="2026-07-18T07:40:00+08:00",
                )

    def test_parses_global_quote_with_explicit_market_date(self):
        fields = [""] * 36
        fields[3] = "6300.50"
        fields[4] = "6200.00"
        fields[30] = "2026-07-17 16:29:28"
        fields[32] = "1.62"
        text = 'v_usINX="%s";' % "~".join(fields)
        item = parse_tencent_global_quote(
            text,
            instrument="标普500", unit="points",
            url="https://qt.gtimg.cn/q=usINX",
            as_of="2026-07-20T07:40:00+08:00",
        )
        self.assertEqual(item.value, 6300.5)
        self.assertEqual(item.previous_value, 6200.0)
        self.assertEqual(item.change_pct, 1.62)
        self.assertEqual(item.market_date, "2026-07-17")

    def test_rejects_future_or_missing_date(self):
        fields = [""] * 36
        fields[3], fields[4], fields[30], fields[32] = "6300", "6200", "2026-07-21 16:00:00", "1.61"
        with self.assertRaisesRegex(SourceError, "date"):
            parse_tencent_global_quote(
                'v_usINX="%s";' % "~".join(fields),
                instrument="x", unit="x", url="https://x",
                as_of="2026-07-20T07:40:00+08:00",
            )


class MarketSnapshotParserTests(unittest.TestCase):
    def test_non_finite_snapshot_numbers_are_suspended(self):
        eastmoney = parse_eastmoney_snapshot({"data": {"diff": [{
            "f12": "600001", "f14": "无效", "f3": "nan", "f2": "inf",
            "f124": "2026-07-17",
        }]}})
        sina = parse_sina_snapshot([{
            "code": "600001", "name": "无效", "changepercent": "nan",
            "trade": "inf", "date": "2026-07-17",
        }])

        self.assertEqual(eastmoney[0]["status"], "suspended")
        self.assertEqual(sina[0]["status"], "suspended")
    def test_eastmoney_preserves_missing_as_suspended(self):
        payload = {"data": {"diff": [
            {"f12": "920001", "f14": "北交样本", "f3": 1.2, "f2": 10.1, "f124": "2026-07-17"},
            {"f12": "600001", "f14": "停牌样本", "f3": "-", "f2": "-", "f124": "2026-07-17"},
        ]}}
        rows = parse_eastmoney_snapshot(payload)
        self.assertEqual(rows[0]["status"], "trading")
        self.assertEqual(rows[1]["status"], "suspended")
        self.assertIsNone(rows[1]["change_pct"])
        self.assertEqual(rows[0]["market_date"], "2026-07-17")

    def test_zero_price_snapshots_are_suspended(self):
        eastmoney = parse_eastmoney_snapshot({"data": {"diff": [
            {"f12": "600001", "f14": "停牌", "f3": 0, "f2": 0, "f124": "2026-07-17"}
        ]}})
        sina = parse_sina_snapshot([
            {"code": "600001", "name": "停牌", "changepercent": "0", "trade": "0", "date": "2026-07-17"}
        ])
        self.assertEqual(eastmoney[0]["status"], "suspended")
        self.assertEqual(sina[0]["status"], "suspended")

    def test_sina_snapshot_rejects_non_list(self):
        with self.assertRaisesRegex(SourceError, "Sina snapshot"):
            parse_sina_snapshot({"error": "limited"})

    def test_sina_snapshot_maps_fields_without_defaulting_to_zero(self):
        rows = parse_sina_snapshot([
            {"code": "000001", "name": "平盘", "changepercent": "0.00", "trade": "9.5", "date": "2026-07-17"},
            {"code": "000002", "name": "缺失", "changepercent": None, "trade": None, "date": "2026-07-17"},
        ])
        self.assertEqual(rows[0]["change_pct"], 0.0)
        self.assertEqual(rows[1]["status"], "suspended")
        self.assertIsNone(rows[1]["change_pct"])
        self.assertEqual(rows[0]["market_date"], "2026-07-17")


class TungstenParserTests(unittest.TestCase):
    def test_uses_same_grade_history_and_labels_non_daily_change(self):
        text = """
黑钨精矿≥65% 390000 395000 392500 元/标吨 2026-07-08
黑钨精矿≥65% 400000 405000 402500 元/标吨 2026-07-15
"""
        item = parse_smm_tungsten_rows(
            text,
            as_of="2026-07-18T07:45:00+08:00",
            url="https://hq.smm.cn/tungsten",
        )
        self.assertEqual(item.market_date, "2026-07-15")
        self.assertEqual(item.value, 402500.0)
        self.assertEqual(item.previous_value, 392500.0)
        self.assertEqual(item.change_pct, 2.55)
        self.assertEqual(item.contract, "黑钨精矿≥65%")

    def test_parses_ganzhou_monthly_forecast_value_and_explicit_change(self):
        text = """发布日期：2026年7月6日
        赣州钨协2026年7月份钨市场预测价：55%黑钨精矿44.8万元/标吨，
        环比6月份报价下调5.7万元/标吨，跌幅11.29%。"""
        item = parse_ganzhou_forecast(
            text,
            as_of="2026-07-20T07:40:00+08:00",
            url="https://example.com/ganzhou",
            instrument="黑钨精矿",
            unit="CNY/metric-tonne-unit",
            contract="黑钨精矿55%协会预测价",
        )
        self.assertEqual(item.value, 448000.0)
        self.assertEqual(item.previous_value, 505000.0)
        self.assertEqual(item.change_pct, -11.29)
        self.assertEqual(item.market_date, "2026-07-06")
        self.assertEqual(item.source, "ganzhou")
        self.assertEqual(
            parse_ganzhou_article_url(
                '<a href="/tungsten/content/103759998">赣州市钨业协会预测价</a>'
            ),
            "https://hq.smm.cn/tungsten/content/103759998",
        )
        live_shape = "发布时间：2026-02-06 11:58；55%黑钨矿67万元/标吨，环比上调21万元/标吨；"
        live_item = parse_ganzhou_forecast(
            live_shape,
            as_of="2026-07-20T07:40:00+08:00",
            url="https://example.com/ganzhou-live",
        )
        self.assertEqual(live_item.value, 670000.0)
        self.assertEqual(live_item.previous_value, 460000.0)

    def test_smm_filters_rows_after_collection_date(self):
        text = """
黑钨精矿≥65% 390000 395000 392500 元/标吨 2026-07-16
黑钨精矿≥65% 400000 405000 402500 元/标吨 2026-07-17
黑钨精矿≥65% 990000 999000 995000 元/标吨 2026-07-21
"""
        item = parse_smm_tungsten_rows(
            text,
            as_of="2026-07-20T07:40:00+08:00",
            url="https://hq.smm.cn/tungsten",
        )
        self.assertEqual(item.market_date, "2026-07-17")
        self.assertEqual(item.value, 402500.0)


class ChinaFuturesParserTests(unittest.TestCase):
    def test_sina_jsonp_uses_last_two_complete_closes(self):
        text = 'callback=([["2026-07-16","20000","20100","19900","20050","1","2","20010"],["2026-07-17","20050","20400","20000","20300","3","4","20250"]]);'
        item = parse_sina_futures_daily(
            text,
            instrument="上期所铝",
            unit="CNY/tonne",
            url="https://stock2.finance.sina.com.cn/futures/al",
            as_of="2026-07-18T07:45:00+08:00",
            contract="main_continuous",
        )
        self.assertEqual(item.source, "sina_futures")
        self.assertEqual(item.market_date, "2026-07-17")
        self.assertEqual(item.value, 20300.0)
        self.assertEqual(item.previous_value, 20050.0)
        self.assertEqual(item.change_pct, 1.25)

    def test_sina_object_rows_and_future_dates_are_filtered(self):
        text = 'callback=([{"d":"2026-07-16","c":"20050"},{"d":"2026-07-17","c":"20300"},{"d":"2026-07-20","c":"21000"}]);'
        item = parse_sina_futures_daily(
            text,
            instrument="上期所铝",
            unit="CNY/tonne",
            url="https://stock2.finance.sina.com.cn/futures/al",
            as_of="2026-07-18T07:45:00+08:00",
        )
        self.assertEqual(item.market_date, "2026-07-17")
        self.assertEqual(item.value, 20300.0)

    def test_eastmoney_futures_uses_close_and_provider_change(self):
        payload = {"data": {"klines": [
            "2026-07-16,20000,20050,20100,19900,1,2,0,0.25,50,0,0,3,0",
            "2026-07-17,20050,20300,20400,20000,3,4,0,1.25,250,0,0,5,0",
        ]}}
        item = parse_eastmoney_futures(
            payload,
            instrument="上期所铝",
            unit="CNY/tonne",
            url="https://push2his.eastmoney.com/futures/al",
            as_of="2026-07-18T07:45:00+08:00",
            contract="main_continuous",
        )
        self.assertEqual(item.source, "eastmoney_futures")
        self.assertEqual(item.market_date, "2026-07-17")
        self.assertEqual(item.value, 20300.0)
        self.assertEqual(item.previous_value, 20050.0)
        self.assertEqual(item.change_pct, 1.25)

    def test_eastmoney_future_dates_are_filtered(self):
        payload = {"data": {"klines": [
            "2026-07-16,20000,20050",
            "2026-07-17,20050,20300",
            "2026-07-20,20300,21000",
        ]}}
        item = parse_eastmoney_futures(
            payload,
            instrument="上期所铝",
            unit="CNY/tonne",
            url="https://push2his.eastmoney.com/futures/al",
            as_of="2026-07-18T07:45:00+08:00",
        )
        self.assertEqual(item.market_date, "2026-07-17")
        self.assertEqual(item.value, 20300.0)

    def test_futures_parsers_reject_missing_history(self):
        with self.assertRaisesRegex(SourceError, "two complete"):
            parse_eastmoney_futures(
                {"data": {"klines": ["2026-07-17,1,2"]}},
                instrument="x", unit="x", url="https://x", as_of="now",
            )


class CurlClientTests(unittest.TestCase):
    def test_transient_empty_reply_is_retried_once(self):
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            if len(calls) == 1:
                return subprocess.CompletedProcess(
                    command, 52, stdout=b"", stderr=b"empty reply"
                )
            return subprocess.CompletedProcess(
                command, 0, stdout=b'{"ok":true}', stderr=b""
            )

        result = CurlClient(runner=runner).get_json("https://example.com/data")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(calls), 2)

    def test_requests_compressed_responses_with_automatic_decompression(self):
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(
                command, 0, stdout=b"ok", stderr=b""
            )

        CurlClient(runner=runner).get_text("https://example.com")

        self.assertIn("--compressed", calls[0])

    def test_rejects_non_https_before_runner(self):
        client = CurlClient(runner=lambda *args, **kwargs: None)
        with self.assertRaisesRegex(SourceError, "HTTPS"):
            client.get_text("http://example.com")

    def test_nonzero_and_empty_responses_are_errors(self):
        def failure(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 28, stdout=b"", stderr=b"timeout")

        with self.assertRaisesRegex(SourceError, "curl rc=28"):
            CurlClient(runner=failure).get_text("https://example.com")

        def empty(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 0, stdout=b"", stderr=b"")

        with self.assertRaisesRegex(SourceError, "empty"):
            CurlClient(runner=empty).get_text("https://example.com")

    def test_gb18030_source_text_preserves_chinese_names(self):
        def gbk(*args, **kwargs):
            return subprocess.CompletedProcess(
                args[0], 0, stdout="退市样本".encode("gb18030"), stderr=b""
            )

        self.assertEqual(
            CurlClient(runner=gbk).get_text("https://example.com"), "退市样本"
        )

    def test_post_json_sends_payload_through_stdin_not_arguments(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs.get("input", b"")))
            return subprocess.CompletedProcess(
                command, 0, stdout=b'{"data":[]}', stderr=b""
            )

        result = CurlClient(runner=runner).post_json(
            "https://scanner.tradingview.com/global/scan",
            {"symbols": {"tickers": ["NASDAQ:IXIC"]}},
        )
        self.assertEqual(result, {"data": []})
        command, sent = calls[0]
        self.assertFalse(any("NASDAQ:IXIC" in part for part in command))
        self.assertIn(b"NASDAQ:IXIC", sent)

    def test_post_json_rejects_control_characters_in_curl_config_values(self):
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(
                command, 0, stdout=b'{"ok":true}', stderr=b""
            )

        with self.assertRaisesRegex(SourceError, "control"):
            CurlClient(runner=runner).post_json(
                "https://example.com/data",
                {"ok": True},
                headers={"X-Test": "safe\nnext = injected"},
            )

        self.assertEqual(calls, [])


class ConfigTests(unittest.TestCase):
    def test_default_config_contains_every_approved_instrument(self):
        config = load_instruments(Path("config/instruments.json"))
        expected = {
            "sp500", "nasdaq", "dow", "dxy", "usdcny", "usdeur",
            "usdjpy", "usdgbp", "gold", "silver", "copper", "wti",
            "aluminum", "tungsten", "ferromolybdenum_smm", "iron_ore",
        }
        self.assertTrue(expected.issubset(config))
        self.assertEqual(len(config["sectors"]), 11)
        self.assertEqual(
            set(config["us_stock_groups"]),
            {"mag7", "storage", "cpo", "ai_apps", "other", "golden_dragon"},
        )
        for key, item in config.items():
            if key in ("sectors", "supplemental", "us_stock_groups"):
                continue
            self.assertGreaterEqual(len(item["sources"]), 1)


if __name__ == "__main__":
    unittest.main()
