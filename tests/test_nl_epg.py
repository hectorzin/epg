import importlib.util
import tempfile
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "nl-epg.py"
SPEC = importlib.util.spec_from_file_location("nl_epg", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def write_guide(path, channels, programmes):
    root = ET.Element("tv")
    for channel_id, name in channels:
        channel = ET.SubElement(root, "channel", id=channel_id)
        ET.SubElement(channel, "display-name").text = name
    for channel_id, title, start in programmes:
        programme = ET.SubElement(
            root,
            "programme",
            channel=channel_id,
            start=start,
            stop="20261117020000 +0000",
        )
        ET.SubElement(programme, "title").text = title
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


class NetherlandsEpgTests(unittest.TestCase):
    def test_nh_nieuws_distinct_from_npo_politiek(self):
        self.assertNotEqual(module.identity_key("NH Nieuws HD"), module.identity_key("NPO Politiek en Nieuws"))

    def test_espn_numbered_feeds_stay_distinct(self):
        self.assertNotEqual(module.identity_key("ESPN 1 HD"), module.identity_key("ESPN 2 HD"))

    def test_ziggo_wins_identity_over_delta_programme_count(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ziggo = root / "ziggo.xml"
            delta = root / "delta.xml"
            output = root / "out.xml"
            write_guide(
                ziggo,
                [("NPO1.nl@HD", "NPO 1")],
                [("NPO1.nl@HD", "Ziggo show", "20261117010000 +0000")],
            )
            write_guide(
                delta,
                [("NPO1.nl@SD", "NPO 1")],
                [
                    ("NPO1.nl@SD", "Delta filler", "20261117010000 +0000"),
                    ("NPO1.nl@SD", "Delta only", "20261117030000 +0000"),
                ],
            )
            channels, programmes, choices, _ = module.write_merged(
                [("ziggo", ziggo, None), ("delta", delta, None)],
                output,
                set(),
            )
            merged = ET.parse(output).getroot()
            titles = sorted(p.findtext("title") for p in merged.findall("programme"))
            self.assertEqual(channels, 1)
            self.assertEqual(programmes, 2)
            self.assertEqual(titles, ["Delta only", "Ziggo show"])
            picked = next(iter(choices.values()))
            self.assertEqual(picked["identity_source"], "ziggo")

    def test_collision_rewrites_to_netherlands_feed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            occupied = {"CNNInternational.us@MENA"}
            ziggo = root / "ziggo.xml"
            output = root / "out.xml"
            write_guide(
                ziggo,
                [("CNNInternational.us@MENA", "CNN")],
                [("CNNInternational.us@MENA", "News", "20261117010000 +0000")],
            )
            module.write_merged([("ziggo", ziggo, None)], output, occupied)
            merged = ET.parse(output).getroot()
            self.assertEqual({c.get("id") for c in merged.findall("channel")}, {"CNNInternational.us@Netherlands"})


if __name__ == "__main__":
    unittest.main()