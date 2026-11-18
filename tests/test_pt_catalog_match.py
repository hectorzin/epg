import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys_path = ROOT / "scripts"
import sys

sys.path.insert(0, str(sys_path))

from pt_catalog_match import (  # noqa: E402
    apply_brand_alias,
    build_mappings_from_trials,
    is_portuguese_market,
    load_catalog_json,
)

PT_EPG = ROOT / "scripts" / "pt-epg.py"
SPEC = importlib.util.spec_from_file_location("pt_epg", PT_EPG)
pt = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pt)


class PtCatalogMatchTests(unittest.TestCase):
    def test_portuguese_market_filter(self):
        self.assertTrue(is_portuguese_market("SIC.pt@HD"))
        self.assertTrue(is_portuguese_market("DAZN1.uk@Portugal"))
        self.assertFalse(is_portuguese_market("Globo.br@SD"))

    def test_brand_alias_rules(self):
        self.assertEqual(apply_brand_alias("FOX HD")[1], "STAR Channel")
        self.assertEqual(apply_brand_alias("Eleven Sports 3")[1], "DAZN 3")
        self.assertEqual(apply_brand_alias("Eleven Sport 6 HD"), (None, None))

    def test_trial_guide_produces_expected_alias_coverage(self):
        catalog = ROOT / "temp" / "pt-xtream-catalog.json"
        guide = ROOT / "temp" / "guide-pt.final.xml"
        trial = ROOT / "temp" / "pt-trial"
        if not catalog.is_file() or not guide.is_file() or not trial.is_dir():
            self.skipTest("Portuguese trial artifacts are not present")
        rows = load_catalog_json(catalog)
        aliases, clones, covered = build_mappings_from_trials(rows, guide, trial, pt.identity_key)
        self.assertGreaterEqual(len(covered), 150)
        self.assertGreaterEqual(len(aliases), 85)
        # every alias key must exist in the processed guide
        merged_ids = {
            node.get("id")
            for node in __import__("xml.etree.ElementTree", fromlist=["parse"]).parse(guide).getroot().findall("channel")
        }
        self.assertTrue(all(channel_id in merged_ids for channel_id in aliases))


if __name__ == "__main__":
    unittest.main()