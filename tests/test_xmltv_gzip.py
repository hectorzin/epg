"""Global guide gzip: level 9, mtime 0, and byte-identical decompression."""
from __future__ import annotations

import gzip
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from xmltv_gzip import (  # noqa: E402
    compress_xmltv,
    is_global_guide,
    pack_verified,
    parse_xmltv,
    published_global_guide,
    read_xmltv_bytes,
    validate_global_xml,
)

SCRIPT = ROOT / "scripts" / "xmltv_gzip.py"
PUBLISH = ROOT / "scripts" / "ci" / "publish-global-guide.sh"


def sample_xml() -> bytes:
    root = ET.Element("tv")
    channel = ET.SubElement(root, "channel", id="La1.es")
    ET.SubElement(channel, "display-name").text = "La 1"
    programme = ET.SubElement(
        root,
        "programme",
        channel="La1.es",
        start="20261120010000 +0100",
        stop="20261120020000 +0100",
    )
    ET.SubElement(programme, "title").text = "Telediario"
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


class XmltvGzipTests(unittest.TestCase):
    def test_header_is_level_9_without_mtime_or_filename(self):
        payload = compress_xmltv(sample_xml())
        self.assertEqual(payload[:4], b"\x1f\x8b\x08\x00")
        self.assertEqual(payload[4:8], b"\x00\x00\x00\x00")
        self.assertEqual(payload[8], 2)
        self.assertEqual(compress_xmltv(sample_xml()), payload)

    def test_round_trip_matches_validated_xml(self):
        xml_bytes = sample_xml()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            xml_path = root / "guide.temp.xml"
            gzip_path = root / "guide.xml.gz"
            xml_path.write_bytes(xml_bytes)
            xml_size, gzip_size = pack_verified(xml_path, gzip_path)
            self.assertEqual(xml_size, len(xml_bytes))
            self.assertLess(gzip_size, xml_size)
            self.assertEqual(gzip.decompress(gzip_path.read_bytes()), xml_bytes)
            self.assertEqual(xml_path.read_bytes(), xml_bytes)

    def test_previous_gzip_and_plain_xml_decode_to_the_same_document(self):
        xml_bytes = sample_xml()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plain = root / "guide.xml"
            compressed = root / "guide.xml.gz"
            plain.write_bytes(xml_bytes)
            compressed.write_bytes(gzip.compress(xml_bytes, compresslevel=9, mtime=123))
            self.assertEqual(read_xmltv_bytes(compressed), xml_bytes)
            self.assertEqual(read_xmltv_bytes(plain), xml_bytes)
            self.assertEqual(parse_xmltv(compressed).find("channel").get("id"), "La1.es")
            self.assertEqual(parse_xmltv(plain).find("programme").get("channel"), "La1.es")
            self.assertEqual(published_global_guide(root), compressed)
            self.assertTrue(is_global_guide(compressed))
            self.assertTrue(is_global_guide(plain))

    def test_validate_rejects_a_guide_without_programmes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "guide.temp.xml"
            path.write_text("<tv><channel id='a'/></tv>", encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_global_xml(path)
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "validate", str(path)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 1)
            self.assertIn("Global guide has no programmes", completed.stderr)

    def test_cli_pack_prints_sizes_and_keeps_the_xml(self):
        xml_bytes = sample_xml()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            xml_path = root / "guide.temp.xml"
            gzip_path = root / "guide.xml.gz"
            xml_path.write_bytes(xml_bytes)
            channels, programmes = validate_global_xml(xml_path)
            self.assertEqual((channels, programmes), (1, 1))
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "pack", str(xml_path), str(gzip_path)],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("guide.xml.gz", completed.stdout)
            self.assertEqual(gzip.decompress(gzip_path.read_bytes()), xml_bytes)

    def test_publish_script_packs_gzip_and_drops_plain_global_guide(self):
        text = PUBLISH.read_text(encoding="utf-8")
        self.assertIn('PUBLISHED="$ROOT/guide.xml.gz"', text)
        self.assertIn("xmltv_gzip.py validate", text)
        self.assertIn("xmltv_gzip.py pack", text)
        self.assertIn("git rm -f -- guide.xml", text)
        self.assertNotIn('git add -f -- "$OUTPUT"', text)
        self.assertNotIn("--output \"$OUTPUT\"", text)
        self.assertIn("mktemp", text)


if __name__ == "__main__":
    unittest.main()
