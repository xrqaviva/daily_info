import unittest

from morning_brief.sources.free_market import parse_sina_global_history


def _history(rows):
    import json
    return "var _=(" + json.dumps(rows) + ")"


class SinaGlobalHistoryTests(unittest.TestCase):
    """2026-08-24 铝/锌/锡空缺事故回归。

    新浪 LME 品种偶发 "open<low" 行（电子盘开盘与场内最低价合并的结构性矛盾，
    如 AHD 2026-08-21）。解析器此前整行丢弃 → 目标日缺失 → SourceError →
    晨报该品种空缺。管线只消费 close，open 矛盾不否定 close 可信度。
    """

    def test_open_below_low_row_is_kept_when_close_valid(self):
        obs = parse_sina_global_history(
            _history([
                {"date": "2026-08-20", "open": "10", "high": "11",
                 "low": "9.5", "close": "10.5"},
                {"date": "2026-08-21", "open": "3185.5", "high": "3249.5",
                 "low": "3189.0", "close": "3242.0"},
            ]),
            instrument="LME铝", unit="USD/吨",
            as_of="2026-08-24T08:00:00+08:00", url="test", contract="LME",
            expected_market_date="2026-08-21",
        )
        self.assertEqual(obs.market_date, "2026-08-21")
        self.assertEqual(obs.value, 3242.0)

    def test_close_outside_low_high_is_still_rejected(self):
        with self.assertRaises(Exception):
            parse_sina_global_history(
                _history([
                    {"date": "2026-08-20", "open": "10", "high": "11",
                     "low": "9.5", "close": "10.5"},
                    # close 高于 high：不可信，必须丢弃 → 目标日缺失报错
                    {"date": "2026-08-21", "open": "10", "high": "11",
                     "low": "9.5", "close": "99"},
                ]),
                instrument="LME铝", unit="USD/吨",
                as_of="2026-08-24T08:00:00+08:00", url="test", contract="LME",
                expected_market_date="2026-08-21",
            )


if __name__ == "__main__":
    unittest.main()
