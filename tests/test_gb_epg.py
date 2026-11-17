import importlib.util
import tempfile
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gb-epg.py"
SPEC = importlib.util.spec_from_file_location("gb_epg", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def write_channels(path, channels):
    root = ET.Element("channels")
    for attrs, name in channels:
        node = ET.SubElement(root, "channel", attrs)
        node.text = name
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def write_guide(path, channels, programmes, *, extra=None):
    root = ET.Element("tv")
    for channel_id, name in channels:
        channel = ET.SubElement(root, "channel", id=channel_id)
        ET.SubElement(channel, "display-name").text = name
    for item in programmes:
        channel_id, title = item[:2]
        programme = ET.SubElement(
            root,
            "programme",
            channel=channel_id,
            start="20261117010000 +0000",
            stop="20261117020000 +0000",
        )
        ET.SubElement(programme, "title").text = title
        if extra:
            extra(programme)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


class BritishEpgTests(unittest.TestCase):
    def test_select_skips_channels_already_covered_by_prior_guide(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "catalog.xml"
            covered_guide = root / "sky.xml"
            selected = root / "selected.xml"
            write_channels(
                catalog,
                [
                    ({"lang": "en", "site_id": "1", "xmltv_id": "BBCOne.uk@HD"}, "BBC One HD"),
                    ({"lang": "en", "site_id": "2", "xmltv_id": "BBCTwo.uk@HD"}, "BBC Two HD"),
                ],
            )
            write_guide(covered_guide, [("BBCOne.uk@HD", "BBC One HD")], [("BBCOne.uk@HD", "News")])
            count = module.select_channels(
                catalog, selected, covered_guides=[covered_guide]
            )
            ids = [row.get("xmltv_id") for row in ET.parse(selected).getroot().findall("channel")]
            self.assertEqual(count, 1)
            self.assertEqual(ids, ["BBCTwo.uk@HD"])

    def test_select_keeps_gb_sky_and_skips_other_territories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "sky.channels.xml"
            selected = root / "selected.xml"
            write_channels(
                catalog,
                [
                    ({"lang": "en", "site_id": "GB#1", "xmltv_id": "BBCTwo.uk@HD"}, "BBC Two HD"),
                    ({"lang": "en", "site_id": "IT#2", "xmltv_id": "Rai1.it@SD"}, "Rai 1"),
                    ({"lang": "de", "site_id": "GB#3", "xmltv_id": "SkyDE.de@SD"}, "Sky DE"),
                ],
            )
            count = module.select_channels(catalog, selected, lang="en", site_id_prefix="GB#")
            ids = [row.get("xmltv_id") for row in ET.parse(selected).getroot().findall("channel")]
            self.assertEqual(count, 1)
            self.assertEqual(ids, ["BBCTwo.uk@HD"])

    def test_plus1_regional_and_numbered_channels_stay_distinct(self):
        self.assertNotEqual(module.identity_key("Channel 5 HD"), module.identity_key("Channel 5+1"))
        self.assertNotEqual(module.identity_key("BBC One HD"), module.identity_key("BBC One Scotland HD"))
        self.assertNotEqual(module.identity_key("TNT Sports 1"), module.identity_key("TNT Sports 2"))
        self.assertEqual(module.identity_key("Channel 5 HD"), module.identity_key("Channel 5 SD"))
        self.assertNotEqual(module.identity_key("5 USA"), module.identity_key("Channel 5"))

    def test_merge_picks_richer_source_and_rewrites_collisions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sky_guide = root / "sky.xml"
            virgin_guide = root / "virgin.xml"
            occupied = root / "guide-fr.xml"
            output = root / "guide-gb.xml"
            write_guide(sky_guide, [("Channel5.uk@SD", "Channel 5")], [("Channel5.uk@SD", "News")])
            def add_desc(programme):
                ET.SubElement(programme, "desc").text = "Full description"

            write_guide(
                virgin_guide,
                [("Channel5.uk@HD", "Channel 5 HD")],
                [("Channel5.uk@HD", "News")],
                extra=add_desc,
            )
            write_guide(
                occupied,
                [("CNBCEurope.uk@SD", "CNBC")],
                [("CNBCEurope.uk@SD", "US Open")],
            )
            write_guide(
                root / "sky-cnbc.xml",
                [("CNBCEurope.uk@SD", "CNBC HD")],
                [("CNBCEurope.uk@SD", "Closing Bell")],
            )
            channels, programmes, choices, collisions = module.write_merged(
                [
                    ("sky", sky_guide, None),
                    ("virgin", virgin_guide, None),
                    ("sky-cnbc", root / "sky-cnbc.xml", None),
                ],
                output,
                module.collect_occupied([occupied]),
            )
            merged = ET.parse(output).getroot()
            ids = {node.get("id") for node in merged.findall("channel")}
            self.assertIn("Channel5.uk@HD", ids)
            self.assertEqual(choices["Channel5.uk@HD"], "virgin")
            self.assertTrue(any(row["original_id"] == "CNBCEurope.uk@SD" for row in collisions))
            self.assertIn("CNBCEurope.uk@UK", ids)
            self.assertEqual((channels, programmes), (2, 2))

    def test_vanished_and_empty_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guide = root / "tv24.xml"
            output = root / "out.xml"
            write_guide(
                guide,
                [("bbc-one-hd", "BBC One HD"), ("gone", "CBS Justice")],
                [("bbc-one-hd", "EastEnders"), ("gone", "Channel No Longer Available")],
            )
            channels, programmes, _, _ = module.write_merged(
                [("tv24", guide, None)],
                output,
                set(),
            )
            merged = ET.parse(output).getroot()
            ids = {node.get("id") for node in merged.findall("channel")}
            self.assertEqual(channels, 1)
            self.assertEqual(programmes, 1)
            self.assertTrue(all(channel_id and not channel_id.isdigit() for channel_id in ids))
            self.assertNotIn("gone", ids)
            self.assertTrue(all(ID_RE.fullmatch(channel_id) for channel_id in ids))

    def test_xmltv_id_is_ignored_when_display_name_disagrees(self):
        self.assertFalse(module.xmltv_agrees("SkySportsF1.uk@HD", "Sky Sports Darts HD"))
        self.assertTrue(module.xmltv_agrees("Film4.uk@HD", "Film4 HD"))
        self.assertFalse(module.xmltv_agrees("BBCOne.uk@HD", "BBC One Scotland HD"))

    def test_abbreviations_and_channel5_share_identity(self):
        self.assertEqual(module.identity_key("SkySp F'ball HD"), module.identity_key("Sky Sports Football HD"))
        self.assertEqual(module.identity_key("SkySpCricket HD"), module.identity_key("Sky Sports Cricket HD"))
        self.assertEqual(module.identity_key("ComedyCentHD"), module.identity_key("Comedy Central HD"))
        self.assertEqual(module.identity_key("Nick +1"), module.identity_key("Nickelodeon+1"))
        self.assertEqual(module.identity_key("5 HD"), module.identity_key("Channel 5 HD"))
        self.assertNotEqual(module.identity_key("5 USA"), module.identity_key("Channel 5"))
        self.assertEqual(module.identity_key("I.D."), module.identity_key("Investigation Discovery"))
        self.assertTrue(module.is_strong_id("BBCOne.uk@HD"))
        self.assertFalse(module.is_strong_id("UK1#ITV1.HD.uk"))
        self.assertEqual(module.mint_id("BBC One HD"), "BBCOne.uk@HD")


ID_RE = module.ID_RE


if __name__ == "__main__":
    unittest.main()
