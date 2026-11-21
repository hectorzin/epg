"""Regression: national publish coverage with policy exemptions."""
from __future__ import annotations

import importlib
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
validate = importlib.import_module("national_publish_validate")


def write_guide(path: Path, channels: list[str], programmed: list[str]) -> None:
    root = ET.Element("tv")
    for cid in channels:
        node = ET.SubElement(root, "channel", id=cid)
        ET.SubElement(node, "display-name").text = cid
    for cid in programmed:
        prog = ET.SubElement(
            root,
            "programme",
            channel=cid,
            start="20261117010000 +0000",
            stop="20261117020000 +0000",
        )
        ET.SubElement(prog, "title").text = "Show"
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


class NationalPublishValidateTests(unittest.TestCase):
    def test_arabic_numeric_clone_loss_is_exempt(self):
        policy = importlib.import_module("es_xtream_policy")
        clones = sorted(policy.intentional_numeric_xtream_clone_ids())[:62]
        self.assertGreaterEqual(len(clones), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = root / "old.xml"
            generated = root / "new.xml"
            real = ["MBC2.ae@SD", "AlJazeera.qa@Arabic"]
            write_guide(previous, clones + real, clones + real)
            write_guide(generated, real, real)
            report = validate.programmed_coverage_report(previous, generated)
            self.assertEqual(len(report["lost_policy_exempt"]), len(clones))
            self.assertEqual(len(report["lost_real"]), 0)
            self.assertFalse(report["exceeds_threshold"])
            self.assertGreater(report["raw_loss_ratio"], 0.20)

    def test_legitimate_numeric_source_id_loss_is_not_exempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = root / "old.xml"
            generated = root / "new.xml"
            write_guide(previous, ["2065", "la1.es"], ["2065", "la1.es"])
            write_guide(generated, ["la1.es"], ["la1.es"])
            report = validate.programmed_coverage_report(previous, generated)
            self.assertEqual(report["lost_real"], ["2065"])
            self.assertTrue(report["exceeds_threshold"])

    def test_real_loss_over_threshold_still_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = root / "old.xml"
            generated = root / "new.xml"
            write_guide(previous, ["a", "b", "c"], ["a", "b", "c"])
            write_guide(generated, ["a"], ["a"])
            report = validate.programmed_coverage_report(previous, generated)
            self.assertTrue(report["exceeds_threshold"])
            with self.assertRaises(SystemExit):
                validate.enforce_programmed_coverage(report, region="Test")

    def test_denied_clone_loss_is_exempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = root / "old.xml"
            generated = root / "new.xml"
            write_guide(previous, ["01tv.fr", "la1.es"], ["01tv.fr", "la1.es"])
            write_guide(generated, ["la1.es"], ["la1.es"])
            report = validate.programmed_coverage_report(previous, generated)
            self.assertIn("01tv.fr", report["lost_policy_exempt"])
            self.assertFalse(report["exceeds_threshold"])

    def test_previous_gzip_is_compared_as_xml(self):
        from xmltv_gzip import compress_xmltv

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plain = root / "old.xml"
            previous = root / "old.xml.gz"
            generated = root / "new.xml"
            write_guide(plain, ["a", "b"], ["a", "b"])
            previous.write_bytes(compress_xmltv(plain.read_bytes()))
            write_guide(generated, ["a"], ["a"])
            report = validate.programmed_coverage_report(previous, generated)
            self.assertEqual(report["old_programmed"], 2)
            self.assertEqual(report["new_programmed"], 1)
            self.assertIn("b", report["lost_real"])


class EsXtreamMappingRegression(unittest.TestCase):
    def test_cima_noel_not_mapped_to_missing_terror(self):
        import json

        xtream = json.loads((ROOT / "epg" / "xtream-aliases.json").read_text(encoding="utf-8"))
        self.assertNotIn("cima.es.theme.noel", xtream)
        aliases = json.loads((ROOT / "epg" / "aliases.json").read_text(encoding="utf-8"))
        self.assertIn("cima.es.theme.noel", aliases)
        self.assertNotIn("MovistarPlus.terror", aliases)

    def test_mplus_series_clones_point_at_mhits(self):
        import json

        xtream = json.loads((ROOT / "epg" / "xtream-aliases.json").read_text(encoding="utf-8"))
        self.assertEqual(xtream["cima.es.mseries"], "mhits")
        self.assertEqual(xtream["movistarseries.es"], "mhits")
        self.assertNotIn("moviestardrama.es", xtream)
        self.assertEqual(xtream["cima.es.moriginales"], "morig")
        aliases = json.loads((ROOT / "epg" / "aliases.json").read_text(encoding="utf-8"))
        self.assertEqual(
            aliases["mhits"],
            ["M+ Series", "M+ Series 2", "M+ SERIES FULL HD", "M+ SERIES 4K"],
        )
        self.assertIn("M+ Originales 2", aliases["morig"])
        for n in range(6, 14):
            self.assertEqual(aliases[f"MovistarPlus.chap{n - 1}"], [f"M+LCAMPEON{n}"])
        self.assertEqual(aliases["Orange.11178"], ["TOP BARÇA HD"])
        self.assertEqual(aliases["Rally.TV.de"], ["DAZN RALLY TV"])
        self.assertNotIn("Orange.11178", xtream)
        self.assertNotIn("Rally.TV.de", xtream)


if __name__ == "__main__":
    unittest.main()