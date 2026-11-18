import importlib.util
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import xml.etree.ElementTree as ET

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'merge-national-guides.py'
SPEC = importlib.util.spec_from_file_location('merge_national_guides', SCRIPT)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

TEST_REFERENCE = datetime(2026, 11, 17, 15, 0, tzinfo=ZoneInfo('Europe/Madrid'))


def guide(channel, title, *, start='20261117010000 +0000', stop='20261117020000 +0000'):
    root = ET.Element('tv')
    c = ET.SubElement(root, 'channel', id=channel)
    ET.SubElement(c, 'display-name').text = channel
    p = ET.SubElement(root, 'programme', channel=channel, start=start, stop=stop)
    ET.SubElement(p, 'title').text = title
    return root


class NationalGuideMergeTests(unittest.TestCase):
    def test_discover_national_guides_ignores_global_and_empty_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            es = root / 'guide-es.xml'
            fr = root / 'guide-fr.xml'
            argentina = root / 'guide-ar.xml'
            arabic = root / 'guide-arabic.xml'
            global_guide = root / 'guide.xml'
            noise = root / 'guide-espa.xml'
            ET.ElementTree(guide('ES.1', 'Spain')).write(es)
            ET.ElementTree(guide('FR.1', 'France')).write(fr)
            ET.ElementTree(guide('AR.1', 'Argentina')).write(argentina)
            ET.ElementTree(guide('Arabic.1', 'Arabic')).write(arabic)
            global_guide.write_text('<tv></tv>', encoding='utf8')
            noise.write_text('<tv></tv>', encoding='utf8')
            (root / 'guide-de.xml').write_text('', encoding='utf8')
            gb = root / 'guide-gb.xml'
            ET.ElementTree(guide('GB.1', 'Britain')).write(gb)
            discovered = module.discover_national_guides(root)
            self.assertEqual(
                [p.name for p in discovered],
                ['guide-ar.xml', 'guide-arabic.xml', 'guide-es.xml', 'guide-fr.xml', 'guide-gb.xml'],
            )

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
                    '--reference-date',
                    '2026-11-17',
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            merged = ET.parse(out).getroot()
            self.assertEqual(len(merged.findall('programme')), 1)
            self.assertEqual(len(merged.findall('channel')), 1)

    def test_duplicate_channels_programmes_and_missing_country(self):
        with tempfile.TemporaryDirectory() as d:
            one, two = Path(d) / 'es.xml', Path(d) / 'fr.xml'
            ET.ElementTree(guide('shared.id', 'Same')).write(one)
            ET.ElementTree(guide('shared.id', 'Same')).write(two)
            merged = module.merge([one, two], reference=TEST_REFERENCE)
            self.assertEqual(len(merged.findall('channel')), 1)
            self.assertEqual(len(merged.findall('programme')), 1)
            self.assertEqual(len(module.merge([one], reference=TEST_REFERENCE).findall('programme')), 1)

    def test_invalid_xml_and_invalid_references_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / 'bad.xml'
            bad.write_text('<tv><programme channel="missing"/></tv>', encoding='utf8')
            with self.assertRaises((ValueError, ET.ParseError)):
                module.merge([bad], reference=TEST_REFERENCE)

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
                        '--reference-date',
                        '2026-11-17',
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
            arabic = root / 'guide-arabic.xml'
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
            ET.ElementTree(guide('Arabic.1', 'Arabic')).write(arabic)
            discovered = module.discover_national_guides(root, validate=True)
            self.assertEqual(
                [p.name for p in discovered],
                ['guide-arabic.xml', 'guide-es.xml', 'guide-fr.xml'],
            )
            merged = module.merge(discovered, reference=TEST_REFERENCE)
            self.assertEqual(len(merged.findall('channel')), 3)
            self.assertEqual(len(merged.findall('programme')), 3)

    def test_duplicate_channels_keep_display_aliases_from_later_national_guides(self):
        with tempfile.TemporaryDirectory() as d:
            first = Path(d) / 'guide-arabic.xml'
            second = Path(d) / 'guide-fr.xml'
            first_root = ET.Element('tv')
            first_channel = ET.SubElement(first_root, 'channel', id='shared.id')
            ET.SubElement(first_channel, 'display-name').text = 'Canonical'
            first_programme = ET.SubElement(
                first_root,
                'programme',
                channel='shared.id',
                start='20261117010000 +0000',
                stop='20261117020000 +0000',
            )
            ET.SubElement(first_programme, 'title').text = 'Arabic schedule'
            second_root = ET.Element('tv')
            second_channel = ET.SubElement(second_root, 'channel', id='shared.id')
            ET.SubElement(second_channel, 'display-name').text = 'Canonical'
            ET.SubElement(second_channel, 'icon', src='https://example.com/logo.png')
            ET.SubElement(second_channel, 'display-name').text = 'Xtream alias'
            second_programme = ET.SubElement(
                second_root,
                'programme',
                channel='shared.id',
                start='20261117020000 +0000',
                stop='20261117030000 +0000',
            )
            ET.SubElement(second_programme, 'title').text = 'French schedule'
            ET.ElementTree(first_root).write(first)
            ET.ElementTree(second_root).write(second)

            merged = module.merge([first, second], reference=TEST_REFERENCE)
            channel = merged.find("channel[@id='shared.id']")
            self.assertEqual(
                [node.text for node in channel.findall('display-name')],
                ['Canonical', 'Xtream alias'],
            )
            from xmltv_channel import channel_children_ordered

            self.assertTrue(channel_children_ordered(channel))
            self.assertEqual(len(merged.findall('channel')), 1)
            self.assertEqual(len(merged.findall('programme')), 2)


