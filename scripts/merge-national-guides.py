#!/usr/bin/env python3
"""Merge all valid national XMLTV guides into one global guide."""
import argparse
import copy
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

NATIONAL_GUIDE_PATTERN = re.compile(r'^(?:guide-[a-z]{2}|guide-arabic)\.xml$', re.IGNORECASE)


def discover_national_guides(root: Path, *, validate: bool = False) -> list[Path]:
    """Return guide-XX.xml paths in deterministic sorted order.

    When validate=True, every matching file must be non-empty and pass read_guide()
    (invalid nationals abort the merge instead of being skipped).
    """
    if not root.is_dir():
        return []
    guides = sorted(
        p for p in root.glob('guide-*.xml') if NATIONAL_GUIDE_PATTERN.match(p.name)
    )
    if not validate:
        return [p for p in guides if p.stat().st_size > 0]
    validated: list[Path] = []
    for path in guides:
        if path.stat().st_size == 0:
            raise ValueError(f'{path.name}: empty national guide refused for merge')
        read_guide(path)
        validated.append(path)
    return validated


def read_guide(path):
    root = ET.parse(path).getroot()
    if root.tag != 'tv':
        raise ValueError(f'{path}: expected <tv> root')
    channel_ids = [c.get('id') for c in root.findall('channel')]
    if any(not c for c in channel_ids) or len(channel_ids) != len(set(channel_ids)):
        raise ValueError(f'{path}: missing or duplicate channel IDs')
    ids = set(channel_ids)
    for p in root.findall('programme'):
        if not p.get('start') or not p.get('stop') or p.get('channel') not in ids:
            raise ValueError(f'{path}: invalid programme or channel reference')
    return root


def merge(paths):
    channels = {}
    programs = {}
    for path in paths:
        root = read_guide(path)
        for c in root.findall('channel'):
            channels.setdefault(c.get('id'), copy.deepcopy(c))
        for p in root.findall('programme'):
            key = (p.get('channel'), p.get('start'), p.get('stop'), tuple((x.tag, x.text or '') for x in p))
            programs.setdefault(key, copy.deepcopy(p))
    if not programs:
        raise ValueError('all national guides are empty')
    result = ET.Element('tv')
    for c in channels.values():
        result.append(c)
    for p in programs.values():
        result.append(p)
    return result


def resolve_guide_paths(root: Path | None, guides: list[Path]) -> list[Path]:
    if guides:
        return guides
    search_root = root if root is not None else Path('.')
    discovered = discover_national_guides(search_root, validate=True)
    if not discovered:
        raise ValueError(f'no national guides matching guide-XX.xml in {search_root}')
    return discovered


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--root',
        type=Path,
        default=None,
        help='Directory to scan for guide-XX.xml when no guide paths are given',
    )
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('guides', nargs='*', type=Path)
    args = parser.parse_args()
    paths = resolve_guide_paths(args.root, args.guides)
    merged = merge(paths)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(merged, space='  ')
    ET.ElementTree(merged).write(args.output, encoding='utf-8', xml_declaration=True)
    names = [p.name for p in paths]
    print(
        f'Merged {", ".join(names)}: {len(merged.findall("channel"))} channels, '
        f'{len(merged.findall("programme"))} programmes'
    )


if __name__ == '__main__':
    try:
        main()
    except (OSError, ET.ParseError, ValueError) as exc:
        print(f'Global guide merge failed: {exc}', file=sys.stderr)
        raise SystemExit(1)
