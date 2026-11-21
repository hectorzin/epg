#!/usr/bin/env python3
"""Grab Canal+ Afrique day schedules without the upstream detail fan-out.

The iptv-org parser for canalplus.com loads every programme page with
``Promise.all``. From GitHub Actions that burst is answered with HTTP 403 and
Axios then prints the protection HTML. The public day listing already carries
title, startTime and endTime, which is the same schedule the local guide used.
This client requests that listing once per channel and day, pauses between
calls, and retries 403/429 without writing the response body to the log.
"""

from __future__ import annotations

import argparse
import json
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

AUTH_URL = (
    "https://hodor.canalplus.pro/api/v2/mycanal/authenticate.json/webapp/6.0"
    "?experiments=beta-test-one-tv-guide:control&offerZone={zone}&offerLocation={location}"
)
DAY_URL = "https://hodor.canalplus.pro/api/v2/mycanal/channels/{token}/{channel_id}/broadcasts/day/{offset}"
# Senegal bouquet. The same numeric channel exists under other country files;
# this grabber only accepts the zone the African table uses.
ZONES = {"sn": ("cpafr", "sn")}
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "fr-FR,fr;q=0.6",
    "Sec-CH-UA": '"Not:A-Brand";v="99", "Brave";v="145", "Chromium";v="145"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}
RETRY_STATUSES = {403, 429, 500, 502, 503, 504}
RETRIES = 4
TIMEOUT_SECONDS = 20


class GrabError(Exception):
    pass


def short_http_error(code: int, body: bytes, declared_length: int | None = None) -> str:
    sample = body.lstrip()[:32].lower()
    size = declared_length if declared_length and declared_length >= len(body) else len(body)
    if sample.startswith(b"<") or sample.startswith(b"<!doctype"):
        return f"HTTP {code} HTML challenge ({size} bytes)"
    return f"HTTP {code}"


def fetch_bytes(url: str, timeout: int = TIMEOUT_SECONDS) -> bytes:
    request = Request(url, headers=HEADERS)
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except HTTPError as exc:
        declared = exc.headers.get("Content-Length") if exc.headers else None
        try:
            length = int(declared) if declared else None
        except ValueError:
            length = None
        body = exc.read(64)
        raise GrabError(short_http_error(exc.code, body, length)) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise GrabError(f"request failed: {exc.__class__.__name__}") from exc


def fetch_json(url: str, *, get, sleep, attempts: int = RETRIES) -> dict:
    last = "request failed"
    for attempt in range(1, attempts + 1):
        try:
            payload = json.loads(get(url))
        except GrabError as exc:
            last = str(exc)
            retry = last.startswith("HTTP ") and any(
                last.startswith(f"HTTP {code}") for code in RETRY_STATUSES
            )
            retry = retry or last.startswith("request failed:")
            if not retry or attempt == attempts:
                raise GrabError(last) from exc
        except json.JSONDecodeError as exc:
            raise GrabError("response was not JSON") from exc
        else:
            if not isinstance(payload, dict):
                raise GrabError("response was not a JSON object")
            return payload
        sleep(min(30, 3 * attempt))
    raise GrabError(last)


def parse_channels(path: Path) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    for node in ET.parse(path).getroot().findall("channel"):
        site = (node.get("site") or "").strip()
        site_id = (node.get("site_id") or "").strip()
        name = "".join(node.itertext()).strip() or site_id
        if site != "canalplus.com":
            raise GrabError(f"{path}: unsupported site {site!r}")
        region, sep, channel_id = site_id.partition("#")
        if not sep or not region or not channel_id or region not in ZONES:
            raise GrabError(f"{path}: unsupported Canal+ Afrique site_id {site_id!r}")
        selected.append({"site_id": site_id, "region": region, "channel_id": channel_id, "name": name})
    if not selected:
        raise GrabError(f"{path}: no channels")
    return selected


def format_stamp(epoch_ms: int) -> str:
    moment = datetime.fromtimestamp(epoch_ms / 1000, timezone.utc)
    return moment.strftime("%Y%m%d%H%M%S +0000")


def programmes_from_day(payload: dict, channel_id: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for time_slice in payload.get("timeSlices") or []:
        if not isinstance(time_slice, dict):
            continue
        for item in time_slice.get("contents") or []:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            start = item.get("startTime")
            stop = item.get("endTime")
            if not title or not isinstance(start, (int, float)) or not isinstance(stop, (int, float)):
                continue
            if stop <= start:
                continue
            rows.append(
                {
                    "channel": channel_id,
                    "title": title,
                    "start": format_stamp(int(start)),
                    "stop": format_stamp(int(stop)),
                }
            )
    return rows


def authenticate(region: str, *, get, sleep) -> str:
    zone, location = ZONES[region]
    payload = fetch_json(AUTH_URL.format(zone=zone, location=location), get=get, sleep=sleep)
    token = str(payload.get("token") or "").strip()
    if not token:
        raise GrabError(f"Canal+ {region} authentication returned no token")
    return token


def grab_days(
    channels: list[dict[str, str]],
    *,
    days: int,
    delay: float,
    get,
    sleep,
) -> tuple[ET.Element, list[str]]:
    if days < 1:
        raise GrabError("--days must be >= 1")
    result = ET.Element("tv")
    failures: list[str] = []
    seen: set[tuple[str, str]] = set()
    tokens: dict[str, str] = {}
    for spec in channels:
        region = spec["region"]
        if region not in tokens:
            tokens[region] = authenticate(region, get=get, sleep=sleep)
            if delay:
                sleep(delay)
        channel = ET.SubElement(result, "channel", id=spec["site_id"])
        ET.SubElement(channel, "display-name").text = spec["name"]
        kept = 0
        for offset in range(days):
            url = DAY_URL.format(token=tokens[region], channel_id=spec["channel_id"], offset=offset)
            try:
                payload = fetch_json(url, get=get, sleep=sleep)
            except GrabError as exc:
                failures.append(f"{spec['site_id']} day {offset}: {exc}")
                if delay:
                    sleep(delay)
                continue
            for programme in programmes_from_day(payload, spec["site_id"]):
                key = (programme["channel"], programme["start"])
                if key in seen:
                    continue
                seen.add(key)
                node = ET.SubElement(
                    result,
                    "programme",
                    channel=programme["channel"],
                    start=programme["start"],
                    stop=programme["stop"],
                )
                ET.SubElement(node, "title", lang="fr").text = programme["title"]
                kept += 1
            if delay:
                sleep(delay)
        if kept == 0:
            result.remove(channel)
    normalize_channels_in_tree(result)
    return result, failures


def write_guide(path: Path, root: ET.Element) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--min-programmes", type=int, default=400)
    args = parser.parse_args()
    if args.delay < 0:
        raise GrabError("--delay must be >= 0")
    root, failures = grab_days(
        parse_channels(args.channels),
        days=args.days,
        delay=args.delay,
        get=fetch_bytes,
        sleep=time.sleep,
    )
    programmes = root.findall("programme")
    for failure in failures:
        print(f"Canal+ Afrique retry exhausted: {failure}", file=sys.stderr)
    if len(programmes) < args.min_programmes:
        raise GrabError(
            f"Canal+ Afrique produced {len(programmes)} programmes "
            f"(minimum {args.min_programmes}); refusing a partial guide"
        )
    write_guide(args.output, root)
    print(
        f"Grabbed Canal+ Afrique: {len(root.findall('channel'))} channels, "
        f"{len(programmes)} programmes -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (GrabError, OSError, ET.ParseError, ValueError) as exc:
        print(f"Canal+ Afrique grab failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
