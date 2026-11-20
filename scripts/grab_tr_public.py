#!/usr/bin/env python3
"""Grab public Turkish operator EPG when the upstream Node grabber is blocked.

Uses the same D-Smart URL and timestamp rules as sites/dsmart.com.tr in
iptv-org/epg. Türkstat Kablo uses its public day JSON and Europe/Istanbul.
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from xmltv_channel import normalize_channels_in_tree  # noqa: E402

ISTANBUL = timezone(timedelta(hours=3))
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
)
DSMART_URL = "https://www.dsmart.com.tr/api/v1/public/epg/schedules?page={page}&limit=10&day={day}"
TURKSAT_URL = "https://www.turksatkablo.com.tr/userUpload/EPG/{day}.json"
TVPLUS_AUTH = "https://izmaottvsc14.tvplus.com.tr:33207/EPG/JSON/Authenticate"
TVPLUS_BILL = "https://izmaottvsc14.tvplus.com.tr:33207/EPG/JSON/PlayBillList"
TURKSAT_HOST = "www.turksatkablo.com.tr"
AIA_HOSTS = {"secure.globalsign.com"}
AIA_URL_RE = re.compile(rb"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+\.crt")


class GrabError(Exception):
    pass


def parse_utc(value: str) -> datetime:
    text = (value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    when = datetime.fromisoformat(text)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc)


def xmltv_stamp(when: datetime) -> str:
    local = when.astimezone(ISTANBUL)
    return local.strftime("%Y%m%d%H%M%S +0300")


def duration_seconds(value: str) -> int:
    clock = (value or "").split(",")[-1].strip()
    hours, minutes, seconds = (int(part) for part in clock.split(":"))
    return hours * 3600 + minutes * 60 + seconds


def dsmart_programmes(schedule: list[dict]) -> list[dict]:
    """Reproduce the iptv-org dsmart.com.tr offset from day + start_date."""
    programmes: list[dict] = []
    day_start: datetime | None = None
    offset = 0
    for item in schedule:
        if not item.get("day") or not item.get("start_date") or not item.get("duration"):
            continue
        title = (item.get("program_name") or "").strip()
        if not title:
            continue
        base = parse_utc(item["day"])
        start_date = parse_utc(item["start_date"])
        if day_start is None:
            day_start = start_date
            combined = parse_utc(item["day"][:11] + item["start_date"][11:])
            offset = int((combined - base).total_seconds())
        delta = int((start_date - day_start).total_seconds())
        start = base + timedelta(seconds=offset + delta)
        stop = start + timedelta(seconds=duration_seconds(item["duration"]))
        genre = (item.get("genre") or "").strip()
        categories = [part[:1].upper() + part[1:] for part in genre.split("/") if part.strip()] if "/" in genre else []
        programmes.append(
            {
                "title": title,
                "description": (item.get("description") or "").strip(),
                "categories": categories,
                "start": start,
                "stop": stop,
            }
        )
    return programmes


def istanbul_clock(day: datetime.date, clock: str) -> datetime:
    hour, minute = (int(part) for part in clock.split(":", 1))
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ISTANBUL)


def turksat_programmes(items: list[dict], day: datetime.date) -> list[dict]:
    """Same midnight rollover as sites/turksatkablo.com.tr."""
    programmes: list[dict] = []
    cursor = day
    for item in items:
        title = (item.get("b") or "").strip()
        start_clock = (item.get("c") or "").strip()
        stop_clock = (item.get("d") or "").strip()
        if not title or title == "-" or not start_clock or not stop_clock:
            continue
        start = istanbul_clock(cursor, start_clock)
        if programmes and start < programmes[-1]["start"]:
            cursor = cursor + timedelta(days=1)
            start = istanbul_clock(cursor, start_clock)
        stop = istanbul_clock(cursor, stop_clock)
        if stop <= start:
            cursor = cursor + timedelta(days=1)
            stop = istanbul_clock(cursor, stop_clock)
        programmes.append({"title": title, "description": "", "categories": [], "start": start, "stop": stop})
    return programmes


def tvplus_when(value: str) -> datetime:
    """TV+ clocks are Istanbul local times labeled UTC+03:00."""
    when = datetime.strptime((value or "").strip()[:19], "%Y-%m-%d %H:%M:%S")
    return when.replace(tzinfo=ISTANBUL)


def tvplus_session() -> str:
    payload = json.dumps(
        {
            "terminaltype": "webtv",
            "terminalvendor": USER_AGENT,
            "osversion": "Win32",
            "userType": "3",
            "utcEnable": "1",
            "timezone": "Europe/Istanbul",
        }
    ).encode()
    request = urllib.request.Request(
        TVPLUS_AUTH,
        data=payload,
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=40, context=ssl.create_default_context()) as response:
        cookie = (response.headers.get("set-cookie") or "").split(";", 1)[0].strip()
    if not cookie.startswith("XSESSIONID="):
        raise GrabError("TV+ did not return a session")
    return cookie


def tvplus_bill(session: str, site_id: str, start: datetime, stop: datetime) -> list[dict]:
    payload = json.dumps(
        {
            "type": "2",
            "channelid": site_id,
            "begintime": start.strftime("%Y%m%d%H%M%S"),
            "endtime": stop.strftime("%Y%m%d%H%M%S"),
            "isFillProgram": 1,
        }
    ).encode()
    request = urllib.request.Request(
        TVPLUS_BILL,
        data=payload,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Cookie": session,
        },
    )
    with urllib.request.urlopen(request, timeout=40, context=ssl.create_default_context()) as response:
        data = json.loads(response.read().decode("utf-8"))
    programmes: list[dict] = []
    for item in data.get("playbilllist") or []:
        title = (item.get("name") or "").strip()
        if not title or not item.get("starttime") or not item.get("endtime"):
            continue
        description = item.get("introduce") if isinstance(item.get("introduce"), str) else ""
        programmes.append(
            {
                "title": title,
                "description": description.strip(),
                "categories": [],
                "start": tvplus_when(item["starttime"]),
                "stop": tvplus_when(item["endtime"]),
            }
        )
    return programmes


def tvplus_channels(catalog: dict[str, dict[str, str]], days: list[datetime.date]) -> dict[str, dict]:
    if not catalog or not days:
        raise GrabError("TV+ needs a channel list and at least one day")
    session = tvplus_session()
    start = datetime(days[0].year, days[0].month, days[0].day, tzinfo=ISTANBUL)
    stop = start + timedelta(days=len(days))
    found: dict[str, dict] = {}
    for site_id, meta in catalog.items():
        try:
            programmes = tvplus_bill(session, site_id, start, stop)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            continue
        if programmes:
            found[site_id] = {"name": meta["name"], "programmes": programmes}
    return found


def load_catalog(path: Path | None) -> dict[str, dict[str, str]]:
    if path is None or not path.is_file():
        return {}
    root = ET.parse(path).getroot()
    found: dict[str, dict[str, str]] = {}
    for channel in root.findall("channel"):
        site_id = (channel.get("site_id") or "").strip()
        if not site_id:
            continue
        found[site_id] = {
            "xmltv_id": (channel.get("xmltv_id") or "").strip(),
            "name": "".join(channel.itertext()).strip(),
        }
    return found


def aia_crt_urls(der: bytes) -> list[str]:
    """CA issuers URLs embedded in a certificate. Only GlobalSign's own host is accepted."""
    urls: list[str] = []
    for raw in AIA_URL_RE.findall(der or b""):
        url = raw.decode("ascii")
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        if host in AIA_HOSTS and url not in urls:
            urls.append(url)
    return urls


