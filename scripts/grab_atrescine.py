#!/usr/bin/env python3
"""Grab the public Atrescine schedule (Atresplayer a3cine feed)."""

from __future__ import annotations

import argparse
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from xmltv_channel import normalize_channels_in_tree  # noqa: E402

PAGE_URL = "https://www.atrescine.com/programacion/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
CHANNEL_ID = "cima.es.a3cine"
DISPLAY_NAMES = ("Atrescine", "Atrescine 2", "Atrescine Internacional")
TIMEZONE = timezone(timedelta(hours=1))
ITEM_RE = re.compile(
    r'class="programacion-item[^"]*" '
    r'data-start="(?P<start_ms>\d+)" data-end="(?P<end_ms>\d+)".*?'
    r'<h2 class="item-title">(?P<title>[^<]+)</h2>.*?'
    r'<p class="item-description">(?P<desc>.*?)</p>',
    re.S,
)
RETRIES = 3
RETRY_PAUSE_SECONDS = 2


class GrabError(Exception):
    pass


def download_page(url: str = PAGE_URL) -> str:
    last_error: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"})
            with urlopen(request, timeout=45) as response:
                payload = response.read(8 * 1024 * 1024)
            text = payload.decode("utf-8", errors="replace")
            if "programacion-item" not in text:
                raise GrabError("Atrescine HTML does not contain programme grid")
            return text
        except (HTTPError, URLError, TimeoutError, OSError, GrabError) as exc:
            last_error = exc
            if attempt < RETRIES:
                time.sleep(RETRY_PAUSE_SECONDS)
    raise GrabError(f"could not download Atrescine schedule: {last_error}") from last_error


def parse_programmes(html: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for match in ITEM_RE.finditer(html):
        title = re.sub(r"\s+", " ", match.group("title")).strip()
        if not title:
            continue
        description = re.sub(r"\s+", " ", match.group("desc")).strip()
        start = datetime.fromtimestamp(int(match.group("start_ms")) / 1000, tz=TIMEZONE)
        stop = datetime.fromtimestamp(int(match.group("end_ms")) / 1000, tz=TIMEZONE)
        if stop <= start:
            continue
        rows.append({"title": title, "description": description, "start": start, "stop": stop})
    rows.sort(key=lambda row: row["start"])  # type: ignore[return-value, arg-type]
    return rows


def format_stamp(value: datetime) -> str:
    local = value.astimezone(TIMEZONE)
    return local.strftime("%Y%m%d%H%M%S +0100")


def wanted_days(days: int, today: date) -> set[date]:
    return {today + timedelta(days=offset) for offset in range(days)}


def build_guide(html: str, *, days: int, today: date | None = None) -> ET.Element:
    if today is None:
        today = datetime.now(TIMEZONE).date()
    window = wanted_days(days, today)
    programmes = parse_programmes(html)
    if not programmes:
        raise GrabError("Atrescine parse produced no programmes")
    root = ET.Element("tv")
    channel = ET.SubElement(root, "channel", id=CHANNEL_ID)
    for name in DISPLAY_NAMES:
        ET.SubElement(channel, "display-name").text = name
    kept = 0
    for row in programmes:
        start = row["start"]
        assert isinstance(start, datetime)
        if start.astimezone(TIMEZONE).date() not in window:
            continue
        node = ET.SubElement(
            root,
            "programme",
            channel=CHANNEL_ID,
            start=format_stamp(start),
            stop=format_stamp(row["stop"]),  # type: ignore[arg-type]
        )
        ET.SubElement(node, "title", lang="es").text = str(row["title"])
        if row["description"]:
            ET.SubElement(node, "desc", lang="es").text = str(row["description"])
        kept += 1
    if kept == 0:
        raise GrabError("Atrescine grab produced no programmes in the requested window")
    normalize_channels_in_tree(root)
    return root


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--html", type=Path, help="Offline HTML fixture (for tests)")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    html = args.html.read_text(encoding="utf-8") if args.html else download_page()
    guide = build_guide(html, days=args.days)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(guide).write(args.output, encoding="utf-8", xml_declaration=True)
    channels = len(guide.findall("channel"))
    programmes = len(guide.findall("programme"))
    print(f"Wrote {args.output} ({channels} channels, {programmes} programmes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())