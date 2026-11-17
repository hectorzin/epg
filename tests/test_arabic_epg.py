import importlib.util
import tempfile
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'arabic-epg.py'
SPEC = importlib.util.spec_from_file_location('arabic_epg', SCRIPT)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def write_channels(path, channels):
    root = ET.Element('channels')
    for attrs, name in channels:
        node = ET.SubElement(root, 'channel', attrs)
        node.text = name
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)


def write_guide(path, channels, programmes):
    root = ET.Element('tv')
    for channel_id, name in channels:
        channel = ET.SubElement(root, 'channel', id=channel_id)
        ET.SubElement(channel, 'display-name').text = name
    for channel_id, title in programmes:
        programme = ET.SubElement(
            root,
            'programme',
            channel=channel_id,
            start='20261117010000 +0000',
            stop='20261117020000 +0000',
        )
        ET.SubElement(programme, 'title').text = title
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)


class ArabicEpgTests(unittest.TestCase):
    def test_select_keeps_uncovered_arabic_and_distinct_regional_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / 'channels.xml'
            prior = root / 'prior.xml'
            selected = root / 'selected.xml'
            write_channels(
                catalog,
                [
                    ({'lang': 'ar', 'site_id': '1', 'xmltv_id': 'News.ae'}, 'الأخبار'),
                    ({'lang': 'ar', 'site_id': '2', 'xmltv_id': 'News.sa'}, 'الأخبار'),
                    ({'lang': 'en', 'site_id': '3', 'xmltv_id': 'News.en'}, 'News'),
                    ({'lang': 'ar', 'site_id': '4', 'xmltv_id': 'News.ae'}, 'الأخبار'),
                ],
            )
            write_guide(prior, [('News.ae', 'الأخبار')], [('News.ae', 'النشرة')])
            count = module.select_channels(catalog, selected, [prior])
            result = ET.parse(selected).getroot().findall('channel')
            self.assertEqual(count, 1)
            self.assertEqual([row.get('xmltv_id') for row in result], ['News.sa'])

    def test_merge_deduplicates_canonical_channel_and_program_but_keeps_regions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_catalog = root / 'shahid.channels.xml'
            second_catalog = root / 'bein.channels.xml'
            first_guide = root / 'shahid.xml'
            second_guide = root / 'bein.xml'
            output = root / 'guide-arabic.xml'
            write_channels(
                first_catalog,
                [
                    ({'lang': 'ar', 'site_id': 'shahid-1', 'xmltv_id': 'News.ae'}, 'الأخبار'),
                    ({'lang': 'ar', 'site_id': 'shahid-2', 'xmltv_id': 'News.sa'}, 'الأخبار'),
                ],
            )
            write_channels(
                second_catalog,
                [({'lang': 'ar', 'site_id': 'bein-1', 'xmltv_id': 'News.ae'}, 'الأخبار')],
            )
            write_guide(
                first_guide,
                [('News.ae', 'الأخبار'), ('News.sa', 'الأخبار')],
                [('News.ae', 'النشرة'), ('News.sa', 'النشرة')],
            )
            write_guide(second_guide, [('News.ae', 'الأخبار')], [('News.ae', 'النشرة')])
            channels, programmes = module.write_merged(
                [(first_catalog, first_guide), (second_catalog, second_guide)], output
            )
            merged = ET.parse(output).getroot()
            self.assertEqual((channels, programmes), (2, 2))
            self.assertEqual(
                {node.get('id') for node in merged.findall('channel')},
                {'News.ae', 'News.sa'},
            )
            self.assertTrue(all(node.findtext('title') == 'النشرة' for node in merged.findall('programme')))


if __name__ == '__main__':
    unittest.main()
