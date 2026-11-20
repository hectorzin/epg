#!/usr/bin/env python3
"""Grab curated EPGShare channels using the iptv-org ripper URL contract.

Reuses the same feed as sites/epgshare01.online in iptv-org/epg:

    https://epgshare01.online/epgshare01/epg_ripper_{tag}.xml.gz

site_id format: {tag}#{channel_id}
"""

from __future__ import annotations

import argparse
import copy
import gzip
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from xmltv_channel import normalize_channels_in_tree  # noqa: E402

RIPPER_URL = "https://epgshare01.online/epgshare01/epg_ripper_{tag}.xml.gz"
USER_AGENT = "Mozilla/5.0 (compatible; epg-grab-epgshare/1.0)"
MAX_DOWNLOAD_BYTES = 80 * 1024 * 1024
RETRIES = 3
RETRY_PAUSE_SECONDS = 2


class GrabError(Exception):
    pass


def parse_channels_file(path: Path) -> list[dict[str, str]]:
    root = ET.parse(path).getroot()
    selected: list[dict[str, str]] = []
    for node in root.findall("channel"):
        site = (node.get("site") or "").strip()
        site_id = (node.get("site_id") or "").strip()
        xmltv_id = (node.get("xmltv_id") or "").strip()
        name = "".join(node.itertext()).strip()
        if site != "epgshare01.online":
            raise GrabError(f"{path}: unsupported site {site!r}")
        if "#" not in site_id:
            raise GrabError(f"{path}: site_id must be TAG#channelId, got {site_id!r}")
        tag, source_id = site_id.split("#", 1)
        if not tag or not source_id:
            raise GrabError(f"{path}: invalid site_id {site_id!r}")
        selected.append(
            {
                "tag": tag,
                "source_id": source_id,
                "xmltv_id": xmltv_id or source_id,
                "name": name or source_id,
            }
        )
    if not selected:
        raise GrabError(f"{path}: no channels")
    return selected


def download_ripper(tag: str) -> bytes:
    url = RIPPER_URL.format(tag=tag)
    last_error: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
            with urlopen(request, timeout=60) as response:
                data = response.read(MAX_DOWNLOAD_BYTES + 1)
            if len(data) > MAX_DOWNLOAD_BYTES:
                raise GrabError(f"{url}: download exceeded {MAX_DOWNLOAD_BYTES} bytes")
            if not data:
                raise GrabError(f"{url}: empty response")
            return gzip.decompress(data)
        except (HTTPError, URLError, TimeoutError, OSError, GrabError, gzip.BadGzipFile) as exc:
            last_error = exc
            if attempt < RETRIES:
                time.sleep(RETRY_PAUSE_SECONDS)
    raise GrabError(f"could not download EPGShare {tag}: {last_error}") from last_error


def parse_xmltv_stamp(value: str) -> datetime:
    raw = (value or "").strip()
    if not raw:
        raise GrabError("empty XMLTV timestamp")
    parts = raw.split(None, 1)
    when = datetime.strptime(parts[0], "%Y%m%d%H%M%S")
    if len(parts) == 1:
        return when.replace(tzinfo=timezone.utc)
    zone = parts[1].strip()
    if zone.upper() in {"Z", "UTC"}:
        return when.replace(tzinfo=timezone.utc)
    sign = 1 if zone[0] == "+" else -1
    hours = int(zone[1:3])
    minutes = int(zone[3:5])
    return when.replace(tzinfo=timezone(sign * timedelta(hours=hours, minutes=minutes)))


def wanted_days(days: int, today: datetime.date) -> set[datetime.date]:
    return {today + timedelta(days=offset) for offset in range(days)}


def keep_programme(programme: ET.Element, days: set[datetime.date]) -> bool:
    start = programme.get("start") or ""
    stop = programme.get("stop") or ""
    title = (programme.findtext("title") or "").strip()
    if not start or not stop or not title:
        return False
    try:
        start_day = parse_xmltv_stamp(start).astimezone(timezone.utc).date()
    except (ValueError, GrabError):
        return False
    return start_day in days


def copy_channel(source: ET.Element, xmltv_id: str, name: str) -> ET.Element:
    channel = ET.Element("channel", id=xmltv_id)
    display = ET.SubElement(channel, "display-name")
    display.text = name
    for icon in source.findall("icon"):
        channel.append(copy.deepcopy(icon))
    for url in source.findall("url"):
        channel.append(copy.deepcopy(url))
    return channel


