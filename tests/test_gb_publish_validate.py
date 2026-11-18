import importlib.util
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gb = load("gb_epg", ROOT / "scripts" / "gb-epg.py")
validate = load("gb_publish_validate", ROOT / "scripts" / "gb_publish_validate.py")
process_epg = load("process_epg", ROOT / "scripts" / "process-epg.py")


def write_guide(path: Path, channels: list[tuple[str, str]], programmes: list[tuple[str, str]]):
    root = ET.Element("tv")
    for channel_id, name in channels:
        node = ET.SubElement(root, "channel", id=channel_id)
        ET.SubElement(node, "display-name").text = name
    for channel_id, title in programmes:
        programme = ET.SubElement(
            root,
            "programme",
            channel=channel_id,
            start="20261117010000 +0000",
            stop="20261117020000 +0000",
        )
        ET.SubElement(programme, "title").text = title
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


class BritishPublishValidateTests(unittest.TestCase):
    def test_identity_loss_ignores_id_renames_and_clones(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = root / "previous.xml"
            generated = root / "generated.xml"
            write_guide(
                previous,
                [
                    ("MTV.uk@HD", "MTV HD"),
                    ("mtv.uk", "MTV HD"),
                ],
                [("MTV.uk@HD", "Hits"), ("mtv.uk", "Hits")],
            )
            write_guide(
                generated,
                [("MTV.uk@SD", "MTV HD")],
                [("MTV.uk@SD", "Hits")],
            )
            report = validate.identity_coverage_report(
                previous, generated, identity_key=gb.identity_key, max_loss_ratio=0.20
            )
            self.assertEqual(report["old_identities"], 1)
            self.assertEqual(report["new_identities"], 1)
            self.assertFalse(report["exceeds_threshold"])
            self.assertEqual(report["lost_identities_count"], 0)
            self.assertEqual(len(report["renamed_programmed_ids"]), 2)

    def test_clone_validation_uses_resolved_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guide = root / "guide.xml"
            aliases = root / "aliases.json"
            xtream = root / "xtream.json"
            write_guide(
                guide,
                [("MTV.uk@SD", "MTV HD")],
                [("MTV.uk@SD", "Hits"), ("mtv.uk", "Hits")],
            )
            aliases.write_text("{}", encoding="utf-8")
            xtream.write_text(json.dumps({"mtv.uk": "MTV.uk@HD"}), encoding="utf-8")
            report = validate.validate_xtream_layer(guide, aliases, xtream, process_epg=process_epg)
            self.assertEqual(report["resolved_clone_map"]["mtv.uk"], "MTV.uk@SD")
            self.assertEqual(report["orphan_clones"], [])
            self.assertEqual(report["invalid_clones"], [])
            self.assertEqual(report["missing_xtream_clone_ids"], ["mtv.uk"])

    def test_absent_configured_aliases_and_clones_are_reportable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guide = root / "guide.xml"
            aliases = root / "aliases.json"
            xtream = root / "xtream.json"
            write_guide(guide, [("source.id", "Source")], [("source.id", "Program")])
            aliases.write_text(json.dumps({"absent.display": ["Alias"]}), encoding="utf-8")
            xtream.write_text(json.dumps({"absent.clone": "absent.original"}), encoding="utf-8")

            report = validate.validate_xtream_layer(guide, aliases, xtream, process_epg=process_epg)

            self.assertEqual(report["missing_display_alias_keys"], ["absent.display"])
            self.assertEqual(report["missing_xtream_clone_ids"], ["absent.clone"])
            self.assertEqual(report["skipped_configured_clones"], ["absent.clone"])


if __name__ == "__main__":
    unittest.main()
