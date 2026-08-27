import dataclasses
import unittest

from morning_brief.models import Observation
from morning_brief.verification import rank_sector_extremes, verify_observations


def obs(source, value, change, *, date="2026-07-17", unit="points", contract=None):
    return Observation(
        source=source,
        instrument="S&P 500",
        value=value,
        previous_value=value / (1 + change / 100),
        change_pct=change,
        market_date=date,
        unit=unit,
        url="https://example.com/%s" % source,
        as_of="2026-07-18T07:45:00+08:00",
        contract=contract,
    )


class VerificationTests(unittest.TestCase):
    def test_matching_independent_sources_are_verified_and_primary_wins(self):
        result = verify_observations(
            [obs("tencent", 6350.20, 0.41), obs("stooq", 6350.25, 0.42)],
            value_tolerance=0.002,
            change_tolerance=0.10,
        )
        self.assertEqual(result.status, "verified")
        self.assertEqual(result.consensus_value, 6350.20)
        self.assertEqual(result.consensus_change_pct, 0.41)

    def test_different_market_dates_cannot_form_consensus(self):
        result = verify_observations([
            obs("tencent", 6350.20, 0.41, date="2026-07-17"),
            obs("stooq", 6350.20, 0.41, date="2026-07-16"),
        ])
        self.assertEqual(result.status, "conflict")
        self.assertIsNone(result.consensus_value)
        self.assertIn("market_date", result.reason)

    def test_same_provider_twice_is_only_single_source(self):
        result = verify_observations([
            obs("yingmi", 6350.20, 0.41),
            obs("yingmi", 6350.20, 0.41),
        ])
        self.assertEqual(result.status, "single_source")
        self.assertIsNone(result.consensus_value)

    def test_value_or_change_outside_tolerance_is_conflict(self):
        result = verify_observations([
            obs("tencent", 6350.20, 0.41),
            obs("stooq", 6300.00, 0.70),
        ])
        self.assertEqual(result.status, "conflict")
        self.assertIsNone(result.consensus_value)
        self.assertGreater(result.relative_difference, 0.002)

    def test_previous_value_mismatch_cannot_form_consensus(self):
        left = obs("a", 100.0, 1.0)
        right = dataclasses.replace(
            obs("b", 100.0, 1.0),
            previous_value=95.0,
            change_pct=1.0,
        )

        result = verify_observations([left, right])

        self.assertEqual(result.status, "conflict")
        self.assertEqual(result.reason, "previous_value_mismatch")

    def test_third_source_is_not_silently_ignored(self):
        first = obs("a", 100.0, 1.0)
        second = obs("b", 100.1, 1.02)
        dissent = obs("c", 110.0, 10.0)
        result = verify_observations([first, second, dissent])
        self.assertEqual(result.status, "conflict")
        self.assertEqual(result.reason, "outside_tolerance")
        self.assertEqual(len(result.observations), 3)

        unanimous = verify_observations([
            first, second, obs("c", 99.95, 0.98)
        ])
        self.assertEqual(unanimous.status, "verified")
        self.assertEqual(len(unanimous.observations), 3)

    def test_missing_sources_are_explicit(self):
        single = verify_observations([obs("tencent", 6350.20, 0.41)])
        missing = verify_observations([])
        self.assertEqual(single.status, "single_source")
        self.assertEqual(missing.status, "unavailable")
        self.assertIsNone(single.consensus_value)
        self.assertIsNone(missing.consensus_value)

    def test_contract_and_unit_must_match(self):
        result = verify_observations([
            obs("a", 100, 1, unit="USD/oz", contract="GCQ26"),
            obs("b", 100, 1, unit="CNY/g", contract="AU2608"),
        ])
        self.assertEqual(result.status, "conflict")
        self.assertIn("unit", result.reason)

    def test_matching_but_stale_sources_cannot_verify(self):
        stale = verify_observations(
            [
                obs("a", 100, 1, date="2026-07-01"),
                obs("b", 100, 1, date="2026-07-01"),
            ],
            max_age_days=4,
        )
        self.assertEqual(stale.status, "conflict")
        self.assertEqual(stale.reason, "stale_market_date")

    def test_expected_market_date_is_enforced_when_requested(self):
        result = verify_observations(
            [
                obs("a", 100, 1, date="2026-07-16"),
                obs("b", 100, 1, date="2026-07-16"),
            ],
            expected_market_date="2026-07-17",
        )
        self.assertEqual(result.status, "conflict")
        self.assertEqual(result.reason, "unexpected_market_date")

    def test_mixed_expected_and_live_dates_are_classified_as_unexpected(self):
        # 数据日期（07-24）晚于采集日（07-18）本身即 future 数据错误，
        # 保持 conflict（future_market_date）语义；与 2026-08-27 美元指数修复
        # 的场景（as_of 当日、观测为历史日）不同。
        result = verify_observations(
            [
                obs("history", 100, 1, date="2026-07-24"),
                obs("live", 101, 2, date="2026-07-27"),
            ],
            expected_market_date="2026-07-24",
        )

        self.assertEqual(result.status, "conflict")
        self.assertEqual(result.reason, "future_market_date")

    def test_collection_age_is_measured_in_shanghai_and_requires_timezone(self):
        dated = dataclasses.replace(
            obs("a", 100, 1, date="2026-07-27"),
            as_of="2026-07-26T23:30:00-10:00",
        )

        normalized = verify_observations([dated], max_age_days=0)
        naive = verify_observations(
            [dataclasses.replace(dated, as_of="2026-07-27T08:00:00")],
            max_age_days=0,
        )

        self.assertEqual(normalized.status, "single_source")
        self.assertEqual(naive.reason, "invalid_collection_timestamp")

    def test_non_finite_numbers_cannot_verify(self):
        for invalid in (float("nan"), float("inf"), float("-inf")):
            result = verify_observations([
                dataclasses.replace(obs("bad", 100, 1), value=invalid),
                obs("good", 100, 1),
            ])

            self.assertEqual(result.status, "conflict")
            self.assertEqual(result.reason, "invalid_numeric_value")


