#!/usr/bin/env python3
"""Merge all valid national XMLTV guides into one global guide."""
import argparse
import copy
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('guides', nargs='+', type=Path)
    args = parser.parse_args()
    root = merge(args.guides)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root, space='  ')
    ET.ElementTree(root).write(args.output, encoding='utf-8', xml_declaration=True)
    print(f'{len(root.findall("channel"))} channels, {len(root.findall("programme"))} programmes')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ET.ParseError, ValueError) as exc:
        print(f'Global guide merge failed: {exc}', file=sys.stderr)
        raise SystemExit(1)
