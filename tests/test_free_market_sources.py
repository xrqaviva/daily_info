import unittest

from morning_brief.http import SourceError
from morning_brief.sources.free_market import (
    latest_completed_international_session,
    latest_completed_nyse_session,
    parse_boc_cross_rates,
    parse_boe_cross_rates,
    parse_cboe_history,
    parse_ecb_cross_rates,
    parse_eastmoney_global_history,
    parse_hf_quote,
    parse_professional_price_history,
    parse_sina_diniw,
    parse_sina_global_history,
    parse_tencent_gz_quote,
    parse_tradingview_scan,
)


AS_OF = "2026-07-23T07:40:00+08:00"
URL = "https://example.com/source"


class FreeMarketSourceTests(unittest.TestCase):
    def test_international_target_session_uses_previous_completed_weekday(self):
        self.assertEqual(
            latest_completed_international_session(
                "2026-07-27T08:42:00+08:00"
            ).isoformat(),
            "2026-07-24",
        )
        self.assertEqual(
            latest_completed_international_session(
                "2026-07-28T07:40:00+08:00"
            ).isoformat(),
            "2026-07-27",
        )

    def test_international_target_session_skips_exchange_holidays(self):
        self.assertEqual(
            latest_completed_international_session(
                "2026-12-28T07:40:00+08:00", market_calendar="uk"
            ).isoformat(),
            "2026-12-24",
        )
        self.assertEqual(
            latest_completed_international_session(
                "2026-12-28T07:40:00+08:00", market_calendar="xetra"
            ).isoformat(),
            "2026-12-23",
        )

    def test_sina_global_history_selects_last_completed_close(self):
        text = '''var=([
          {"date":"2026-07-23","close":"92.360"},
          {"date":"2026-07-24","close":"90.470"},
          {"date":"2026-07-27","close":"85.280"}
        ]);'''

        row = parse_sina_global_history(
            text,
            instrument="WTI原油",
            unit="USD/barrel",
            as_of="2026-07-27T08:42:00+08:00",
            url=URL,
            contract="当月连续",
            expected_market_date="2026-07-24",
        )

        self.assertEqual(row.source, "sina_global_history")
        self.assertEqual(row.market_date, "2026-07-24")
        self.assertEqual(row.previous_market_date, "2026-07-23")
        self.assertEqual(row.value, 90.47)
        self.assertAlmostEqual(row.change_pct, -2.0463, places=4)

    def test_sina_global_history_applies_declared_unit_scale(self):
        text = '''var=([
          {"date":"2026-07-23","close":"633.700"},
          {"date":"2026-07-24","close":"633.850"}
        ]);'''

        row = parse_sina_global_history(
            text,
            instrument="COMEX铜",
            unit="USD/lb",
            as_of="2026-07-27T08:42:00+08:00",
            url=URL,
            contract="front-month continuous",
            expected_market_date="2026-07-24",
            scale=0.01,
        )

        self.assertEqual(row.value, 6.3385)
        self.assertEqual(row.previous_value, 6.337)

    def test_eastmoney_global_history_uses_provider_settlement_change(self):
        payload = {"data": {"klines": [
            "2026-07-23,87.72,92.36,93.50,87.32,379306,0,7.12,6.37,5.53",
            "2026-07-24,92.55,90.47,92.83,87.68,336373,0,5.59,-1.87,-1.72",
            "2026-07-27,86.12,85.29,86.20,83.10,39776,0,3.47,-4.50,-4.02",
        ]}}

        row = parse_eastmoney_global_history(
            payload,
            instrument="WTI原油",
            unit="USD/barrel",
            as_of="2026-07-27T08:42:00+08:00",
            url=URL,
            contract="当月连续",
            expected_market_date="2026-07-24",
        )

        self.assertEqual(row.source, "eastmoney_global_history")
        self.assertEqual(row.market_date, "2026-07-24")
        self.assertEqual(row.value, 90.47)
        self.assertAlmostEqual(row.change_pct, -1.8657, places=4)
        self.assertEqual(row.previous_value, 92.19)
        self.assertEqual(row.previous_market_date, "2026-07-23")

    def test_eastmoney_roll_day_does_not_recompute_from_adjacent_continuous_close(self):
        payload = {"data": {"klines": [
            "2026-07-24,90.47,90.47,92.83,87.68,336373,0,5.59,-1.87,-1.72",
            "2026-07-27,86.12,81.91,86.20,81.10,39776,0,3.47,-8.29,-7.40",
        ]}}

        row = parse_eastmoney_global_history(
            payload,
            instrument="WTI原油",
            unit="USD/barrel",
            as_of="2026-07-28T07:40:00+08:00",
            url=URL,
            contract="front-month continuous",
            expected_market_date="2026-07-27",
        )

        self.assertEqual(row.value, 81.91)
        self.assertEqual(row.previous_value, 89.31)
        self.assertAlmostEqual(row.change_pct, -8.2857, places=4)
        self.assertNotEqual(row.previous_value, 90.47)

    def test_sina_global_history_rejects_impossible_ohlc_roll_row(self):
        text = '''var=([
          {"date":"2026-07-24","open":"90.47","high":"92.83","low":"87.68","close":"90.47"},
          {"date":"2026-07-27","open":"90.47","high":"86.20","low":"81.10","close":"81.91"}
        ]);'''

        with self.assertRaises(SourceError):
            parse_sina_global_history(
                text,
                instrument="WTI原油",
                unit="USD/barrel",
                as_of="2026-07-28T07:40:00+08:00",
                url=URL,
                contract="front-month continuous",
                expected_market_date="2026-07-27",
            )

    def test_tencent_gz_quote_converts_beijing_timestamp_to_market_date(self):
        text = (
            'v_gzFCHI="FCHI~法国CAC40指数~2026-07-25 00:00:00~'
            '8372.28~73.19~0.88~EU~";'
        )

        row = parse_tencent_gz_quote(
            text,
            symbol="FCHI",
            instrument="法国CAC40",
            unit="points",
            as_of="2026-07-27T08:42:00+08:00",
            url=URL,
            contract="cash index close",
            market_timezone="Europe/Paris",
        )

        self.assertEqual(row.market_date, "2026-07-24")
        self.assertEqual(row.value, 8372.28)
        self.assertEqual(row.previous_value, 8299.09)
        self.assertEqual(row.change_pct, 0.88)

    def test_tradingview_is_session_only_supplemental(self):
        payload = {"data": [{"s": "NASDAQ:IXIC", "d": [25690.9, -0.57, -147.1, "closed", "delayed_streaming_900"]}]}
        row = parse_tradingview_scan(payload)["NASDAQ:IXIC"]
        self.assertEqual(row["value"], 25690.9)
        self.assertEqual(row["change_pct"], -0.57)
        self.assertEqual(row["date_quality"], "session_only")
        self.assertNotIn("market_date", row)

    def test_boc_cross_rates_compute_value_previous_and_change(self):
        payload = {"observations": [
            {"d": "2026-07-21", "FXUSDCAD": {"v": "1.4000"}, "FXCNYCAD": {"v": "0.2070"}, "FXEURCAD": {"v": "1.6000"}, "FXJPYCAD": {"v": "0.008600"}, "FXGBPCAD": {"v": "1.8800"}},
            {"d": "2026-07-22", "FXUSDCAD": {"v": "1.4088"}, "FXCNYCAD": {"v": "0.2080"}, "FXEURCAD": {"v": "1.6076"}, "FXJPYCAD": {"v": "0.008640"}, "FXGBPCAD": {"v": "1.8840"}},
            {"d": "2026-07-23", "FXUSDCAD": {"v": "1.4083"}, "FXCNYCAD": {"v": "0.2080"}, "FXEURCAD": {"v": "1.6020"}, "FXJPYCAD": {"v": "0.008600"}, "FXGBPCAD": {"v": "1.8760"}},
        ]}
        rows = parse_boc_cross_rates(payload, as_of=AS_OF, url=URL)
        self.assertAlmostEqual(rows["usdcny"].value, 6.7731, places=4)
        self.assertAlmostEqual(rows["usdjpy"].value, 163.0556, places=4)
        self.assertEqual(rows["usdcny"].market_date, "2026-07-22")
        self.assertIsNotNone(rows["usdcny"].previous_value)
        self.assertEqual(rows["usdcny"].source, "boc")

    def test_boe_series_directions_are_normalized_to_quote_per_usd(self):
        text = "DATE,XUDLBK73,XUDLJYD,XUDLERD,XUDLGBD\n21 Jul 2026,6.7600,162.0,0.8734,0.7463\n22 Jul 2026,6.7749,163.115,0.8765,0.7477\n23 Jul 2026,6.7771,163.92,0.8794,0.7508\n"
        rows = parse_boe_cross_rates(text, as_of=AS_OF, url=URL)
        self.assertEqual(rows["usdcny"].value, 6.7749)
        self.assertEqual(rows["usdeur"].value, 0.8765)
        self.assertEqual(rows["usdgbp"].value, 0.7477)
        self.assertEqual(rows["usdcny"].market_date, "2026-07-22")

    def test_ecb_cross_rates_are_normalized_to_quote_per_usd(self):
        text = """<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref"><Cube><Cube time="2026-07-21"><Cube currency="USD" rate="1.1800"/><Cube currency="JPY" rate="191.16"/><Cube currency="GBP" rate="0.8700"/><Cube currency="CNY" rate="7.9800"/></Cube><Cube time="2026-07-22"><Cube currency="USD" rate="1.1770"/><Cube currency="JPY" rate="191.80"/><Cube currency="GBP" rate="0.8790"/><Cube currency="CNY" rate="7.9740"/></Cube></Cube></gesmes:Envelope>"""

        rows = parse_ecb_cross_rates(text, as_of=AS_OF, url=URL)

        self.assertAlmostEqual(rows["usdcny"].value, 7.9740 / 1.1770, places=6)
        self.assertAlmostEqual(rows["usdeur"].value, 1 / 1.1770, places=6)
        self.assertAlmostEqual(rows["usdjpy"].value, 191.80 / 1.1770, places=6)
        self.assertAlmostEqual(rows["usdgbp"].value, 0.8790 / 1.1770, places=6)
        self.assertEqual(rows["usdcny"].market_date, "2026-07-22")
        self.assertEqual(rows["usdcny"].source, "ecb")

        csv_text = "CURRENCY,TIME_PERIOD,OBS_VALUE\nCNY,2026-07-21,7.9800\nUSD,2026-07-21,1.1800\nJPY,2026-07-21,191.16\nGBP,2026-07-21,0.8700\nCNY,2026-07-22,7.9740\nUSD,2026-07-22,1.1770\nJPY,2026-07-22,191.80\nGBP,2026-07-22,0.8790\n"
        csv_rows = parse_ecb_cross_rates(csv_text, as_of=AS_OF, url=URL)
        self.assertEqual(csv_rows["usdcny"].market_date, "2026-07-22")

    def test_cboe_history_has_explicit_date_and_previous_close(self):
        text = "DATE,OPEN,HIGH,LOW,CLOSE\n07/21/2026,7400,7500,7390,7509.47\n07/22/2026,7500,7520,7480,7498.96\n"
        row = parse_cboe_history(text, instrument="标普500", as_of=AS_OF, url=URL)
        self.assertEqual(row.market_date, "2026-07-22")
        self.assertEqual(row.previous_value, 7509.47)
        self.assertEqual(row.value, 7498.96)
        self.assertEqual(row.source, "cboe")

    def test_cboe_history_accepts_title_case_headers(self):
        text = (
            "Date,Open,High,Low,Close\n"
            "2026-07-16,6300,6350,6290,6324.00\n"
            "2026-07-17,6325,6370,6320,6350.20\n"
        )

        row = parse_cboe_history(
            text, instrument="标普500", as_of=AS_OF, url=URL
        )

        self.assertEqual(row.value, 6350.20)
        self.assertEqual(row.previous_value, 6324.00)

    def test_cboe_history_accepts_official_spx_value_column(self):
        text = (
            "DATE,SPX\n"
            "07/16/2026,6324.00\n"
            "07/17/2026,6350.20\n"
        )

        row = parse_cboe_history(
            text, instrument="标普500", as_of=AS_OF, url=URL
        )

        self.assertEqual(row.value, 6350.20)

    def test_cboe_excludes_same_calendar_day_close_before_nyse_session(self):
        text = (
            "DATE,SPX\n"
            "07/22/2026,7498.96\n"
            "07/23/2026,7408.30\n"
            "07/24/2026,7411.98\n"
        )

        row = parse_cboe_history(
            text,
            instrument="标普500",
            as_of="2026-07-24T07:40:00+08:00",
            url=URL,
        )

        self.assertEqual(row.market_date, "2026-07-23")
        self.assertEqual(row.value, 7408.30)

    def test_tencent_and_sina_hf_quotes_share_explicit_market_date(self):
        tencent = 'v_hf_GC="4063.75,0.33,4063.60,4063.70,4065.00,4024.00,18:27:04,4050.20,4053.40,0,2,1,2026-07-24,Gold";'
        sina = 'var hq_str_hf_GC="4065.000,,4064.700,4065.000,4065.000,4024.000,18:27:51,4050.200,4053.400,0,1,9,2026-07-24,Gold,0";'
        left = parse_hf_quote(tencent, source="tencent", instrument="COMEX黄金", unit="USD/troy oz", as_of="2026-07-24T19:00:00+08:00", url=URL, contract="provider_continuous")
        right = parse_hf_quote(sina, source="sina", instrument="COMEX黄金", unit="USD/troy oz", as_of="2026-07-24T19:00:00+08:00", url=URL, contract="provider_continuous")
        self.assertEqual(left.market_date, "2026-07-24")
        self.assertEqual(right.market_date, "2026-07-24")
        self.assertEqual(left.previous_value, 4050.2)
        self.assertEqual(right.previous_value, 4050.2)

    def test_sina_diniw_uses_explicit_date_and_previous_close(self):
        text = 'var hq_str_DINIW="05:06:46,101.4647,101.4647,101.4469,2865,101.4337,101.5312,101.2447,101.4647,美元指数,2026-07-23";'

        row = parse_sina_diniw(text, as_of=AS_OF, url=URL)

        self.assertEqual(row.value, 101.4647)
        self.assertEqual(row.previous_value, 101.4337)
        self.assertEqual(row.market_date, "2026-07-23")
        self.assertAlmostEqual(row.change_pct, 0.0306, places=4)

    def test_professional_price_history_keeps_contract(self):
        text = "钼铁60% 331000 336000 333500 元/基吨 2026-07-22\n钼铁60% 329000 334000 331500 元/基吨 2026-07-21"
        row = parse_professional_price_history(text, source="smm", instrument="ferromolybdenum", contract="钼铁60%", unit="CNY/base-tonne", as_of=AS_OF, url=URL)
        self.assertEqual(row.value, 333500.0)
        self.assertEqual(row.previous_value, 331500.0)
        self.assertEqual(row.contract, "钼铁60%")

    def test_professional_price_history_parses_smm_embedded_trend(self):
        text = '''<script>{"product_name":"钼铁60%","unit":"元/基吨","price_detail":[{"average":331500,"renew_date":"2026-07-21"},{"average":333500,"renew_date":"2026-07-22"}]}</script>'''

        row = parse_professional_price_history(
            text,
            source="smm",
            instrument="ferromolybdenum",
            contract="钼铁60%",
            unit="CNY/base-tonne",
            as_of=AS_OF,
            url=URL,
        )

        self.assertEqual(row.value, 333500.0)
        self.assertEqual(row.previous_value, 331500.0)
        self.assertEqual(row.market_date, "2026-07-22")

    def test_professional_price_excludes_same_day_row_before_noon(self):
        text = '''{"product_name":"黑钨精矿≥65%","price_detail":[{"average":415000,"renew_date":"2026-07-23"},{"average":416500,"renew_date":"2026-07-24"}]}'''

        with self.assertRaises(Exception):
            parse_professional_price_history(
                text,
                source="smm",
                instrument="tungsten",
                contract="黑钨精矿≥65%",
                unit="CNY/metric-tonne-unit",
                as_of="2026-07-24T07:40:00+08:00",
                url=URL,
            )

    def test_nyse_target_session_handles_weekend_holiday_and_dst(self):
        self.assertEqual(latest_completed_nyse_session("2026-07-23T07:40:00+08:00").isoformat(), "2026-07-22")
        self.assertEqual(latest_completed_nyse_session("2026-07-06T07:40:00+08:00").isoformat(), "2026-07-02")


if __name__ == "__main__":
    unittest.main()
