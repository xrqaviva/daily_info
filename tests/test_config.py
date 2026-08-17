import json
import tempfile
import unittest
from pathlib import Path

from morning_brief.config import ConfigError, load_source_catalog


class SourceCatalogTests(unittest.TestCase):
    def test_international_instruments_are_locked_to_completed_session(self):
        path = Path(__file__).resolve().parents[1] / "config" / "instruments.json"
        instruments = json.loads(path.read_text(encoding="utf-8"))["instruments"]

        for key in (
            "lme_copper", "lme_aluminum", "lme_zinc", "lme_lead",
            "lme_nickel", "lme_tin", "ftse100", "cac40", "dax",
        ):
            self.assertEqual(
                instruments[key]["expected_session"],
                "international_previous",
            )
        for key in (
            "gold", "silver", "copper", "wti", "spot_gold", "spot_silver",
            "dxy",
        ):
            self.assertEqual(instruments[key]["expected_session"], "us_previous")
        expected_calendars = {
            "ftse100": "uk",
            "cac40": "euronext",
            "dax": "xetra",
            "lme_copper": "lme",
            "lme_aluminum": "lme",
            "lme_zinc": "lme",
            "lme_lead": "lme",
            "lme_nickel": "lme",
            "lme_tin": "lme",
        }
        for key, calendar in expected_calendars.items():
            self.assertEqual(instruments[key]["market_calendar"], calendar)
        for key in (
            "lme_copper", "lme_aluminum", "lme_zinc", "lme_lead",
            "lme_nickel", "lme_tin",
        ):
            self.assertIn("供应商", instruments[key]["contract"])
            self.assertIn("非LME官方", instruments[key]["contract"])
        for sector in instruments["sectors"]:
            self.assertEqual(sector["expected_session"], "us_previous")
            self.assertEqual(sector["contract"], "US sector ETF close")
        for key in ("gold", "silver", "copper", "wti"):
            self.assertNotIn(
                "hf_tencent",
                {row["kind"] for row in instruments[key]["sources"]},
            )

    def test_source_catalog_loads_enabled_supplemental_and_disabled_sources(self):
        catalog = load_source_catalog(
            Path(__file__).resolve().parents[1] / "config" / "source_catalog.json"
        )
        self.assertEqual(catalog["tencent"]["status"], "enabled")
        self.assertEqual(catalog["tradingview"]["date_quality"], "session_only")
        self.assertEqual(catalog["tradingview"]["status"], "supplemental")
        self.assertEqual(catalog["twelve_data"]["status"], "disabled")

    def test_source_catalog_rejects_unknown_fields(self):
        row = {
            "status": "enabled",
            "roles": ["market"],
            "date_quality": "explicit",
            "endpoint_type": "https_get_json",
            "timeout_seconds": 20,
            "max_requests": 1,
            "url": "https://example.com/data",
            "ownership": ["example"],
            "limitations": "fixture",
            "unexpected": True,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps({
                "schema_version": 1,
                "sources": {"example": row},
            }), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_source_catalog(path)


if __name__ == "__main__":
    unittest.main()
