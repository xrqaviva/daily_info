import unittest

from morning_brief.templates import HTML_SHELL, REPORT_CSS, md_to_html


class MdToHtmlTests(unittest.TestCase):
    def test_headings_quote_paragraph_and_disclaimer_boundary(self):
        md = (
            "# A股盘前双源晨报｜2026-08-13\n\n"
            "> 规则：只有同口径、同日期的两个独立来源在容差内才显示共识值。\n\n"
            "采集截止：中国时间 2026-08-13T08:00:00+08:00  \n"
            "上一A股交易日：2026-08-12\n\n"
            "## 小节\n\n"
            "一段正文。\n\n"
            "---\n"
            "本报告仅作信息整理，不构成投资建议。\n"
        )
        html = md_to_html(md)
        self.assertIn("<h1>A股盘前双源晨报｜2026-08-13</h1>", html)
        self.assertIn('<p class="rule">规则：只有同口径、同日期的两个独立来源在容差内才显示共识值。</p>', html)
        self.assertIn('<p class="meta">采集截止：中国时间 2026-08-13T08:00:00+08:00</p>', html)
        self.assertIn('<p class="meta">上一A股交易日：2026-08-12</p>', html)
        self.assertIn("<h2>小节</h2>", html)
        self.assertIn("<p>一段正文。</p>", html)
        self.assertNotIn("本报告仅作信息整理", html)

    def test_table_headers_cells_links_and_trend_classes(self):
        md = (
            "| 品种 | 核验状态 | 最新值 | 绝对变化 | 变化比例 | 来源 |\n"
            "|---|---:|---:|---:|---:|---|\n"
            "| 标普500 | 已双源核验 | 7,748.50 | +20.30 | +0.26% | [stooq](https://stooq.com/spx) |\n"
            "| WTI原油 | 待核验（仅单源） | 82.58 | -0.62 | -0.75% | [sina](https://hq.sinajs.cn/wti) |\n"
            "| LME锡 | 不可用 | — | — | — | — |\n"
        )
        html = md_to_html(md)
        self.assertIn('<div class="table-wrap">', html)
        self.assertIn("<table>", html)
        self.assertIn("<thead>", html)
        self.assertIn("<th>品种</th>", html)
        self.assertIn('<a href="https://stooq.com/spx">stooq</a>', html)
        self.assertIn('class="status-verified"', html)
        self.assertIn('class="status-single"', html)
        self.assertIn('class="status-unavailable"', html)
        self.assertIn('class="num up"', html)
        self.assertIn('class="num down"', html)
        self.assertIn('class="num flat"', html)
        self.assertIn('class="src"', html)
        self.assertIn("7,748.50", html)

    def test_multi_source_conflict_cell_stays_neutral(self):
        md = (
            "| 品种 | 核验状态 | 变化比例 |\n|---|---|---:|\n"
            "| 美元/英镑 | 待核验（双源冲突） | boc -0.03% / boe -0.01% / ecb -0.19% |\n"
        )
        html = md_to_html(md)
        self.assertIn('class="status-conflict"', html)
        self.assertIn('class="num"', html)
        self.assertNotIn('class="num up"', html)
        self.assertNotIn('class="num down"', html)

    def test_alert_details_wrapped_and_counted(self):
        md = "## 数据告警\n\n- 纳斯达克：待核验（仅单源）\n- COMEX黄金：待核验（双源冲突）\n"
        html = md_to_html(md)
        self.assertIn('<details class="alert">', html)
        self.assertIn("<summary>数据告警（2 条，点击展开）</summary>", html)
        self.assertIn("<li>纳斯达克：待核验（仅单源）</li>", html)
        self.assertIn("<li>COMEX黄金：待核验（双源冲突）</li>", html)

    def test_news_article_with_official_tag_and_links(self):
        md = (
            "## 重要宏观新闻\n\n"
            "1. **Cash remains most widely accepted payment method**\n"
            "   - 摘要：—\n"
            "   - 事件时间：未单独提供；发布时间：2026-08-13T17:00:00+08:00；核验：官方一手单源\n"
            "   - 来源：[ecb_press](https://www.ecb.europa.eu/a)\n"
        )
        html = md_to_html(md)
        self.assertIn("<article>", html)
        self.assertIn("<h3>1. <strong>Cash remains most widely accepted payment method</strong></h3>", html)
        self.assertIn('<span class="tag official">官方一手单源</span>', html)
        self.assertIn('<a href="https://www.ecb.europa.eu/a">ecb_press</a>', html)
        self.assertIn('class="meta"', html)

    def test_inline_escapes_are_unescaped(self):
        md = "核验原因：unexpected\\_market\\_date\n"
        html = md_to_html(md)
        self.assertIn("核验原因：unexpected_market_date", html)

    def test_breadth_table_columns_are_colored(self):
        md = (
            "| 来源 | 数据日期 | 有效样本 | 上涨 | 下跌 | 平盘 | 上涨率 | 下跌率 |\n"
            "|---|---|---:|---:|---:|---:|---:|---:|\n"
            "| eastmoney | 2026-08-12 | 5333 | 3000 | 2000 | 333 | +56.25% | -37.50% |\n"
        )
        html = md_to_html(md)
        self.assertIn("<th>上涨</th>", html)
        self.assertIn("num up", html)
        self.assertIn("num down", html)
        self.assertIn("num flat", html)

    def test_status_details_wrapped_and_colored(self):
        md = (
            "## 核验状态\n\n"
            "- 标普500：已双源核验\n"
            "- 纳斯达克综合：待核验（仅单源）\n"
            "- A股涨跌家数：待核验（双源冲突）\n"
        )
        html = md_to_html(md)
        self.assertIn('<details class="status">', html)
        self.assertIn("<summary>核验状态（3 条，点击展开）</summary>", html)
        self.assertIn('<span class="status-verified">已双源核验</span>', html)
        self.assertIn('<span class="status-single">待核验（仅单源）</span>', html)
        self.assertIn('<span class="status-conflict">待核验（双源冲突）</span>', html)

    def test_shell_links_shared_css_and_css_has_alert_rule(self):
        self.assertIn('href="../../report.css?v=', HTML_SHELL)
        self.assertIn(".alert", REPORT_CSS)
        self.assertIn(".up", REPORT_CSS)


if __name__ == "__main__":
    unittest.main()
