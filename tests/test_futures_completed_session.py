import unittest

from morning_brief.sources.eastmoney_futures import parse_eastmoney_futures
from morning_brief.sources.sina_futures import parse_sina_futures_daily


class CompletedSessionFilterTests(unittest.TestCase):
    """2026-08-24 上期所镍/锡、铁矿石双源冲突空缺事故回归。

    as_of 为交易日早间（盘前）时，东财/新浪日 K 已含当日未完成行；
    该行不得参与核验或覆盖上一完整收盘（AGENTS.md 第3条）。
    传入 expected_market_date 后必须只返回 <= expected 的观测。
    """

    EM_PAYLOAD = {"data": {"klines": [
        "2026-08-20,129300,129200,129800,128900,100",
        "2026-08-21,129400,129200,130000,128950,110",
        "2026-08-24,129510,129510,129600,129000,5",   # 当日未完成
    ]}}

    def test_eastmoney_drops_uncompleted_day(self):
        obs = parse_eastmoney_futures(
            dict(self.EM_PAYLOAD), instrument="沪镍", unit="元/吨",
            url="t", as_of="2026-08-24T08:00:00+08:00",
            expected_market_date="2026-08-21")
        self.assertEqual(obs.market_date, "2026-08-21")

    def test_sina_drops_uncompleted_day(self):
        text = 'cb([' \
               '["2026-08-20","x","x","x","129300"],' \
               '["2026-08-21","x","x","x","129200"],' \
               '["2026-08-24","x","x","x","129510"]])'
        obs = parse_sina_futures_daily(
            text, instrument="沪镍", unit="元/吨", url="t",
            as_of="2026-08-24T08:00:00+08:00",
            expected_market_date="2026-08-21")
        self.assertEqual(obs.market_date, "2026-08-21")


if __name__ == "__main__":
    unittest.main()
