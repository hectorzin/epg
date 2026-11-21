#!/usr/bin/env python3
"""Grab the public SNRT schedule for a curated set of Moroccan TV channels.

The upstream ``snrt.ma`` parser requests the same HTML grid, but that request
is rejected with HTTP 403 unless it carries a browser user-agent. This script
reads ``https://www.snrt.ma/ar/node/{site_id}`` and keeps the two-day window
used by the national guides. Radio nodes are refused: they are not TV feeds.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from xmltv_channel import normalize_channels_in_tree  # noqa: E402

PAGE_URL = "https://www.snrt.ma/ar/node/{site_id}"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
# SNRT publishes Africa/Casablanca wall time. Morocco has stayed on UTC+1 since 2018;
# a fixed offset avoids a stale Windows zone database shifting the grid by an hour.
TIMEZONE = timezone(timedelta(hours=1))
RADIO_SITE_IDS = {"4076", "4077", "4078", "4079"}
RETRIES = 3
RETRY_PAUSE_SECONDS = 2
TIME_RE = re.compile(r"(\d{1,2})H(\d{2})")
VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


class GrabError(Exception):
    pass


class _GridParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.items: list[dict[str, str]] = []
        self.current: dict[str, str] | None = None
        self.line_depth = 0
        self.capture: str | None = None
        self.capture_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.depth += 1
        self._open(tag, attrs)
        if tag in VOID_TAGS:
            self._close()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.depth += 1
        self._open(tag, attrs)
        self._close()

    def handle_endtag(self, tag: str) -> None:
        self._close()

    def handle_data(self, data: str) -> None:
        if self.current is not None and self.capture:
            self.current[self.capture] += data

    def _open(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = (dict(attrs).get("class") or "").split()
        if self.current is None and "grille-line" in classes:
            matched = re.search(r"\d{8}", " ".join(classes))
            self.current = {
                "date": matched.group(0) if matched else "",
                "time": "",
                "title": "",
                "description": "",
            }
            self.line_depth = self.depth
            return
        if self.current is None or self.capture:
            return
        if "grille-time" in classes:
            self.capture = "time"
            self.capture_depth = self.depth
        elif tag == "h2" and "program-title-sm" in classes:
            self.capture = "title"
            self.capture_depth = self.depth
        elif "program-description-sm" in classes:
            self.capture = "description"
            self.capture_depth = self.depth

    def _close(self) -> None:
        if self.capture and self.depth == self.capture_depth:
            self.capture = None
        if self.current is not None and self.depth == self.line_depth:
            self.items.append(self.current)
            self.current = None
        self.depth -= 1


def parse_channels_file(path: Path) -> list[dict[str, str]]:
    root = ET.parse(path).getroot()
    selected: list[dict[str, str]] = []
    for node in root.findall("channel"):
        site = (node.get("site") or "").strip()
        site_id = (node.get("site_id") or "").strip()
        xmltv_id = (node.get("xmltv_id") or "").strip()
        expect = (node.get("expect") or "").strip()
        name = "".join(node.itertext()).strip()
        if site != "snrt.ma":
            raise GrabError(f"{path}: unsupported site {site!r}")
        if site_id in RADIO_SITE_IDS:
            raise GrabError(f"{path}: {site_id} is an SNRT radio feed")
        if not site_id or not xmltv_id or not expect or not name:
            raise GrabError(f"{path}: channel {site_id or name!r} needs site_id, xmltv_id, expect and a name")
        selected.append(
            {"site_id": site_id, "xmltv_id": xmltv_id, "expect": expect, "name": name}
        )
    if not selected:
        raise GrabError(f"{path}: no channels")
    return selected


def download_page(site_id: str) -> str:
    url = PAGE_URL.format(site_id=site_id)
    last_error: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html",
                    "Accept-Language": "ar,fr;q=0.8",
                },
            )
            with urlopen(request, timeout=40) as response:
                data = response.read()
            if not data:
                raise GrabError(f"{url}: empty response")
            return data.decode("utf-8", errors="replace")
        except (HTTPError, URLError, TimeoutError, OSError, GrabError) as exc:
            last_error = exc
            if attempt < RETRIES:
                time.sleep(RETRY_PAUSE_SECONDS)
    raise GrabError(f"could not download SNRT {site_id}: {last_error}") from last_error


def page_title(html: str) -> str:
    matched = re.search(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    return re.sub(r"\s+", " ", matched.group(1)).strip() if matched else ""


def parse_grid(html: str) -> list[dict[str, object]]:
    parser = _GridParser()
    parser.feed(html)
    programmes: list[dict[str, object]] = []
    for item in parser.items:
        title = re.sub(r"\s+", " ", item["title"]).strip()
        timed = TIME_RE.search(item["time"])
        if not item["date"] or timed is None or not title:
            continue
        hour = int(timed.group(1))
        minute = int(timed.group(2))
        if hour > 23 or minute > 59:
            continue
        start = datetime.strptime(item["date"], "%Y%m%d").replace(
            hour=hour,
            minute=minute,
            tzinfo=TIMEZONE,
        )
        programmes.append(
            {
                "start": start,
                "title": title,
                "description": re.sub(r"\s+", " ", item["description"]).strip(),
            }
        )
    programmes.sort(key=lambda row: row["start"])
    for index, programme in enumerate(programmes):
        if index + 1 < len(programmes):
            programme["stop"] = programmes[index + 1]["start"]
        else:
            start = programme["start"]
            assert isinstance(start, datetime)
            next_day = (start + timedelta(days=1)).date()
            programme["stop"] = datetime(
                next_day.year, next_day.month, next_day.day, tzinfo=TIMEZONE
            )
    return [row for row in programmes if row["stop"] > row["start"]]


def format_stamp(value: datetime) -> str:
    local = value.astimezone(TIMEZONE)
    offset = local.utcoffset() or timedelta(0)
    total = int(offset.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    hours, minutes = divmod(total // 60, 60)
    return local.strftime("%Y%m%d%H%M%S ") + f"{sign}{hours:02d}{minutes:02d}"


def wanted_days(days: int, today: datetime.date) -> set[datetime.date]:
    return {today + timedelta(days=offset) for offset in range(days)}


def build_guide(
    selected: list[dict[str, str]],
    *,
    days: int,
    today: datetime.date | None,
    alias_names: dict[str, list[str]] | None = None,
) -> ET.Element:
    if today is None:
        today = datetime.now(TIMEZONE).date()
    window = wanted_days(days, today)
    result = ET.Element("tv")
    kept = 0
    for spec in selected:
        html = download_page(spec["site_id"])
        title = page_title(html)
        if spec["expect"] not in title:
            raise GrabError(
                f"SNRT {spec['site_id']} title {title!r} does not contain {spec['expect']!r}"
            )
        names = [spec["name"]]
        for alias in (alias_names or {}).get(spec["xmltv_id"], []):
            if alias not in names:
                names.append(alias)
        channel = ET.SubElement(result, "channel", id=spec["xmltv_id"])
        for name in names:
            ET.SubElement(channel, "display-name").text = name
        for programme in parse_grid(html):
            start = programme["start"]
            stop = programme["stop"]
            assert isinstance(start, datetime) and isinstance(stop, datetime)
            if start.astimezone(TIMEZONE).date() not in window:
                continue
            node = ET.SubElement(
                result,
                "programme",
                channel=spec["xmltv_id"],
                start=format_stamp(start),
                stop=format_stamp(stop),
            )
            ET.SubElement(node, "title", lang="ar").text = str(programme["title"])
            if programme["description"]:
                ET.SubElement(node, "desc", lang="ar").text = str(programme["description"])
            kept += 1
    if kept == 0:
        raise GrabError("SNRT grab produced no programmes")
    normalize_channels_in_tree(result)
    return result


def programmed_ids(paths: list[Path]) -> set[str]:
    found: set[str] = set()
    for path in paths:
        if not path.is_file() or path.stat().st_size == 0:
            continue
        for _event, elem in ET.iterparse(path, events=("end",)):
            if elem.tag == "programme" and (elem.findtext("title") or "").strip():
                found.add(elem.get("channel") or "")
            if elem.tag in {"programme", "channel"}:
                elem.clear()
    found.discard("")
    return found


def append_unoccupied(target: Path, source: ET.Element, occupied: list[Path]) -> list[str]:
    blocked = programmed_ids(occupied)
    existing = ET.parse(target).getroot()
    if existing.tag != "tv":
        raise GrabError(f"{target}: expected <tv> root")
    already = {node.get("id") for node in existing.findall("channel")}
    added: list[str] = []
    for channel in source.findall("channel"):
        channel_id = channel.get("id") or ""
        if not channel_id or channel_id in blocked or channel_id in already:
            continue
        programmes = [
            programme
            for programme in source.findall("programme")
            if programme.get("channel") == channel_id and (programme.findtext("title") or "").strip()
        ]
        if not programmes:
            continue
        existing.append(channel)
        for programme in programmes:
            existing.append(programme)
        added.append(channel_id)
    if not added:
        return []
    normalize_channels_in_tree(existing)
    ET.indent(existing, space="  ")
    ET.ElementTree(existing).write(target, encoding="utf-8", xml_declaration=True)
    return added


def load_alias_names(path: Path | None) -> dict[str, list[str]]:
    if path is None or not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise GrabError(f"{path}: aliases must be an object")
    names: dict[str, list[str]] = {}
    for channel_id, values in data.items():
        if isinstance(channel_id, str) and isinstance(values, list):
            names[channel_id] = [str(value) for value in values if str(value).strip()]
    return names


def write_guide(path: Path, root: ET.Element) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--today", help="Africa/Casablanca date YYYY-MM-DD")
    parser.add_argument("--aliases", type=Path)
    parser.add_argument("--append-to", type=Path)
    parser.add_argument("--occupied-guide", action="append", type=Path, default=[])
    args = parser.parse_args()
    if args.days < 1:
        raise GrabError("--days must be >= 1")
    today = datetime.strptime(args.today, "%Y-%m-%d").date() if args.today else None
    root = build_guide(
        parse_channels_file(args.channels),
        days=args.days,
        today=today,
        alias_names=load_alias_names(args.aliases),
    )
    write_guide(args.output, root)
    added: list[str] = []
    if args.append_to:
        added = append_unoccupied(args.append_to, root, args.occupied_guide)
    print(
        f"Grabbed SNRT: {len(root.findall('channel'))} channels, "
        f"{len(root.findall('programme'))} programmes -> {args.output}"
    )
    if args.append_to:
        print(f"Appended {', '.join(added) if added else 'nothing'} to {args.append_to}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (GrabError, OSError, ET.ParseError, ValueError, json.JSONDecodeError) as exc:
        print(f"SNRT grab failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
