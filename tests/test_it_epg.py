import importlib.util
import tempfile
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "it-epg.py"
SPEC = importlib.util.spec_from_file_location("it_epg", SCRIPT)
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
        ET.SubElement(programme, "desc").text = "detail"
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


class ItalyEpgTests(unittest.TestCase):
    def test_la7_distinct_from_la7d(self):
        self.assertNotEqual(module.identity_key("LA 7 HD"), module.identity_key("LA 7D"))

    def test_sky_cinema_plus1_distinct_from_plus24(self):
        self.assertNotEqual(
            module.identity_key("Sky Cinema Due +1 HD"),
            module.identity_key("Sky Cinema Due +24"),
        )

    def test_mediaset_wins_over_sky_for_canale5(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sky = root / "sky.xml"
            mediaset = root / "mediaset.xml"
            output = root / "out.xml"
            write_guide(
                sky,
                [("Canale5.it@SD", "Canale 5")],
                [("Canale5.it@SD", "Sky filler", "20261117010000 +0000")],
            )
            write_guide(
                mediaset,
                [("Canale5.it@SD", "Canale 5")],
                [
                    ("Canale5.it@SD", "Mediaset prime", "20261117010000 +0000"),
                    ("Canale5.it@SD", "Mediaset only", "20261117030000 +0000"),
                ],
            )
            channels, programmes, choices, _ = module.write_merged(
                [("sky", sky, None), ("mediaset", mediaset, None)],
                output,
                set(),
            )
            merged = ET.parse(output).getroot()
            titles = sorted(p.findtext("title") for p in merged.findall("programme"))
            self.assertEqual(channels, 1)
            self.assertEqual(titles, ["Mediaset only", "Sky filler"])
            picked = next(iter(choices.values()))
            self.assertEqual(picked["identity_source"], "sky")

    def test_collision_rewrites_to_italy_feed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            occupied = {"FoxNewsChannel.us@SD"}
            sky = root / "sky.xml"
            output = root / "out.xml"
            write_guide(
                sky,
                [("FoxNewsChannel.us@SD", "Fox News")],
                [("FoxNewsChannel.us@SD", "News", "20261117010000 +0000")],
            )
            module.write_merged([("sky", sky, None)], output, occupied)
            merged = ET.parse(output).getroot()
            self.assertEqual({c.get("id") for c in merged.findall("channel")}, {"FoxNewsChannel.us@Italy"})


if __name__ == "__main__":
    unittest.main()