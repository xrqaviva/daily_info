import unittest

from morning_brief.breadth import calculate_breadth, verify_breadth


class BreadthTests(unittest.TestCase):
    def test_excludes_st_delisting_and_suspended_but_keeps_beijing(self):
        rows = [
            {"code": "600001", "name": "沪市上涨", "change_pct": 1.0, "price": 10, "status": "trading", "market_date": "2026-07-17"},
            {"code": "000001", "name": "深市下跌", "change_pct": -0.5, "price": 9, "status": "trading", "market_date": "2026-07-17"},
            {"code": "920001", "name": "北交平盘", "change_pct": 0.0, "price": 8, "status": "trading", "market_date": "2026-07-17"},
            {"code": "600002", "name": "*ST样本", "change_pct": 5.0, "price": 2, "status": "trading", "market_date": "2026-07-17"},
            {"code": "600003", "name": "XD*ST样本", "change_pct": 5.0, "price": 2, "status": "trading", "market_date": "2026-07-17"},
            {"code": "000002", "name": "退市样本", "change_pct": -10.0, "price": 1, "status": "trading", "market_date": "2026-07-17"},
            {"code": "688001", "name": "停牌样本", "change_pct": None, "price": None, "status": "suspended", "market_date": "2026-07-17"},
        ]

        result = calculate_breadth(rows)

        self.assertEqual(result.sample_size, 3)
        self.assertEqual((result.up, result.down, result.flat), (1, 1, 1))
        self.assertAlmostEqual(result.up_rate, 1 / 3)
        self.assertAlmostEqual(result.down_rate, 1 / 3)
        self.assertEqual(result.market_date, "2026-07-17")
        self.assertEqual(set(result.codes), {"sh:600001", "sz:000001", "bj:920001"})

    def test_zero_is_real_but_missing_is_not_zero(self):
        result = calculate_breadth([
            {"code": "920001", "name": "北交平盘", "change_pct": 0, "price": 8, "status": "trading", "market_date": "2026-07-17"},
            {"code": "600001", "name": "缺失", "change_pct": None, "price": 10, "status": "trading", "market_date": "2026-07-17"},
        ])
        self.assertEqual(result.sample_size, 1)
        self.assertEqual(result.flat, 1)

    def test_non_finite_price_or_change_is_not_counted(self):
        result = calculate_breadth([
            {"code": "600001", "name": "无效涨跌", "change_pct": float("nan"), "price": 10, "status": "trading", "market_date": "2026-07-17"},
            {"code": "000001", "name": "无效价格", "change_pct": 1, "price": float("inf"), "status": "trading", "market_date": "2026-07-17"},
            {"code": "920001", "name": "有效平盘", "change_pct": 0, "price": 8, "status": "trading", "market_date": "2026-07-17"},
        ])

        self.assertEqual(result.sample_size, 1)
        self.assertEqual(result.flat, 1)

    @staticmethod
    def _full_market_rows(up_count=500, *, suffix_offset=0, date="2026-07-17"):
        codes = ["600001", "000001", "920001"] + [
            str(600100 + suffix_offset + i) for i in range(997)
        ]
        return [
            {
                "code": code,
                "name": "股票%s" % code,
                "change_pct": 1 if i < up_count else -1,
                "price": 10,
                "status": "trading",
                "market_date": date,
            }
            for i, code in enumerate(codes)
        ]

    def test_breadth_pair_uses_sample_and_count_tolerances(self):
        a = calculate_breadth(self._full_market_rows(500))
        b = calculate_breadth(self._full_market_rows(497))
        verified = verify_breadth(a, b, expected_market_date="2026-07-17")
        self.assertEqual(verified.status, "verified")

        c = calculate_breadth(self._full_market_rows(450))
        conflict = verify_breadth(a, c, expected_market_date="2026-07-17")
        self.assertEqual(conflict.status, "conflict")
        self.assertIsNone(conflict.consensus_value)

    def test_same_counts_with_different_stock_sets_cannot_verify(self):
        left = calculate_breadth(self._full_market_rows())
        right = calculate_breadth(self._full_market_rows(suffix_offset=2000))
        result = verify_breadth(left, right, expected_market_date="2026-07-17")
        self.assertEqual(result.status, "conflict")
        self.assertEqual(result.reason, "eligible_code_set_mismatch")

    def test_wrong_date_missing_venue_and_duplicates_cannot_verify(self):
        valid = calculate_breadth(self._full_market_rows())
        wrong_date = calculate_breadth(self._full_market_rows(date="2026-07-16"))
        self.assertEqual(
            verify_breadth(valid, wrong_date, expected_market_date="2026-07-17").reason,
            "market_date_mismatch",
        )

        no_beijing = calculate_breadth([
            row for row in self._full_market_rows() if row["code"] != "920001"
        ])
        self.assertEqual(
            verify_breadth(no_beijing, no_beijing, expected_market_date="2026-07-17").reason,
            "incomplete_market_coverage",
        )

        duplicate = calculate_breadth(
            self._full_market_rows() + [self._full_market_rows()[0]]
        )
        verified = verify_breadth(duplicate, duplicate, expected_market_date="2026-07-17")
        self.assertEqual(verified.status, "verified")
        self.assertIn("sh:600001", duplicate.duplicate_codes)

    def test_unexpected_date_takes_priority_over_duplicate_codes(self):
        rows = self._full_market_rows(date="2026-07-18")
        result = calculate_breadth(rows + [rows[0]])

        verification = verify_breadth(
            result, result, expected_market_date="2026-07-17"
        )

        self.assertEqual(verification.reason, "unexpected_market_date")

    def test_zero_price_is_suspended_not_flat(self):
        result = calculate_breadth([
            {"code": "600001", "name": "零价格", "change_pct": 0, "price": 0, "status": "trading", "market_date": "2026-07-17"}
        ])
        self.assertEqual(result.sample_size, 0)

    def test_every_eligible_row_must_prove_its_market_date(self):
        rows = self._full_market_rows()
        rows[20] = dict(rows[20], market_date=None)
        left = calculate_breadth(rows)
        right = calculate_breadth(rows)
        result = verify_breadth(
            left, right, expected_market_date="2026-07-17"
        )
        self.assertEqual(result.status, "conflict")
        self.assertEqual(result.reason, "market_date_missing")


if __name__ == "__main__":
    unittest.main()
