import unittest

from morning_brief.models import Observation
from morning_brief.sources.binance import (
    parse_binance_klines,
    parse_binance_ticker,
)
from morning_brief.templates import sparkline_ascii, sparkline_svg
from morning_brief.verification import verify_observations


def _obs(source, value, date, change=1.0, as_of="2026-08-27T08:00:00+08:00"):
    return Observation(
        source=source, instrument="测试", value=value, previous_value=100.0,
        change_pct=change, market_date=date, unit="USD", url="t",
        as_of=as_of, contract="c",
    )


class BinanceTests(unittest.TestCase):
    def test_parse_ticker(self):
        payload = {"lastPrice": "78933.55", "prevClosePrice": "78450.00"}
        obs = parse_binance_ticker(payload, instrument="比特币", unit="USD",
                                   as_of="2026-08-27T08:00:00+08:00", url="t")
        self.assertEqual(obs.value, 78933.55)
        self.assertEqual(obs.market_date, "2026-08-27")

    def test_parse_klines(self):
        payload = [
            [1735689600000, "1", "2", "3", "40000", "4", 1735776000000,
             "5", 6, 7, "8", "9"],
            [1735776000000, "1", "2", "3", "41000", "4", 1735862400000,
             "5", 6, 7, "8", "9"],
        ]
        rows = parse_binance_klines(payload, limit=10)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1][1], 41000.0)


class SparklineTests(unittest.TestCase):
    def test_svg_renders_polyline(self):
        svg = sparkline_svg([("a", 100), ("b", 110), ("c", 105)])
        self.assertIn("<svg", svg)
        self.assertIn("<polyline", svg)
        self.assertIn("spark-up", svg)

    def test_svg_requires_two_points(self):
        self.assertEqual(sparkline_svg([("a", 1)]), "")
        self.assertEqual(sparkline_svg([]), "")

    def test_ascii_renders(self):
        text = sparkline_ascii([("a", 1), ("b", 5), ("c", 3)])
        self.assertTrue(text)
        self.assertTrue(all(ch in "▁▂▃▄▅▆▇█" for ch in text))


class VerificationDatePriorityTests(unittest.TestCase):
    """2026-08-27 用户报告回归：美元指数双源日期 08-26/08-27 不一致被判空。"""

    def test_expected_date_wins_over_future_stamp(self):
        result = verify_observations(
            [
                _obs("eastmoney", 99.14, "2026-08-26"),
                _obs("sina", 99.1174, "2026-08-27"),
            ],
            expected_market_date="2026-08-26",
        )
        self.assertEqual(result.status, "single_source")
        self.assertEqual(result.observations[0].market_date, "2026-08-26")

    def test_no_expected_keeps_original_conflict(self):
        result = verify_observations(
            [_obs("a", 1, "2026-08-26"), _obs("b", 2, "2026-08-27")],
            expected_market_date=None,
        )
        self.assertNotEqual(result.status, "verified")


if __name__ == "__main__":
    unittest.main()