import unittest

from morning_brief.calendar import TradingCalendar, parse_exchange_closures


NOTICE = '''关于2026年部分节假日休市安排的通知
元旦：1月1日（星期四）至1月3日（星期六）休市，1月5日起开市。
春节：2月15日（星期日）至2月23日（星期一）休市。
清明节：4月4日（星期六）至4月6日（星期一）休市。
劳动节：5月1日（星期五）至5月5日（星期二）休市。
端午节：6月19日（星期五）至6月21日（星期日）休市。
中秋节：9月25日（星期五）至9月27日（星期日）休市。
国庆节：10月1日（星期四）至10月7日（星期三）休市。'''


class FakeClient:
    def __init__(self, second=NOTICE):
        self.second = second

    def get_text(self, url, **kwargs):
        if "sse" in url:
            return NOTICE
        if self.second is None:
            raise RuntimeError("down")
        return self.second


class CalendarParserTests(unittest.TestCase):
    def test_expands_exchange_closure_ranges(self):
        dates = parse_exchange_closures(NOTICE, year=2026)
        self.assertIn("2026-05-01", dates)
        self.assertIn("2026-05-05", dates)
        self.assertNotIn("2026-05-06", dates)

    def test_rejects_wrong_year_or_incomplete_annual_notice(self):
        with self.assertRaisesRegex(ValueError, "year"):
            parse_exchange_closures(NOTICE, year=2027)
        with self.assertRaisesRegex(ValueError, "ranges"):
            parse_exchange_closures("2026年 1月1日至1月3日休市", year=2026)


class TradingCalendarTests(unittest.TestCase):
    def config(self):
        return {
            "2026": {
                "sse": "https://www.sse.com.cn/2026",
                "szse": "https://www.szse.cn/2026",
            }
        }

    def test_two_official_exchanges_confirm_trading_and_previous_date(self):
        result = TradingCalendar(FakeClient(), self.config()).check("2026-07-20")
        self.assertEqual(result["status"], "confirmed")
        self.assertTrue(result["is_trading_day"])
        self.assertEqual(result["previous_trading_day"], "2026-07-17")

    def test_holiday_and_weekend_are_confirmed_closed(self):
        holiday = TradingCalendar(FakeClient(), self.config()).check("2026-05-04")
        weekend = TradingCalendar(FakeClient(), self.config()).check("2026-07-18")
        self.assertFalse(holiday["is_trading_day"])
        self.assertFalse(weekend["is_trading_day"])

    def test_one_source_failure_fails_closed(self):
        result = TradingCalendar(FakeClient(second=None), self.config()).check("2026-07-20")
        self.assertEqual(result["status"], "unconfirmed")
        self.assertIsNone(result["is_trading_day"])

    def test_source_disagreement_is_conflict(self):
        altered = NOTICE.replace("7月20日", "7月20日") + "\n临时：7月20日至7月20日休市。"
        result = TradingCalendar(FakeClient(second=altered), self.config()).check("2026-07-20")
        self.assertEqual(result["status"], "conflict")
        self.assertIsNone(result["is_trading_day"])


if __name__ == "__main__":
    unittest.main()
