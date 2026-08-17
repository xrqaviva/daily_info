import unittest

from morning_brief.news import build_verified_news, is_official_url


AS_OF = "2026-07-20T07:50:00+08:00"
SINCE = "2026-07-17T08:00:00+08:00"


def candidate(title, url, publisher, published_at, **extra):
    return {
        "title": title,
        "url": url,
        "publisher": publisher,
        "published_at": published_at,
        "summary": extra.pop("summary", "摘要"),
        **extra,
    }


class NewsVerificationTests(unittest.TestCase):
    def test_malformed_or_timezone_free_publish_time_is_rejected(self):
        rows = build_verified_news([
            candidate(
                "错误时间一", "https://www.pbc.gov.cn/bad-one", "央行",
                "2026-07-19 10:00:00garbage",
            ),
            candidate(
                "错误时间二", "https://www.pbc.gov.cn/bad-two", "央行",
                "2026-07-19T10:00:00",
            ),
        ], since=SINCE, as_of=AS_OF)

        self.assertEqual(rows, [])

    def test_domestic_futures_summary_rejects_duplicate_commodity_movement(self):
        duplicate = candidate(
            "国内期货收盘",
            "https://www.pbc.gov.cn/futures",
            "官方",
            "2026-07-19T10:00:00+08:00",
            summary="国内期货涨跌不一，钯跌超5%，钯跌超4%，沪银跌近4%。",
        )
        valid = candidate(
            "国内期货收盘（复核）",
            "https://www.pbc.gov.cn/futures-valid",
            "官方",
            "2026-07-19T11:00:00+08:00",
            summary="国内期货涨跌不一，钯跌超5%，铂跌超4%，沪银跌近4%。",
        )

        rows = build_verified_news(
            [duplicate, valid], since=SINCE, as_of=AS_OF
        )

        self.assertEqual([row["title"] for row in rows], ["国内期货收盘（复核）"])

    def test_official_allowlist_is_domain_based_not_publisher_label(self):
        self.assertTrue(is_official_url("https://www.pbc.gov.cn/goutongjiaoliu/113456/1.html"))
        self.assertTrue(is_official_url("https://www.federalreserve.gov/newsevents/x.htm"))
        self.assertFalse(is_official_url("https://news.example.com/pbc-copy"))

        rows = build_verified_news([
            candidate("央行发布政策", "https://www.pbc.gov.cn/a", "中国人民银行", "2026-07-19T10:00:00+08:00"),
            candidate("媒体自称官方", "https://news.example.com/a", "央行官方", "2026-07-19T11:00:00+08:00"),
        ], since=SINCE, as_of=AS_OF)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["verification_status"], "official_single_source")

    def test_media_requires_two_distinct_domains_for_same_event(self):
        rows = build_verified_news([
            candidate("美联储维持利率不变", "https://a.example.com/1", "媒体甲", "2026-07-19T10:00:00+08:00"),
            candidate("美联储宣布维持利率不变", "https://b.example.net/2", "媒体乙", "2026-07-19T10:03:00+08:00"),
            candidate("孤立传闻", "https://c.example.org/3", "媒体丙", "2026-07-19T10:04:00+08:00"),
        ], since=SINCE, as_of=AS_OF)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["verification_status"], "media_two_source")
        self.assertEqual(len(rows[0]["sources"]), 2)

    def test_required_market_category_is_preserved_and_prioritized(self):
        rows = build_verified_news([
            candidate(
                "央行美联储利率通胀政策",
                "https://www.pbc.gov.cn/macro", "央行",
                "2026-07-19T11:00:00+08:00",
                category="中国宏观与政策",
            ),
            candidate(
                "美股收盘科技股走弱",
                "https://media-one.example.com/market", "媒体甲",
                "2026-07-19T10:00:00+08:00",
                category="隔夜美股与财报",
            ),
            candidate(
                "美股收盘科技股走弱",
                "https://media-two.example.net/market", "媒体乙",
                "2026-07-19T10:02:00+08:00",
                category="隔夜美股与财报",
            ),
        ], since=SINCE, as_of=AS_OF)

        self.assertEqual(rows[0]["category"], "隔夜美股与财报")
        self.assertEqual(rows[1]["category"], "中国宏观与政策")

    def test_same_domain_does_not_count_twice(self):
        rows = build_verified_news([
            candidate("美国公布通胀数据", "https://www.media.com/a", "媒体甲", "2026-07-19T10:00:00+08:00"),
            candidate("美国通胀数据公布", "https://finance.media.com/b", "媒体甲财经", "2026-07-19T10:02:00+08:00"),
        ], since=SINCE, as_of=AS_OF)
        self.assertEqual(rows, [])

    def test_shared_event_key_cannot_pair_semantically_unrelated_headlines(self):
        rows = build_verified_news([
            candidate(
                "纳指收低芯片股领跌",
                "https://media-one.example.com/us-close", "媒体甲",
                "2026-07-19T10:00:00+08:00",
                category="隔夜美股与财报",
                event_key="2026-07-18-us-market-close-semiconductors",
            ),
            candidate(
                "科技板块拖累华尔街主要指数",
                "https://media-two.example.net/wall-street", "媒体乙",
                "2026-07-19T10:03:00+08:00",
                category="隔夜美股与财报",
                event_key="2026-07-18-us-market-close-semiconductors",
            ),
        ], since=SINCE, as_of=AS_OF)

        self.assertEqual(rows, [])

    def test_shared_event_key_cannot_bypass_headline_number_disagreement(self):
        rows = build_verified_news([
            candidate(
                "芯片股跌7%闪迪跌11%英伟达跌5%油价跌8%",
                "https://media-one.example.com/detail", "媒体甲",
                "2026-07-19T10:00:00+08:00",
                event_key="us-market-close-2026-07-18",
            ),
            candidate(
                "科技股轮动油价单日跌8%",
                "https://media-two.example.net/summary", "媒体乙",
                "2026-07-19T10:03:00+08:00",
                event_key="us-market-close-2026-07-18",
            ),
        ], since=SINCE, as_of=AS_OF)

        self.assertEqual(rows, [])

    def test_shared_event_key_still_pairs_independently_matching_headlines(self):
        rows = build_verified_news([
            candidate(
                "美股收盘科技股走弱",
                "https://media-one.example.com/detail", "媒体甲",
                "2026-07-19T10:00:00+08:00",
                category="隔夜美股与财报",
                event_key="us-market-close-2026-07-18",
            ),
            candidate(
                "美股收盘科技板块走弱",
                "https://media-two.example.net/summary", "媒体乙",
                "2026-07-19T10:03:00+08:00",
                category="隔夜美股与财报",
                event_key="us-market-close-2026-07-18",
            ),
        ], since=SINCE, as_of=AS_OF)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["verification_status"], "media_two_source")

    def test_roll_window_excludes_old_and_future_and_caps_twenty(self):
        items = [
            candidate("旧事件", "https://www.pbc.gov.cn/old", "央行", "2026-07-17T07:59:00+08:00"),
            candidate("未来事件", "https://www.pbc.gov.cn/future", "央行", "2026-07-20T08:01:00+08:00"),
        ]
        items.extend(
            candidate(
                "政策事件%02d" % index,
                "https://www.pbc.gov.cn/%s" % index,
                "央行",
                "2026-07-19T%02d:00:00+08:00" % (index % 20),
                importance=index,
            )
            for index in range(25)
        )
        rows = build_verified_news(items, since=SINCE, as_of=AS_OF, max_items=20)
        self.assertEqual(len(rows), 20)
        self.assertNotIn("旧事件", {row["title"] for row in rows})
        self.assertNotIn("未来事件", {row["title"] for row in rows})
        self.assertEqual(rows[0]["title"], "政策事件24")


if __name__ == "__main__":
    unittest.main()
