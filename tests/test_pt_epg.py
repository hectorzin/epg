import importlib.util
import tempfile
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pt-epg.py"
SPEC = importlib.util.spec_from_file_location("pt_epg", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def write_guide(path, channels, programmes):
    root = ET.Element("tv")
    for channel_id, name in channels:
        channel = ET.SubElement(root, "channel", id=channel_id)
        ET.SubElement(channel, "display-name").text = name
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


class PortugueseEpgTests(unittest.TestCase):
    def test_dazn_channels_stay_distinct(self):
        self.assertNotEqual(module.identity_key("DAZN 1"), module.identity_key("DAZN 2"))

    def test_regional_rtp_feeds_stay_distinct(self):
        self.assertNotEqual(
            module.identity_key("RTP Açores HD"),
            module.identity_key("RTP Madeira HD"),
        )

    def test_placeholder_penalised_and_programmes_omitted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            meo = root / "meo.xml"
            nos = root / "nos.xml"
            output = root / "out.xml"
            write_guide(
                meo,
                [("DAZN1.pt@HD", "DAZN 1")],
                [("DAZN1.pt@HD", "Live football"), ("DAZN1.pt@HD", "Sem Emissão")],
            )
            write_guide(
                nos,
                [("DAZN1.pt@SD", "DAZN 1")],
                [("DAZN1.pt@SD", "Sem Emissão")],
            )
            channels, programmes, _, _ = module.write_merged(
                [("meo", meo, None), ("nostv", nos, None)],
                output,
                set(),
            )
            merged = ET.parse(output).getroot()
            titles = [p.findtext("title") for p in merged.findall("programme")]
            self.assertEqual({node.get("id") for node in merged.findall("channel")}, {"DAZN1.pt@HD"})
            self.assertEqual(programmes, 1)
            self.assertEqual(titles, ["Live football"])
            self.assertEqual(channels, 1)

    def test_brazilian_feeds_are_rejected(self):
        self.assertFalse(module.accepts_channel("Globo.br@SD", "meo"))
        self.assertTrue(module.accepts_channel("SIC.pt@HD", "meo"))

    def test_mint_id_uses_pt_domain(self):
        channel_id = module.mint_id("SIC Notícias HD")
        self.assertIn(".pt@", channel_id)
        self.assertTrue(channel_id.endswith("@SD") or channel_id.endswith("@HD"))


if __name__ == "__main__":
    unittest.main()