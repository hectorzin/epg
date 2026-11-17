#!/usr/bin/env python3
"""Select uncovered Arabic channels and combine their XMLTV guides."""
import argparse
import copy
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path


def normalise(value: str | None) -> str:
    value = unicodedata.normalize('NFKC', value or '').casefold()
    value = re.sub(r'\s+(?:hd|sd|fhd|uhd)$', '', value)
    return re.sub(r'[^\w]', '', value, flags=re.UNICODE)


def channel_identity(channel: ET.Element) -> str:
    xmltv_id = (channel.get('xmltv_id') or '').strip()
    if xmltv_id:
        return f'id:{xmltv_id.casefold()}'
    name = ''.join(channel.itertext())
    return f'name:{normalise(name)}'


def read_guide(path: Path) -> ET.Element:
    root = ET.parse(path).getroot()
    if root.tag != 'tv':
        raise ValueError(f'{path}: expected <tv> root')
    channels = {c.get('id'): c for c in root.findall('channel')}
    if None in channels or len(channels) != len(root.findall('channel')):
        raise ValueError(f'{path}: missing or duplicate channel IDs')
    for programme in root.findall('programme'):
        if not programme.get('start') or not programme.get('stop'):
            raise ValueError(f'{path}: programme is missing start or stop')
        if programme.get('channel') not in channels:
            raise ValueError(f'{path}: programme references an unknown channel')
    return root


def programmed_channel_names(guide_paths: list[Path]) -> tuple[set[str], set[str]]:
    ids: set[str] = set()
    names: set[str] = set()
    for path in guide_paths:
        if not path.exists() or not path.stat().st_size:
            continue
        root = read_guide(path)
        programmed = {
            p.get('channel')
            for p in root.findall('programme')
            if (p.findtext('title') or '').strip()
        }
        for channel in root.findall('channel'):
            channel_id = channel.get('id') or ''
            if channel_id in programmed:
                ids.add(channel_id.casefold())
                for display_name in channel.findall('display-name'):
                    names.add(normalise(display_name.text))
    return ids, names


def select_channels(catalog: Path, output: Path, covered_guides: list[Path]) -> int:
    root = ET.parse(catalog).getroot()
    covered_ids, covered_names = programmed_channel_names(covered_guides)
    selected = ET.Element('channels')
    identities: set[str] = set()
    for channel in root.findall('channel'):
        if (channel.get('lang') or '').casefold() != 'ar':
            continue
        identity = channel_identity(channel)
        xmltv_id = (channel.get('xmltv_id') or '').strip().casefold()
        name_key = normalise(''.join(channel.itertext()))
        if identity in identities:
            continue
        if (xmltv_id and xmltv_id in covered_ids) or (
            not xmltv_id and name_key and name_key in covered_names
        ):
            continue
        identities.add(identity)
        row = ET.SubElement(selected, 'channel', channel.attrib)
        row.text = channel.text
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(selected, space='    ')
    ET.ElementTree(selected).write(output, encoding='utf-8', xml_declaration=True)
    return len(identities)


def _slug(value: str) -> str:
    return normalise(value) or 'unknown'


def merge_guides(pairs: list[tuple[Path, Path]]) -> ET.Element:
    channels: dict[str, ET.Element] = {}
    programmes: dict[tuple, ET.Element] = {}
    for catalog_path, guide_path in pairs:
        if not guide_path.exists() or not guide_path.stat().st_size:
            continue
        source_channels = ET.parse(catalog_path).getroot().findall('channel')
        by_source_id: dict[str, ET.Element] = {}
        for channel in source_channels:
            for key in (channel.get('xmltv_id'), channel.get('site_id')):
                if key:
                    by_source_id[key] = channel
        root = read_guide(guide_path)
        id_map: dict[str, str] = {}
        for channel in root.findall('channel'):
            old_id = channel.get('id') or ''
            source = by_source_id.get(old_id)
            display_name = channel.findtext('display-name') or old_id
            canonical_id = (
                (source.get('xmltv_id') or '').strip()
                if source is not None and (source.get('xmltv_id') or '').strip()
                else f'arabic.{_slug(display_name)}'
            )
            id_map[old_id] = canonical_id
            if canonical_id not in channels:
                canonical = copy.deepcopy(channel)
                canonical.set('id', canonical_id)
                channels[canonical_id] = canonical
        for programme in root.findall('programme'):
            old_channel = programme.get('channel') or ''
            canonical_id = id_map.get(old_channel)
            if not canonical_id or not (programme.findtext('title') or '').strip():
                continue
            canonical = copy.deepcopy(programme)
            canonical.set('channel', canonical_id)
            key = (
                canonical_id,
                canonical.get('start'),
                canonical.get('stop'),
                tuple((node.tag, node.text or '') for node in canonical),
            )
            programmes.setdefault(key, canonical)
    if not programmes:
        raise ValueError('no Arabic programmes were generated')
    result = ET.Element('tv')
    for channel in channels.values():
        result.append(channel)
    for programme in programmes.values():
        result.append(programme)
    return result


def write_merged(pairs: list[tuple[Path, Path]], output: Path) -> tuple[int, int]:
    merged = merge_guides(pairs)
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(merged, space='  ')
    ET.ElementTree(merged).write(output, encoding='utf-8', xml_declaration=True)
    checked = read_guide(output)
    return len(checked.findall('channel')), len(checked.findall('programme'))


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command', required=True)
    select = subparsers.add_parser('select')
    select.add_argument('--catalog', type=Path, required=True)
    select.add_argument('--output', type=Path, required=True)
    select.add_argument('--covered-guide', action='append', type=Path, default=[])
    merge = subparsers.add_parser('merge')
    merge.add_argument('--pair', action='append', required=True, metavar='CATALOG=GUIDE')
    merge.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'select':
        count = select_channels(args.catalog, args.output, args.covered_guide)
        print(count)
        return 0
    pairs = []
    for value in args.pair:
        catalog, sep, guide = value.partition('=')
        if not sep:
            raise ValueError(f'invalid --pair value: {value}')
        pairs.append((Path(catalog), Path(guide)))
    channels, programmes = write_merged(pairs, args.output)
    print(f'Arabic guide: {channels} channels, {programmes} programmes')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ET.ParseError, ValueError) as exc:
        print(f'Arabic EPG failed: {exc}', file=sys.stderr)
        raise SystemExit(1)
