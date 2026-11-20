import gzip
import importlib.util
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "grab_epgshare.py"
SPEC = importlib.util.spec_from_file_location("grab_epgshare", SCRIPT)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


RALLY_XML = """<?xml version="1.0" encoding="UTF-8"?>
<tv>
  <channel id="Rally.TV.de">
    <display-name lang="en">Rally TV</display-name>
    <icon src="https://example.test/rally.svg" />
    <url>http://www.rally.tv</url>
  </channel>
  <programme start="20261120090028 +0000" stop="20261120095243 +0000" channel="Rally.TV.de">
    <title lang="en">Season Review - WRC 2026</title>
    <desc lang="en">Catch up with all the highlights.</desc>
  </programme>
  <programme start="20261119090028 +0000" stop="20261119095243 +0000" channel="Rally.TV.de">
    <title lang="en">Yesterday show</title>
  </programme>
  <programme start="20261121090028 +0000" stop="20261121095243 +0000" channel="Rally.TV.de">
    <title lang="en">Tomorrow show</title>
  </programme>
</tv>
"""


class GrabEpgshareTests(unittest.TestCase):
    def test_channels_file_uses_epgshare_contract(self):
        path = ROOT / "epg" / "epgshare-rally.channels.xml"
        selected = mod.parse_channels_file(path)
        self.assertEqual(len(selected), 1)
        channel = selected[0]
        self.assertEqual(channel["tag"], "RALLY_TV1")
        self.assertEqual(channel["source_id"], "Rally.TV.de")
        self.assertEqual(channel["xmltv_id"], "Rally.TV.de")
        self.assertEqual(channel["name"], "Rally TV")

    def test_build_guide_filters_days_and_keeps_metadata(self):
        payload = gzip.compress(RALLY_XML.encode("utf-8"))

        def fake_download(tag):
            self.assertEqual(tag, "RALLY_TV1")
            return gzip.decompress(payload)

        selected = mod.parse_channels_file(ROOT / "epg" / "epgshare-rally.channels.xml")
        root = mod.build_guide(
            selected,
            days=2,
            today=date(2026, 11, 20),
            download=fake_download,
        )
        self.assertEqual([c.get("id") for c in root.findall("channel")], ["Rally.TV.de"])
        names = [n.text for n in root.find("channel[@id='Rally.TV.de']").findall("display-name")]
        self.assertEqual(names, ["Rally TV"])
        self.assertEqual(
            root.find("channel[@id='Rally.TV.de']/icon").get("src"),
            "https://example.test/rally.svg",
        )
        titles = [p.findtext("title") for p in root.findall("programme")]
        self.assertEqual(titles, ["Season Review - WRC 2026", "Tomorrow show"])

    def test_inject_replaces_existing_channel_without_duplicating(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "guide.xml"
            existing = ET.Element("tv")
            channel = ET.SubElement(existing, "channel", id="Rally.TV.de")
            ET.SubElement(channel, "display-name").text = "Old"
            other = ET.SubElement(existing, "channel", id="keep.me")
            ET.SubElement(other, "display-name").text = "Keep"
            old = ET.SubElement(
                existing,
                "programme",
                channel="Rally.TV.de",
                start="20261120000000 +0000",
                stop="20261120010000 +0000",
            )
            ET.SubElement(old, "title").text = "Old show"
            keep = ET.SubElement(
                existing,
                "programme",
                channel="keep.me",
                start="20261120000000 +0000",
                stop="20261120010000 +0000",
            )
            ET.SubElement(keep, "title").text = "Stay"
            ET.ElementTree(existing).write(target, encoding="utf-8", xml_declaration=True)

            incoming = ET.fromstring(
                "<tv><channel id='Rally.TV.de'><display-name>Rally TV</display-name></channel>"
                "<programme start='20261120090028 +0000' stop='20261120095243 +0000' "
                "channel='Rally.TV.de'><title>Season Review - WRC 2026</title></programme></tv>"
            )
            mod.inject_into(target, incoming)
            out = ET.parse(target).getroot()
            ids = [c.get("id") for c in out.findall("channel")]
            self.assertEqual(ids.count("Rally.TV.de"), 1)
            self.assertIn("keep.me", ids)
            self.assertEqual(out.find("channel[@id='Rally.TV.de']/display-name").text, "Rally TV")
            rally_titles = [
                p.findtext("title") for p in out.findall("programme") if p.get("channel") == "Rally.TV.de"
            ]
            self.assertEqual(rally_titles, ["Season Review - WRC 2026"])
            self.assertEqual(out.find("programme[@channel='keep.me']/title").text, "Stay")


if __name__ == "__main__":
    unittest.main()
