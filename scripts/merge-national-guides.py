#!/usr/bin/env python3
"""Merge all valid national XMLTV guides into one global guide."""

from __future__ import annotations

import argparse
import copy
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import xml.etree.ElementTree as ET

from xmltv_channel import normalize_channel_children

NATIONAL_GUIDE_PATTERN = re.compile(r'^(?:guide-[a-z]{2}|guide-arabic)\.xml$', re.IGNORECASE)
MADRID = ZoneInfo('Europe/Madrid')
LAST_RUN: dict[str, int] = {
    'programmes_before_filter': 0,
    'programmes_removed': 0,
    'programmes_trimmed_tomorrow': 0,
}
TOMORROW_PROGRAMME_CHILDREN = frozenset({'title', 'category'})


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


def parse_xmltv_datetime(value: str) -> datetime:
    """Parse an XMLTV programme start/stop timestamp with its timezone offset."""
    raw = (value or '').strip()
    if not raw:
        raise ValueError('empty XMLTV timestamp')
    parts = raw.split(None, 1)
    if not re.fullmatch(r'\d{14}', parts[0]):
        raise ValueError(f'unrecognised XMLTV timestamp: {value!r}')
    when = datetime.strptime(parts[0], '%Y%m%d%H%M%S')
    if len(parts) == 1:
        return when.replace(tzinfo=timezone.utc)
    tz_part = parts[1].strip()
    upper = tz_part.upper()
    if upper in ('Z', 'UTC'):
        return when.replace(tzinfo=timezone.utc)
    offset_match = re.fullmatch(r'([+-])(\d{2}):?(\d{2})', tz_part)
    if not offset_match:
        raise ValueError(f'unrecognised XMLTV timezone: {value!r}')
    sign = 1 if offset_match.group(1) == '+' else -1
    hours = int(offset_match.group(2))
    minutes = int(offset_match.group(3))
    offset = timezone(sign * timedelta(hours=hours, minutes=minutes))
    return when.replace(tzinfo=offset)


def madrid_two_day_window(reference: datetime | None = None) -> tuple[datetime, datetime]:
    """Inclusive today and tomorrow in Europe/Madrid, as [start, end)."""
    anchor = datetime.now(MADRID) if reference is None else reference.astimezone(MADRID)
    start = anchor.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=2)
    return start, end


def programme_overlaps_window(start: str, stop: str, window_start: datetime, window_end: datetime) -> bool:
    """Keep programmes that overlap the Madrid window (half-open interval)."""
    programme_start = parse_xmltv_datetime(start).astimezone(MADRID)
    programme_stop = parse_xmltv_datetime(stop).astimezone(MADRID)
    return programme_start < window_end and programme_stop > window_start


def programme_start_madrid_date(programme: ET.Element) -> datetime.date:
    start = programme.get('start') or ''
    if not start:
        raise ValueError('programme start is required')
    return parse_xmltv_datetime(start).astimezone(MADRID).date()


def trim_tomorrow_programme_metadata(result: ET.Element, window_start: datetime) -> int:
    """Keep full metadata for programmes starting today; slim tomorrow-only starts."""
    today = window_start.date()
    tomorrow = today + timedelta(days=1)
    trimmed = 0
    for programme in result.findall('programme'):
        try:
            start_day = programme_start_madrid_date(programme)
        except ValueError:
            continue
        if start_day != tomorrow:
            continue
        for child in list(programme):
            if child.tag not in TOMORROW_PROGRAMME_CHILDREN:
                programme.remove(child)
        trimmed += 1
    return trimmed


def filter_programmes(result: ET.Element, window_start: datetime, window_end: datetime) -> int:
    """Drop programmes outside the window; return how many were removed."""
    removed = 0
    for programme in list(result.findall('programme')):
        start = programme.get('start') or ''
        stop = programme.get('stop') or ''
        try:
            keep = programme_overlaps_window(start, stop, window_start, window_end)
        except ValueError as exc:
            raise ValueError(f'programme timestamp could not be parsed ({start!r}, {stop!r}): {exc}') from exc
        if not keep:
            result.remove(programme)
            removed += 1
    return removed


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


