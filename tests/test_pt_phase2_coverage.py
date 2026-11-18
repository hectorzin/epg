import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PtPhase2CoverageRegression(unittest.TestCase):
    def test_phase2_catalog_mapping_meets_target(self):
        guide = ROOT / "temp" / "guide-pt.final.xml"
        if not guide.is_file():
            self.skipTest("temp guide not built")
        phase2 = json.loads((ROOT / "temp" / "pt-trial" / "coverage-phase2.json").read_text(encoding="utf-8"))
        pending = set(phase2["pending_linear"])
        import importlib.util
        import sys

        sys.path.insert(0, str(ROOT / "scripts"))
        from pt_catalog_match import build_mappings_from_trials, load_catalog_json

        spec = importlib.util.spec_from_file_location("pt_epg", ROOT / "scripts" / "pt-epg.py")
        pt = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pt)
        rows = load_catalog_json(ROOT / "temp" / "pt-xtream-catalog.json")
        covered_phase2 = [
            row["name"] for row in rows if row["name"] not in pending and "VIP" not in row["name"]
        ]
        _, _, mapped = build_mappings_from_trials(
            rows, guide, ROOT / "temp" / "pt-trial", pt.identity_key
        )
        mapped_names = {rows[index]["name"] for index in mapped}
        self.assertGreaterEqual(len(mapped_names), 164)
        still_missing = sorted(set(covered_phase2) - mapped_names)
        self.assertEqual(
            still_missing,
            ["PT Afro Music", "PT Eleven Sport 4 HD", "PT Eleven Sports 4 4K"],
        )


if __name__ == "__main__":
    unittest.main()