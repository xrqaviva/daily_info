import json
import re
import unittest
from pathlib import Path


CONFIG = Path(__file__).resolve().parents[1] / "config" / "instruments.json"


class StockGroupsTests(unittest.TestCase):
    """美股分组配置完整性（2026-08-24 用户裁定持久化）。

    背景：golden_dragon 组自建组起 stocks 为空，晨报里金龙指数下长期
    没有辨识度成分股（阿里/拼多多/京东等），而全部结构测试依然通过——
    空列表不违反任何既有契约。本测试把"内容完整性"变成可执行断言：
    任何分组的 stocks 被清空都会在此处变红，防止需求只留在对话记忆里。
    """

    def setUp(self):
        self.groups = json.loads(CONFIG.read_text(encoding="utf-8"))[
            "instruments"]["us_stock_groups"]

    def test_every_group_has_stocks(self):
        for key, group in self.groups.items():
            self.assertTrue(
                group.get("stocks"),
                "美股分组 {}（{}）的 stocks 为空：指数行下必须有辨识度个股".format(
                    key, group.get("name")),
            )

    def test_golden_dragon_constituents(self):
        symbols = [s["symbol"] for s in self.groups["golden_dragon"]["stocks"]]
        expected = [
            "usBABA", "usPDD", "usJD", "usBIDU", "usNTES",
            "usLI", "usXPEV", "usNIO", "usTME", "usBILI",
        ]
        self.assertEqual(
            symbols, expected,
            "金龙指数辨识度成分股清单被改动（用户裁定 2026-08-24）",
        )
        # 指数行必须保留在个股之上
        index = self.groups["golden_dragon"].get("index") or {}
        self.assertEqual(index.get("symbol"), "usHXC")

    def test_stock_symbols_are_tencent_format(self):
        for key, group in self.groups.items():
            for stock in group.get("stocks", []):
                self.assertRegex(
                    stock.get("symbol", ""), r"^(us|jp)[A-Z0-9]+$",
                    "{} 组 {} 的 symbol 格式非法".format(key, stock.get("name")),
                )


if __name__ == "__main__":
    unittest.main()