def issuer_missing(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "certificate verify failed" in text or "unable to get local issuer" in text


def context_with_intermediate(pem: str) -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.load_verify_locations(cadata=pem)
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def turksat_verified_context() -> ssl.SSLContext:
    """Complete Türksat's chain with the intermediate named in the leaf, then verify it."""
    probe = ssl._create_unverified_context()
    with socket.create_connection((TURKSAT_HOST, 443), timeout=20) as sock:
        with probe.wrap_socket(sock, server_hostname=TURKSAT_HOST) as tls:
            der = tls.getpeercert(binary_form=True) or b""
    urls = aia_crt_urls(der)
    if not urls:
        raise GrabError(f"{TURKSAT_HOST}: certificate has no GlobalSign intermediate URL")
    request = urllib.request.Request(urls[0], headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        downloaded = response.read()
    if b"GlobalSign" not in downloaded and b"Globalsign" not in downloaded:
        raise GrabError(f"{TURKSAT_HOST}: downloaded issuer is not a GlobalSign certificate")
    pem = ssl.DER_cert_to_PEM_cert(downloaded) if downloaded.startswith(b"\x30") else downloaded.decode("ascii")
    return context_with_intermediate(pem)


def read_json(url: str, context: ssl.SSLContext | None) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=40, context=context) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise GrabError(f"{url}: expected a JSON object")
    return payload


def fetch_json(url: str) -> dict:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    try:
        return read_json(url, ssl.create_default_context())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        if host != TURKSAT_HOST or not issuer_missing(exc):
            raise GrabError(f"{url}: {exc}") from exc
    try:
        return read_json(url, turksat_verified_context())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise GrabError(f"{url}: {exc}") from exc


def dsmart_channels(days: list[datetime.date]) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for day in days:
        page = 1
        total_pages = 1
        while page <= total_pages:
            payload = fetch_json(DSMART_URL.format(page=page, day=day.isoformat()))
            data = payload.get("data") or {}
            total = int(data.get("total") or 0)
            total_pages = max(1, (total + 9) // 10)
            for channel in data.get("channels") or []:
                site_id = str(channel.get("_id") or "").strip()
                name = (channel.get("channel_name") or "").strip()
                if not site_id or not name:
                    continue
                bucket = found.setdefault(site_id, {"name": name, "programmes": []})
                bucket["programmes"].extend(dsmart_programmes(channel.get("schedule") or []))
            page += 1
    return found


def turksat_channels(days: list[datetime.date]) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for day in days:
        payload = fetch_json(TURKSAT_URL.format(day=day.strftime("%d")))
        for channel in payload.get("k") or []:
            site_id = str(channel.get("x") or channel.get("i") or "").strip()
            name = (channel.get("n") or "").strip()
            if not site_id or not name:
                continue
            bucket = found.setdefault(site_id, {"name": name, "programmes": []})
            bucket["programmes"].extend(turksat_programmes(channel.get("p") or [], day))
    return found


_STATION_KEY = None


def turkish_station_key(name: str) -> str:
    global _STATION_KEY
    if _STATION_KEY is None:
        import importlib.util

        path = Path(__file__).resolve().parent / "tr-epg.py"
        spec = importlib.util.spec_from_file_location("tr_epg_identity", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _STATION_KEY = module.station_key
    return _STATION_KEY(name)


def turkish_xmltv_id(value: str | None) -> str:
    text = (value or "").strip()
    if ".tr@" not in text:
        return ""
    return text


def catalog_for(site_id: str, name: str, catalog: dict[str, dict[str, str]]) -> dict[str, str]:
    direct = catalog.get(site_id) or {}
    if turkish_xmltv_id(direct.get("xmltv_id")):
        return direct
    folded = name.casefold()
    exact = [
        item
        for item in catalog.values()
        if item.get("name", "").casefold() == folded and turkish_xmltv_id(item.get("xmltv_id"))
    ]
    if exact:
        return exact[0]
    key = turkish_station_key(name)
    if not key:
        return {"name": name, "xmltv_id": ""}
    hits = [
        item
        for item in catalog.values()
        if turkish_xmltv_id(item.get("xmltv_id")) and turkish_station_key(item.get("name") or "") == key
    ]
    ids = {item.get("xmltv_id") for item in hits}
    if len(ids) == 1:
        return hits[0]
    return {"name": name, "xmltv_id": ""}


def write_guide(path: Path, channels: dict[str, dict], catalog: dict[str, dict[str, str]]) -> tuple[int, int]:
    root = ET.Element("tv")
    programme_count = 0
    used_ids: set[str] = set()
    for site_id, channel in sorted(channels.items(), key=lambda item: item[1]["name"].casefold()):
        programmes = channel["programmes"]
        if not programmes:
            continue
        meta = catalog_for(site_id, channel["name"], catalog)
        channel_id = meta.get("xmltv_id") or site_id
        if channel_id in used_ids:
            channel_id = site_id if site_id not in used_ids else f"{site_id}.{channel['name']}"
        used_ids.add(channel_id)
        name = meta.get("name") or channel["name"]
        node = ET.SubElement(root, "channel", id=channel_id)
        display = ET.SubElement(node, "display-name", lang="tr")
        display.text = name
        seen_starts: set[str] = set()
        for programme in sorted(programmes, key=lambda item: item["start"]):
            start = xmltv_stamp(programme["start"])
            if start in seen_starts:
                continue
            seen_starts.add(start)
            item = ET.SubElement(
                root,
                "programme",
                channel=channel_id,
                start=start,
                stop=xmltv_stamp(programme["stop"]),
            )
            title = ET.SubElement(item, "title", lang="tr")
            title.text = programme["title"]
            if programme["description"]:
                desc = ET.SubElement(item, "desc", lang="tr")
                desc.text = programme["description"]
            for category in programme["categories"]:
                node_category = ET.SubElement(item, "category", lang="tr")
                node_category.text = category
            programme_count += 1
    if programme_count == 0:
        raise GrabError("no programmes")
    normalize_channels_in_tree(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return len(root.findall("channel")), programme_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", choices=("dsmart", "turksat", "tvplus"), required=True)
    parser.add_argument("--channels", type=Path, help="Optional upstream channels.xml for xmltv ids")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--today", help="Istanbul calendar day YYYY-MM-DD (default: now)")
    args = parser.parse_args()
    if args.days < 1:
        raise GrabError("--days must be >= 1")
    if args.today:
        today = datetime.strptime(args.today, "%Y-%m-%d").date()
    else:
        today = datetime.now(ISTANBUL).date()
    days = [today + timedelta(days=offset) for offset in range(args.days)]
    catalog = load_catalog(args.channels)
    if args.site == "dsmart":
        channels = dsmart_channels(days)
    elif args.site == "turksat":
        channels = turksat_channels(days)
    else:
        channels = tvplus_channels(catalog, days)
    channel_count, programme_count = write_guide(args.output, channels, catalog)
    print(f"Grabbed {args.site}: {channel_count} channels, {programme_count} programmes -> {args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (GrabError, OSError, ET.ParseError, ValueError) as exc:
        print(f"Turkish public grab failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
