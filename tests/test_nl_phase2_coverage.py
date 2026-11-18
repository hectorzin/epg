import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class NlPhase2CoverageRegression(unittest.TestCase):
    def test_trial_merge_meets_real_client_coverage(self):
        guide = ROOT / "temp" / "guide-nl.final.xml"
        catalog = ROOT / "temp" / "nl-xtream-catalog.json"
        if not guide.is_file():
            self.skipTest("temp guide-nl.final.xml not built")
        if not catalog.is_file():
            self.skipTest("temp nl-xtream catalog missing")
        import sys

        sys.path.insert(0, str(ROOT / "scripts"))
        from nl_catalog_match import real_client_coverage

        aliases_path = ROOT / "epg" / "aliases-nl.json"
        aliases = {}
        if aliases_path.is_file():
            import json

            aliases = json.loads(aliases_path.read_text(encoding="utf-8"))
        report = real_client_coverage(guide, catalog, aliases=aliases)
        self.assertGreaterEqual(report["iptvnator_hits"], 152)
        self.assertGreaterEqual(report["aquaplay_hits"], 152)
        self.assertEqual(report["catalog_real_streams"], 167)
        nh = report.get("nh_nieuws") or []
        self.assertTrue(nh)
        self.assertTrue(all(row.get("ok") for row in nh))


if __name__ == "__main__":
    unittest.main()