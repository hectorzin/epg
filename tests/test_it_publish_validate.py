import importlib.util
import json
import io
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validate = load("it_publish_validate", ROOT / "scripts" / "it_publish_validate.py")


def write_minimal_guide(path: Path, *, channel_count: int = 85, programme_count: int = 5100) -> None:
    root = ET.Element("tv")
    for index in range(channel_count):
        channel_id = f"TestChannel{index}.it@SD"
        channel = ET.SubElement(root, "channel", id=channel_id)
        ET.SubElement(channel, "display-name").text = f"Test {index}"
        ET.SubElement(channel, "icon", src="https://example.test/icon.png")
    for index in range(programme_count):
        channel_id = f"TestChannel{index % channel_count}.it@SD"
        programme = ET.SubElement(
            root,
            "programme",
            channel=channel_id,
            start="20261118010000 +0000",
            stop="20261118020000 +0000",
        )
        ET.SubElement(programme, "title").text = f"Programme {index}"
    tree = ET.ElementTree(root)
    tree.write(path, encoding="utf-8", xml_declaration=True)


class ItalyPublishValidateTests(unittest.TestCase):
    def test_private_catalog_missing_skips_coverage_with_warning(self):
        aliases = {"TestChannel0.it@SD": ["IT Test 0"]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guide = root / "guide.xml"
            alias_path = root / "aliases.json"
            xtream_path = root / "xtream.json"
            write_minimal_guide(guide)
            alias_path.write_text(json.dumps(aliases), encoding="utf-8")
            xtream_path.write_text("{}", encoding="utf-8")
            missing_catalog = root / "missing-catalog.json"
            stderr = io.StringIO()
            argv = [
                "it_publish_validate.py",
                str(guide),
                "--aliases",
                str(alias_path),
                "--xtream-aliases",
                str(xtream_path),
                "--catalog",
                str(missing_catalog),
            ]
            with patch.object(validate, "private_catalog_available", return_value=False):
                with redirect_stderr(stderr):
                    with patch.object(sys, "argv", argv):
                        code = validate.main()
            self.assertEqual(code, 0)
        msg = stderr.getvalue()
        self.assertIn("Skipping Italy curated client coverage", msg)
        self.assertIn("cannot verify", msg.lower())

    def test_private_catalog_present_runs_curated_coverage(self):
        guide_path = ROOT / "temp" / "guide-it-ci-fix.final.xml"
        if not guide_path.is_file():
            guide_path = ROOT / "temp" / "guide-it.final.xml"
        if not guide_path.is_file():
            self.skipTest("trial guide missing")
        catalog_path = ROOT / "temp" / "it-trial" / "xtream-it-catalog.json"
        if not catalog_path.is_file():
            self.skipTest("xtream-it-catalog.json missing")
        fake_catalog = {
            "catalog_streams": 116,
            "iptvnator_auto_hits": 0,
            "iptvnator_after_aliases": 66,
            "aquaplay_auto_hits": 66,
            "aquaplay_after_aliases": 66,
            "curated_mappings_verified": 66,
            "curated_with_useful_programming": 65,
        }
        argv = [
            "it_publish_validate.py",
            str(guide_path),
            "--aliases",
            str(ROOT / "epg" / "aliases-it.json"),
            "--catalog",
            str(catalog_path),
        ]
        with patch.object(validate, "private_catalog_available", return_value=True):
            with patch.object(validate, "validate_curated_coverage", return_value=fake_catalog) as mocked:
                with patch.object(sys, "argv", argv):
                    code = validate.main()
        self.assertEqual(code, 0)
        mocked.assert_called_once()

    def test_dtd_violation_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guide = root / "bad.xml"
            channel = ET.Element("channel", id="Bad.it@SD")
            ET.SubElement(channel, "icon", src="https://example.test/x.png")
            ET.SubElement(channel, "display-name").text = "Bad"
            tree = ET.Element("tv")
            tree.append(channel)
            programme = ET.SubElement(
                tree,
                "programme",
                channel="Bad.it@SD",
                start="20261118010000 +0000",
                stop="20261118020000 +0000",
            )
            ET.SubElement(programme, "title").text = "X"
            ET.ElementTree(tree).write(guide, encoding="utf-8", xml_declaration=True)
            with self.assertRaises(SystemExit) as ctx:
                validate.validate_channel_layout(ET.parse(guide).getroot())
            self.assertIn("DTD", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()