def channels_from_ripper(tag: str, xml: bytes) -> list[dict[str, str]]:
    """Every channel in one ripper, keeping the source id as the XMLTV id."""
    root = ET.fromstring(xml)
    if root.tag != "tv":
        raise GrabError(f"EPGShare {tag}: root is not <tv>")
    selected: list[dict[str, str]] = []
    for node in root.findall("channel"):
        source_id = (node.get("id") or "").strip()
        if not source_id:
            continue
        name = ""
        for display in node.findall("display-name"):
            name = (display.text or "").strip()
            if name:
                break
        selected.append(
            {
                "tag": tag,
                "source_id": source_id,
                "xmltv_id": source_id,
                "name": name or source_id,
            }
        )
    if not selected:
        raise GrabError(f"EPGShare {tag}: no channels")
    return selected


def build_guide(
    channels: list[dict[str, str]],
    *,
    days: int,
    today: datetime.date | None = None,
    download=download_ripper,
    preloaded: dict[str, bytes] | None = None,
) -> ET.Element:
    today = today or datetime.now(timezone.utc).date()
    window = wanted_days(days, today)
    by_tag: dict[str, list[dict[str, str]]] = {}
    for channel in channels:
        by_tag.setdefault(channel["tag"], []).append(channel)

    result = ET.Element("tv")
    programmes_out = 0
    for tag, requested in by_tag.items():
        wanted = {item["source_id"]: item for item in requested}
        xml = preloaded.get(tag) if preloaded and tag in preloaded else download(tag)
        root = ET.fromstring(xml)
        if root.tag != "tv":
            raise GrabError(f"EPGShare {tag}: root is not <tv>")
        source_channels = {
            node.get("id"): node for node in root.findall("channel") if node.get("id")
        }
        for source_id, spec in wanted.items():
            source = source_channels.get(source_id)
            if source is None:
                raise GrabError(f"EPGShare {tag}: missing channel {source_id}")
            result.append(copy_channel(source, spec["xmltv_id"], spec["name"]))
        for programme in root.findall("programme"):
            source_id = programme.get("channel") or ""
            spec = wanted.get(source_id)
            if spec is None or not keep_programme(programme, window):
                continue
            clone = copy.deepcopy(programme)
            clone.set("channel", spec["xmltv_id"])
            result.append(clone)
            programmes_out += 1
    if not result.findall("channel"):
        raise GrabError("EPGShare grab produced no channels")
    if programmes_out == 0:
        raise GrabError("EPGShare grab produced no programmes")
    normalize_channels_in_tree(result)
    return result


def inject_into(target: Path, source: ET.Element) -> None:
    dest = ET.parse(target).getroot()
    if dest.tag != "tv":
        raise GrabError(f"{target}: expected <tv> root")
    incoming = {node.get("id") for node in source.findall("channel") if node.get("id")}
    if not incoming:
        raise GrabError("inject source has no channels")
    for child in list(dest):
        if child.tag == "channel" and child.get("id") in incoming:
            dest.remove(child)
        elif child.tag == "programme" and child.get("channel") in incoming:
            dest.remove(child)
    for channel in source.findall("channel"):
        dest.append(copy.deepcopy(channel))
    for programme in source.findall("programme"):
        dest.append(copy.deepcopy(programme))
    normalize_channels_in_tree(dest)
    ET.ElementTree(dest).write(target, encoding="utf-8", xml_declaration=True)


def write_guide(path: Path, root: ET.Element) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channels", type=Path, help="Curated channels file. Omit with --tag.")
    parser.add_argument(
        "--tag",
        help="Grab every channel from this EPGShare ripper tag (for example TR1)",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--today", help="UTC calendar date YYYY-MM-DD (default: now)")
    parser.add_argument(
        "--inject-into",
        action="append",
        type=Path,
        default=[],
        help="Replace these XMLTV files' matching channel ids with the grab",
    )
    args = parser.parse_args()
    if args.days < 1:
        raise GrabError("--days must be >= 1")
    if not args.channels and not args.tag:
        raise GrabError("pass --channels or --tag")
    today = None
    if args.today:
        today = datetime.strptime(args.today, "%Y-%m-%d").date()
    preloaded: dict[str, bytes] | None = None
    if args.channels:
        selected = parse_channels_file(args.channels)
    else:
        downloaded = download_ripper(args.tag)
        selected = channels_from_ripper(args.tag, downloaded)
        preloaded = {args.tag: downloaded}
    root = build_guide(selected, days=args.days, today=today, preloaded=preloaded)
    write_guide(args.output, root)
    for target in args.inject_into:
        inject_into(target, root)
        print(f"Injected {', '.join(c['xmltv_id'] for c in selected)} into {target}")
    print(
        f"Grabbed EPGShare: {len(root.findall('channel'))} channels, "
        f"{len(root.findall('programme'))} programmes -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (GrabError, OSError, ET.ParseError, ValueError) as exc:
        print(f"EPGShare grab failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
