#!/usr/bin/env python3
from __future__ import annotations

import copy
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from xmltv_channel import (  # noqa: E402
    channel_children_ordered,
    channel_metadata_fingerprint,
    deep_copy_normalized,
    normalize_channel_children,
    normalize_channels_in_tree,
    tree_channel_metadata,
)

DTD_PATH = ROOT / "tests" / "__data__" / "xmltv.dtd"


class XmltvChannelOrderTests(unittest.TestCase):
    def test_reorders_display_names_before_icon_and_url(self):
        channel = ET.Element("channel", id="example.es")
        ET.SubElement(channel, "display-name").text = "Primary"
        icon = ET.SubElement(channel, "icon", src="https://example.com/logo.png")
        ET.SubElement(channel, "url").text = "https://example.com"
        ET.SubElement(channel, "display-name").text = "Alias A"
        ET.SubElement(channel, "display-name").text = "Alias B"

        self.assertTrue(normalize_channel_children(channel))
        tags = [node.tag for node in channel]
        self.assertEqual(
            tags,
            ["display-name", "display-name", "display-name", "icon", "url"],
        )
        names = [node.text for node in channel.findall("display-name")]
        self.assertEqual(names, ["Primary", "Alias A", "Alias B"])
        self.assertIs(channel.find("icon"), icon)

    def test_preserves_first_display_name(self):
        channel = ET.Element("channel", id="x")
        ET.SubElement(channel, "display-name").text = "IPTVnator primary"
        ET.SubElement(channel, "icon", src="https://logo")
        ET.SubElement(channel, "display-name").text = "Secondary"

        normalize_channel_children(channel)
        self.assertEqual(channel.find("display-name").text, "IPTVnator primary")

    def test_trailing_elements_stay_after_url(self):
        channel = ET.Element("channel", id="x")
        ET.SubElement(channel, "display-name").text = "Name"
        ET.SubElement(channel, "icon", src="https://logo")
        ET.SubElement(channel, "url").text = "https://site"
        lcn = ET.SubElement(channel, "lcn")
        lcn.text = "42"
        ET.SubElement(channel, "display-name").text = "Late alias"

        normalize_channel_children(channel)
        self.assertEqual([node.tag for node in channel], ["display-name", "display-name", "icon", "url", "lcn"])
        self.assertEqual(channel.find("lcn").text, "42")

    def test_metadata_fingerprint_unchanged_after_reorder(self):
        channel = ET.Element("channel", id="demo")
        ET.SubElement(channel, "display-name").text = "A"
        ET.SubElement(channel, "icon", src="u")
        ET.SubElement(channel, "display-name").text = "B"
        before = channel_metadata_fingerprint(channel)
        normalize_channel_children(channel)
        self.assertEqual(before, channel_metadata_fingerprint(channel))

    def test_merge_scenario_icon_between_aliases(self):
        root = ET.Element("tv")
        channel = ET.SubElement(root, "channel", id="shared")
        ET.SubElement(channel, "display-name").text = "Canonical"
        ET.SubElement(channel, "icon", src="https://i")
        ET.SubElement(channel, "display-name").text = "Extra"

        normalize_channels_in_tree(root)
        self.assertTrue(channel_children_ordered(channel))
        self.assertEqual([n.text for n in channel.findall("display-name")], ["Canonical", "Extra"])


def guide_display_name_map(root: ET.Element) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for channel in root.findall("channel"):
        channel_id = channel.get("id")
        if not channel_id:
            continue
        out[channel_id] = [node.text or "" for node in channel.findall("display-name")]
    return out


class GuideRegressionTests(unittest.TestCase):
    def _guides(self) -> list[Path]:
        return sorted((ROOT / "guides").glob("guide*.xml"))

    @unittest.skipUnless(any((ROOT / "guides").glob("guide-es.xml")), "local guide-es.xml missing")
    def test_local_guides_keep_channel_metadata_when_reordered(self):
        for path in self._guides():
            with self.subTest(guide=path.name):
                root = ET.parse(path).getroot()
                before = tree_channel_metadata(root)
                clone = deep_copy_normalized(root)
                self.assertEqual(before, tree_channel_metadata(clone))
                for channel in clone.findall("channel"):
                    self.assertTrue(channel_children_ordered(channel))

    @unittest.skipUnless(any((ROOT / "guides").glob("guide-es.xml")), "local guide-es.xml missing")
    def test_xtream_name_indexes_unchanged_after_reorder(self):
        from xtream_matching import build_guide_indexes

        for path in (
            ROOT / "guides" / "guide-es.xml",
            ROOT / "guides" / "guide-nl.xml",
            ROOT / "guides" / "guide-pt.xml",
        ):
            if not path.is_file():
                continue
            with self.subTest(guide=path.name):
                root = ET.parse(path).getroot()
                before = guide_display_name_map(root)
                channel_ids = set(before)
                before_indexes = build_guide_indexes(channel_ids, before)
                clone = deep_copy_normalized(root)
                after = guide_display_name_map(clone)
                after_indexes = build_guide_indexes(channel_ids, after)
                self.assertEqual(before, after)
                self.assertEqual(before_indexes, after_indexes)

    @unittest.skipUnless(DTD_PATH.is_file(), "xmltv.dtd fixture missing")
    def test_sample_against_official_dtd(self):
        from lxml import etree

        channel = ET.Element("channel", id="dtd.sample")
        ET.SubElement(channel, "display-name").text = "One"
        ET.SubElement(channel, "display-name").text = "Two"
        ET.SubElement(channel, "icon", src="https://example/logo.png")
        ET.SubElement(channel, "url").text = "https://example.com"
        normalize_channel_children(channel)
        dtd_href = DTD_PATH.resolve().as_posix()
        sample_root = ET.Element("tv")
        sample_root.append(channel)
        body = ET.tostring(sample_root, encoding="unicode")
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<!DOCTYPE tv SYSTEM "{dtd_href}">\n'
            f"{body}"
        )
        parser = etree.XMLParser(dtd_validation=True, load_dtd=True)
        doc = etree.fromstring(xml.encode("utf-8"), parser=parser)
        self.assertEqual(len(doc.findall("channel")), 1)


if __name__ == "__main__":
    unittest.main()