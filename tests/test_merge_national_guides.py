import importlib.util
import tempfile
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'merge-national-guides.py'
SPEC = importlib.util.spec_from_file_location('merge_national_guides', SCRIPT)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def guide(channel, title):
    root = ET.Element('tv')
    c = ET.SubElement(root, 'channel', id=channel)
    ET.SubElement(c, 'display-name').text = channel
    p = ET.SubElement(root, 'programme', channel=channel, start='20261117010000 +0000', stop='20261117020000 +0000')
    ET.SubElement(p, 'title').text = title
    return root


class NationalGuideMergeTests(unittest.TestCase):
    def test_duplicate_channels_programmes_and_missing_country(self):
        with tempfile.TemporaryDirectory() as d:
            one, two = Path(d) / 'es.xml', Path(d) / 'fr.xml'
            ET.ElementTree(guide('shared.id', 'Same')).write(one)
            ET.ElementTree(guide('shared.id', 'Same')).write(two)
            merged = module.merge([one, two])
            self.assertEqual(len(merged.findall('channel')), 1)
            self.assertEqual(len(merged.findall('programme')), 1)
            # Omitting a national guide preserves every remaining country's data.
            self.assertEqual(len(module.merge([one]).findall('programme')), 1)

    def test_invalid_xml_and_invalid_references_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / 'bad.xml'
            bad.write_text('<tv><programme channel="missing"/></tv>', encoding='utf8')
            with self.assertRaises((ValueError, ET.ParseError)):
                module.merge([bad])


if __name__ == '__main__':
    unittest.main()