class SectorRankingTests(unittest.TestCase):
    def test_ranks_only_verified_sectors(self):
        rows = {}
        changes = [
            ("科技", 2.1), ("能源", 1.4), ("金融", 0.8), ("工业", 0.1),
            ("公用事业", -0.3), ("材料", -0.9), ("房地产", -1.8),
        ]
        for name, change in changes:
            left = obs("tencent-" + name, 100 + change, change)
            right = obs("stooq-" + name, 100 + change, change)
            rows[name] = verify_observations([left, right])
        rows["未核验"] = verify_observations([obs("only", 100, 9.9)])

        ranked = rank_sector_extremes(rows, limit=3)

        self.assertEqual([x[0] for x in ranked["top"]], ["科技", "能源", "金融"])
        self.assertEqual([x[0] for x in ranked["bottom"]], ["房地产", "材料", "公用事业"])

    def test_single_source_sectors_are_ranked_separately(self):
        rows = {
            "科技": verify_observations([obs("tencent-tech", 102.1, 2.1)]),
            "能源": verify_observations([obs("tencent-energy", 101.4, 1.4)]),
            "材料": verify_observations([obs("tencent-materials", 99.1, -0.9)]),
            "房地产": verify_observations([obs("tencent-real-estate", 98.2, -1.8)]),
        }

        ranked = rank_sector_extremes(rows, limit=3)

        self.assertEqual(
            [x[0] for x in ranked["single_source_top"]],
            ["科技", "能源", "材料"],
        )
        self.assertEqual(
            [x[0] for x in ranked["single_source_bottom"]],
            ["房地产", "材料", "能源"],
        )


if __name__ == "__main__":
    unittest.main()
