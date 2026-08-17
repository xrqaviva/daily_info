import unittest
from pathlib import Path


class HandoffDocumentationTests(unittest.TestCase):
    def test_new_conversation_has_a_stable_daily_report_entrypoint(self):
        agents = Path("AGENTS.md").read_text(encoding="utf-8")
        handoff = Path("docs/日常报告交接.md").read_text(encoding="utf-8")
        readme = Path("README.md").read_text(encoding="utf-8")
        operations = Path("docs/运行与安装.md").read_text(encoding="utf-8")

        self.assertIn("docs/日常报告交接.md", agents)
        self.assertIn("config/market_api_registry.json", agents)
        self.assertIn("python3 -m morning_brief.cli run", handoff)
        self.assertIn("reports/index/A股盘前晨报.md", handoff)
        self.assertIn("最近一个已完成交易日", handoff)
        self.assertIn("不包含 ST", handoff)
        self.assertIn("最多 20 条", handoff)
        self.assertIn("尚未接入生产报告", handoff)
        self.assertIn("重点方向优先", handoff)
        self.assertIn("当前生产报告的美股个股部分", handoff)
        self.assertIn("官方 RSS", readme)
        self.assertIn("日常报告交接", readme)
        self.assertIn("周一至周五 07:40", operations)
        for artifact in (
            "reports/index/A股盘前晨报.md",
            "reports/index/A股盘前晨报.html",
            "reports/index/evidence.json",
            "reports/index/state.json",
        ):
            self.assertIn(artifact, handoff)
        for status in ("generated", "skipped", "blocked", "error"):
            self.assertIn("`%s`" % status, handoff)


if __name__ == "__main__":
    unittest.main()