def merge(paths, *, reference: datetime | None = None, trim_tomorrow_metadata: bool = True) -> ET.Element:
    channels = {}
    programs = {}
    for path in paths:
        root = read_guide(path)
        for c in root.findall('channel'):
            channel_id = c.get('id')
            if channel_id not in channels:
                channels[channel_id] = copy.deepcopy(c)
                continue
            # Keep aliases from every national producer when the same XMLTV
            # channel is present in multiple guides. The first definition
            # remains authoritative for other metadata.
            canonical = channels[channel_id]
            known_names = {
                (node.text or '', tuple(sorted(node.attrib.items())))
                for node in canonical.findall('display-name')
            }
            for display_name in c.findall('display-name'):
                identity = (display_name.text or '', tuple(sorted(display_name.attrib.items())))
                if identity not in known_names:
                    canonical.append(copy.deepcopy(display_name))
                    known_names.add(identity)
        for p in root.findall('programme'):
            key = (p.get('channel'), p.get('start'), p.get('stop'), tuple((x.tag, x.text or '') for x in p))
            programs.setdefault(key, copy.deepcopy(p))
    if not programs:
        raise ValueError('all national guides are empty')
    result = ET.Element('tv')
    for c in channels.values():
        normalize_channel_children(c)
        result.append(c)
    for p in programs.values():
        result.append(p)
    window_start, window_end = madrid_two_day_window(reference)
    LAST_RUN['programmes_before_filter'] = len(programs)
    LAST_RUN['programmes_removed'] = filter_programmes(result, window_start, window_end)
    LAST_RUN['programmes_trimmed_tomorrow'] = (
        trim_tomorrow_programme_metadata(result, window_start) if trim_tomorrow_metadata else 0
    )
    if not result.findall('programme'):
        raise ValueError(
            'no programmes remain after filtering to today and tomorrow in Europe/Madrid '
            f'({window_start.isoformat()} .. {window_end.isoformat()})'
        )
    return result


def resolve_guide_paths(root: Path | None, guides: list[Path]) -> list[Path]:
    if guides:
        return guides
    search_root = root if root is not None else Path('.')
    discovered = discover_national_guides(search_root, validate=True)
    if not discovered:
        raise ValueError(f'no national guides matching guide-XX.xml in {search_root}')
    return discovered


def parse_reference_date(value: str) -> datetime:
    try:
        when = datetime.strptime(value, '%Y-%m-%d')
    except ValueError as exc:
        raise argparse.ArgumentTypeError('reference date must use YYYY-MM-DD') from exc
    return when.replace(tzinfo=MADRID)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--root',
        type=Path,
        default=None,
        help='Directory to scan for guide-XX.xml when no guide paths are given',
    )
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument(
        '--reference-date',
        type=parse_reference_date,
        default=None,
        help='Interpret "today" on this calendar day in Europe/Madrid (default: now)',
    )
    parser.add_argument(
        '--no-trim-tomorrow-metadata',
        action='store_true',
        help='Keep every programme child element for both Madrid window days',
    )
    parser.add_argument('guides', nargs='*', type=Path)
    args = parser.parse_args()
    paths = resolve_guide_paths(args.root, args.guides)
    merged = merge(
        paths,
        reference=args.reference_date,
        trim_tomorrow_metadata=not args.no_trim_tomorrow_metadata,
    )
    _scripts = Path(__file__).resolve().parent
    if str(_scripts) not in sys.path:
        sys.path.insert(0, str(_scripts))
    from es_xtream_policy import (  # noqa: WPS433
        apply_channel_id_renames,
        channel_renames,
        denied_xtream_clone_ids,
        purge_denied_clone_channels,
    )

    apply_channel_id_renames(merged, channel_renames())
    purge_denied_clone_channels(merged, denied_xtream_clone_ids())
    window_start, window_end = madrid_two_day_window(args.reference_date)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(merged, space='  ')
    ET.ElementTree(merged).write(args.output, encoding='utf-8', xml_declaration=True)
    names = [p.name for p in paths]
    programme_count = len(merged.findall('programme'))
    print(
        f'Merged {", ".join(names)}: {len(merged.findall("channel"))} channels, '
        f'{programme_count} programmes '
        f'(Madrid window {window_start.date()}..{(window_end - timedelta(days=1)).date()}, '
        f'{LAST_RUN["programmes_removed"]} programmes dropped, '
        f'{LAST_RUN["programmes_trimmed_tomorrow"]} tomorrow starts slimmed)'
    )


if __name__ == '__main__':
    try:
        main()
    except (OSError, ET.ParseError, ValueError) as exc:
        print(f'Global guide merge failed: {exc}', file=sys.stderr)
        raise SystemExit(1)
