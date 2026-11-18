import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REJECTED = ROOT / "temp" / "it-trial" / "rejected-curated-aliases.json"
ALIASES = ROOT / "epg" / "aliases-it.json"
XTREAM = ROOT / "epg" / "xtream-aliases-it.json"
REFERENCE = ROOT / "temp" / "it-trial" / "curated-coverage-results.json"


class ItalyCoverageTests(unittest.TestCase):
    def test_aliases_exclude_rejected_streams(self):
        aliases = json.loads(ALIASES.read_text(encoding="utf-8"))
        rejected = {row["stream"] for row in json.loads(REJECTED.read_text(encoding="utf-8"))}
        mapped = {name for names in aliases.values() for name in names}
        overlap = sorted(mapped & rejected)
        self.assertEqual(overlap, [], msg=f"rejected streams in aliases: {overlap}")

    def test_xtream_aliases_empty(self):
        data = json.loads(XTREAM.read_text(encoding="utf-8"))
        self.assertEqual(data, {})

    def test_trial_reference_curated_figures(self):
        if not REFERENCE.is_file():
            self.skipTest("trial reference missing")
        report = json.loads(REFERENCE.read_text(encoding="utf-8"))
        self.assertEqual(report["curated_mappings_verified"], 66)
        self.assertEqual(report["curated_with_useful_programming"], 65)
        self.assertEqual(report["iptvnator_auto_hits"], 0)
        self.assertEqual(report["aquaplay_auto_hits"], 0)

    def test_final_guide_when_built(self):
        guide = ROOT / "temp" / "guide-it.final.xml"
        if not guide.is_file():
            self.skipTest("run scripts/ci/build-it-trial-guide.sh first")
        import sys

        sys.path.insert(0, str(ROOT / "scripts"))
        from it_catalog_match import client_coverage_report

        aliases = json.loads(ALIASES.read_text(encoding="utf-8"))
        report = client_coverage_report(guide, aliases=aliases)
        self.assertGreaterEqual(report["curated_mappings_verified"], 66)
        self.assertGreaterEqual(report["curated_with_useful_programming"], 65)
        root = ET.parse(guide).getroot()
        ids = [c.get("id") for c in root.findall("channel")]
        self.assertEqual(len(ids), len(set(ids)))
        for channel in root.findall("channel"):
            names = [n.text for n in channel.findall("display-name") if (n.text or "").strip()]
            self.assertTrue(names, "channel missing display-name")
            first = channel.find("display-name")
            self.assertIs(first, channel.findall("display-name")[0])
        for clone_id in XTREAM.read_text():
            self.assertNotIn('"1"', clone_id)


if __name__ == "__main__":
    unittest.main()