class MadridProgrammeWindowTests(unittest.TestCase):
    def test_window_is_today_and_tomorrow_in_madrid(self):
        start, end = module.madrid_two_day_window(TEST_REFERENCE)
        self.assertEqual(start.isoformat(), '2026-11-17T00:00:00+01:00')
        self.assertEqual(end.isoformat(), '2026-11-19T00:00:00+01:00')

    def test_overlap_keeps_programmes_spanning_boundaries(self):
        self.assertTrue(
            module.programme_overlaps_window(
                '20261116223000 +0000',
                '20261117013000 +0000',
                *module.madrid_two_day_window(TEST_REFERENCE),
            )
        )
        self.assertTrue(
            module.programme_overlaps_window(
                '20261118220000 +0000',
                '20261119013000 +0000',
                *module.madrid_two_day_window(TEST_REFERENCE),
            )
        )

    def test_merge_drops_outside_window_but_keeps_channels(self):
        with tempfile.TemporaryDirectory() as d:
            root = ET.Element('tv')
            channel = ET.SubElement(root, 'channel', id='ch')
            ET.SubElement(channel, 'display-name').text = 'Channel'
            for start, stop, title in (
                ('20261110010000 +0000', '20261110020000 +0000', 'Too early'),
                ('20261117010000 +0000', '20261117020000 +0000', 'Inside'),
                ('20261119010000 +0000', '20261119020000 +0000', 'Too late'),
            ):
                programme = ET.SubElement(root, 'programme', channel='ch', start=start, stop=stop)
                ET.SubElement(programme, 'title').text = title
            path = Path(d) / 'guide-es.xml'
            ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)
            merged = module.merge([path], reference=TEST_REFERENCE)
            titles = [node.text for node in merged.findall('programme/title')]
            self.assertEqual(titles, ['Inside'])
            self.assertEqual(len(merged.findall('channel')), 1)

    def test_parse_xmltv_datetime_respects_offsets(self):
        parsed = module.parse_xmltv_datetime('20261117010000 +0000')
        madrid = parsed.astimezone(ZoneInfo('Europe/Madrid'))
        self.assertEqual(madrid.isoformat(), '2026-11-17T02:00:00+01:00')


class TomorrowMetadataTrimTests(unittest.TestCase):
    def _write_guide(self, path: Path, programmes):
        root = ET.Element('tv')
        channel = ET.SubElement(root, 'channel', id='ch')
        ET.SubElement(channel, 'display-name').text = 'Channel'
        for start, stop, title, extra in programmes:
            programme = ET.SubElement(root, 'programme', channel='ch', start=start, stop=stop)
            ET.SubElement(programme, 'title').text = title
            if extra:
                ET.SubElement(programme, 'desc').text = extra
                ET.SubElement(programme, 'category').text = 'News'
                ET.SubElement(programme, 'episode-num', system='xmltv_ns').text = '0.1.0/1'
        ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)

    def test_tomorrow_start_drops_secondary_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'guide-es.xml'
            # 2026-11-18 02:00 Madrid = 20261118010000 +0000
            self._write_guide(
                path,
                [
                    (
                        '20261118010000 +0000',
                        '20261118020000 +0000',
                        'Tomorrow',
                        'Long description',
                    ),
                ],
            )
            merged = module.merge([path], reference=TEST_REFERENCE)
            programme = merged.find('programme')
            child_tags = {child.tag for child in programme}
            self.assertEqual(child_tags, {'title', 'category'})
            self.assertEqual(programme.find('title').text, 'Tomorrow')
            self.assertEqual(module.LAST_RUN['programmes_trimmed_tomorrow'], 1)

    def test_today_start_keeps_secondary_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'guide-es.xml'
            self._write_guide(
                path,
                [
                    (
                        '20261117010000 +0000',
                        '20261117020000 +0000',
                        'Today',
                        'Keep me',
                    ),
                ],
            )
            merged = module.merge([path], reference=TEST_REFERENCE)
            programme = merged.find('programme')
            self.assertIsNotNone(programme.find('desc'))
            self.assertIsNotNone(programme.find('episode-num'))
            self.assertEqual(module.LAST_RUN['programmes_trimmed_tomorrow'], 0)

    def test_cross_midnight_starting_today_keeps_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'guide-es.xml'
            # Starts 2026-11-17 23:30 Madrid, ends next Madrid morning
            self._write_guide(
                path,
                [
                    (
                        '20261117223000 +0000',
                        '20261118083000 +0000',
                        'Late show',
                        'Spans midnight',
                    ),
                ],
            )
            merged = module.merge([path], reference=TEST_REFERENCE)
            programme = merged.find('programme')
            self.assertIsNotNone(programme.find('desc'))
            self.assertEqual(module.LAST_RUN['programmes_trimmed_tomorrow'], 0)

    def test_trim_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'guide-es.xml'
            self._write_guide(
                path,
                [
                    (
                        '20261118010000 +0000',
                        '20261118020000 +0000',
                        'Tomorrow',
                        'Still here',
                    ),
                ],
            )
            merged = module.merge([path], reference=TEST_REFERENCE, trim_tomorrow_metadata=False)
            programme = merged.find('programme')
            self.assertIsNotNone(programme.find('desc'))
            self.assertEqual(module.LAST_RUN['programmes_trimmed_tomorrow'], 0)


if __name__ == '__main__':
    unittest.main()
