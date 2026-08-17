import unittest

from morning_brief.sources.official_feeds import (
    parse_bls_response,
    parse_official_feed,
    parse_sec_submissions,
)


class OfficialFeedTests(unittest.TestCase):
    def test_parses_rss_with_direct_official_url_and_time(self):
        text = """<rss><channel><item><title>美联储发布政策声明</title><link>https://www.federalreserve.gov/newsevents/pressreleases/a.htm</link><pubDate>Thu, 23 Jul 2026 18:00:00 GMT</pubDate><description>政策摘要</description></item></channel></rss>"""
        rows = parse_official_feed(text, provider_id="fed", category="美国与主要央行")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["provider"], "official:fed")
        self.assertEqual(rows[0]["published_at"], "2026-07-23T18:00:00+00:00")
        self.assertTrue(rows[0]["url"].startswith("https://www.federalreserve.gov/"))

    def test_feed_limit_is_ten(self):
        items = "".join("<item><title>事件%s</title><link>https://www.stats.gov.cn/a%s</link><pubDate>Thu, 23 Jul 2026 0%s:00:00 GMT</pubDate></item>" % (index, index, index % 10) for index in range(15))
        rows = parse_official_feed("<rss><channel>%s</channel></rss>" % items, provider_id="nbs", category="中国宏观与政策")
        self.assertEqual(len(rows), 10)

    def test_bls_on_demand_parser_keeps_series_period_and_value(self):
        payload = {"status": "REQUEST_SUCCEEDED", "Results": {"series": [{
            "seriesID": "CUUR0000SA0",
            "data": [
                {"year": "2026", "period": "M06", "periodName": "June", "value": "319.2"},
                {"year": "2026", "period": "M05", "periodName": "May", "value": "318.4"},
                {"year": "2025", "period": "M13", "periodName": "Annual", "value": "310.0"},
            ],
        }]}}

        rows = parse_bls_response(payload)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["series_id"], "CUUR0000SA0")
        self.assertEqual(rows[0]["period"], "2026-06")
        self.assertEqual(rows[0]["value"], 319.2)

    def test_sec_on_demand_parser_builds_official_archive_urls(self):
        payload = {"filings": {"recent": {
            "accessionNumber": ["0000320193-26-000077", "0000320193-26-000076"],
            "filingDate": ["2026-07-22", "2026-07-21"],
            "reportDate": ["2026-06-27", ""],
            "form": ["10-Q", "4"],
            "primaryDocument": ["aapl-20260627.htm", "xslF345X06/form4.xml"],
        }}}

        rows = parse_sec_submissions(payload, cik="0000320193")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["form"], "10-Q")
        self.assertEqual(rows[0]["filing_date"], "2026-07-22")
        self.assertEqual(
            rows[0]["url"],
            "https://www.sec.gov/Archives/edgar/data/320193/000032019326000077/aapl-20260627.htm",
        )


if __name__ == "__main__":
    unittest.main()
