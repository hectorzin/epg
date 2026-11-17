import importlib.util
import subprocess
import sys
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
    def test_discover_national_guides_ignores_global_and_empty_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            es = root / 'guide-es.xml'
            fr = root / 'guide-fr.xml'
            global_guide = root / 'guide.xml'
            noise = root / 'guide-espa.xml'
            ET.ElementTree(guide('ES.1', 'Spain')).write(es)
            ET.ElementTree(guide('FR.1', 'France')).write(fr)
            global_guide.write_text('<tv></tv>', encoding='utf8')
            noise.write_text('<tv></tv>', encoding='utf8')
            (root / 'guide-de.xml').write_text('', encoding='utf8')
            discovered = module.discover_national_guides(root)
            self.assertEqual([p.name for p in discovered], ['guide-es.xml', 'guide-fr.xml'])

    def test_cli_discovers_guides_under_root(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            es = root / 'guide-es.xml'
            out = root / 'guide.xml'
            ET.ElementTree(guide('ES.1', 'Spain')).write(es)
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    '--root',
                    str(root),
                    '--output',
                    str(out),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            merged = ET.parse(out).getroot()
            self.assertEqual(len(merged.findall('programme')), 1)

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

    def test_empty_national_file_blocks_automatic_merge(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            ET.ElementTree(guide('ES.1', 'Spain')).write(root / 'guide-es.xml')
            (root / 'guide-fr.xml').write_text('', encoding='utf8')
            with self.assertRaises(ValueError):
                module.discover_national_guides(root, validate=True)
            with self.assertRaises(subprocess.CalledProcessError):
                subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        '--root',
                        str(root),
                        '--output',
                        str(root / 'guide.xml'),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )

    def test_discover_order_and_duplicate_dedup_are_stable(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            es = root / 'guide-es.xml'
            fr = root / 'guide-fr.xml'
            es_root = ET.Element('tv')
            for ch, title in (('shared.id', 'One'), ('ES.only', 'Es')):
                c = ET.SubElement(es_root, 'channel', id=ch)
                ET.SubElement(c, 'display-name').text = ch
                p = ET.SubElement(
                    es_root,
                    'programme',
                    channel=ch,
                    start='20261117010000 +0000',
                    stop='20261117020000 +0000',
                )
                ET.SubElement(p, 'title').text = title
            ET.ElementTree(es_root).write(es)
            ET.ElementTree(guide('shared.id', 'One')).write(fr)
            discovered = module.discover_national_guides(root, validate=True)
            self.assertEqual([p.name for p in discovered], ['guide-es.xml', 'guide-fr.xml'])
            merged = module.merge(discovered)
            self.assertEqual(len(merged.findall('channel')), 2)
            self.assertEqual(len(merged.findall('programme')), 2)


if __name__ == '__main__':
    unittest.main()
