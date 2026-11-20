#!/usr/bin/env python3
"""Turkish alias builder and AquaPlay / IPTVnator coverage report.

Reads a sanitized local catalog JSON. It does not open the IPTVnator database.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from es_xtream_policy import is_forbidden_channel_id  # noqa: E402
from xmltv_channel import channel_children_ordered  # noqa: E402
from xtream_matching import valid_panel_epg_id  # noqa: E402


def _load_tr_epg():
    spec = importlib.util.spec_from_file_location("tr_epg", _SCRIPT_DIR / "tr-epg.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tr_epg = _load_tr_epg()
NUMERIC_ID_RE = re.compile(r"^\d+$")
NULLISH = {"", "null", "none", "undefined"}
VOD_PREFIXES = (
    "redbox",
    "sinevizyon",
    "multivizyon",
    "enovizyon",
    "bossmovies",
    "moviesmart",
    "dizismart",
    "sineanimasyon",
)


def match_key_ap(value: str) -> str:
    text = tr_epg.fold_letters(value or "")
    text = re.sub(r"\(.*?\)", " ", text)
    text = re.sub(r"\[.*?\]", " ", text)
    text = re.sub(r"\b(hd|fhd|uhd|4k|sd|hevc|h265|raw|backup|vip)\b", " ", text)
    text = re.sub(r"[\s\-_.,:;/\\()[\]{}'\"!?&+*#@|~`^%$]+", "", text)
    return "" if len(text) < 3 else text


def load_streams(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "streams" in data:
        data = data["streams"]
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a JSON array")
    streams = []
    for row in data:
        if not isinstance(row, dict):
            continue
        allowed = {"name", "epg_id", "xtream_id", "category"}
        if any(key not in allowed for key in row):
            raise ValueError(f"{path}: catalog rows may only contain name, epg_id, xtream_id and category")
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        epg_id = row.get("epg_id")
        epg_id = "" if epg_id is None else str(epg_id).strip()
        if epg_id.casefold() in NULLISH:
            epg_id = ""
        streams.append(
            {
                "name": name,
                "epg_id": epg_id,
                "xtream_id": str(row.get("xtream_id") or "").strip(),
                "category": str(row.get("category") or "").strip(),
            }
        )
    return streams


def programmed_channels(root: ET.Element) -> dict[str, list[str]]:
    programmed = {
        programme.get("channel")
        for programme in root.findall("programme")
        if (programme.findtext("title") or "").strip() and programme.get("channel")
    }
    channels: dict[str, list[str]] = {}
    for channel in root.findall("channel"):
        channel_id = channel.get("id") or ""
        if channel_id not in programmed:
            continue
        names = [
            (node.text or "").strip()
            for node in channel.findall("display-name")
            if (node.text or "").strip()
        ]
        if names:
            channels[channel_id] = names
    return channels


def signal_id(channel_id: str, clones: dict[str, str] | None = None) -> str:
    return (clones or {}).get(channel_id, channel_id)


def channel_for_stream(
    stream_name: str,
    channels: dict[str, list[str]],
    clones: dict[str, str] | None = None,
) -> str | None:
    key = tr_epg.identity_key(stream_name)
    if not key[0]:
        return None
    matches = {
        signal_id(channel_id, clones)
        for channel_id, names in channels.items()
        if tr_epg.identity_key(names[0]) == key
    }
    if len(matches) == 1:
        return next(iter(matches))
    return None


def build_alias_maps(
    root: ET.Element,
    streams: list[dict],
    occupied_ids: set[str] | None = None,
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Exact Xtream titles, plus clones of panel ids that name one station only."""
    occupied_ids = occupied_ids or set()
    channels = programmed_channels(root)
    guide_ids = {channel.get("id") or "" for channel in root.findall("channel")}
    first_owner = {names[0]: channel_id for channel_id, names in channels.items()}
    aliases: dict[str, list[str]] = defaultdict(list)
    seen_names: dict[str, str] = {}
    for stream in streams:
        if tr_epg.is_separator(stream["name"]):
            continue
        channel_id = channel_for_stream(stream["name"], channels)
        if not channel_id:
            continue
        title = stream["name"]
        owner = first_owner.get(title)
        if owner and owner != channel_id:
            continue
        if seen_names.get(title, channel_id) != channel_id:
            continue
        seen_names[title] = channel_id
        if title not in aliases[channel_id] and title != channels[channel_id][0]:
            aliases[channel_id].append(title)
    alias_map = {
        channel_id: sorted(names, key=str.casefold)
        for channel_id, names in sorted(aliases.items())
        if names
    }

    by_epg: dict[str, list[dict]] = defaultdict(list)
    for stream in streams:
        epg_id = (stream.get("epg_id") or "").strip()
        if epg_id:
            by_epg[epg_id].append(stream)
    clones: dict[str, str] = {}
    for epg_id, group in by_epg.items():
        if not valid_panel_epg_id(epg_id) or NUMERIC_ID_RE.fullmatch(epg_id):
            continue
        if tr_epg.is_separator(group[0]["name"]):
            continue
        stations = {tr_epg.station_key(stream["name"]) for stream in group}
        shifts = {1 if tr_epg.is_timeshift(stream["name"]) else 0 for stream in group}
        if len(stations) != 1 or len(shifts) != 1 or "" in stations:
            continue
        station = next(iter(stations))
        if not tr_epg.tokens_match(epg_id, station):
            continue
        targets = []
        for channel_id, names in channels.items():
            if tr_epg.identity_key(names[0]) == (station, next(iter(shifts))):
                targets.append(channel_id)
        if len(targets) != 1:
            continue
        target = targets[0]
        if epg_id == target or epg_id in occupied_ids or epg_id in guide_ids:
            continue
        clones[epg_id] = target
    return alias_map, dict(sorted(clones.items()))


def acceptable_guide_id(channel_id: str) -> bool:
    """Published Turkish ids, or a panel clone that does not carry another country's feed."""
    if tr_epg.is_published_id(channel_id):
        return True
    if (
        not channel_id
        or channel_id.isdigit()
        or "@" in channel_id
        or not tr_epg.ID_RE.fullmatch(channel_id)
    ):
        return False
    return not is_forbidden_channel_id(channel_id)


def structural_problems(root: ET.Element) -> list[str]:
    problems = []
    channel_ids = [channel.get("id") for channel in root.findall("channel")]
    if any(not channel_id for channel_id in channel_ids) or len(channel_ids) != len(set(channel_ids)):
        problems.append("duplicate or empty channel ids")
    known = set(channel_ids)
    for programme in root.findall("programme"):
        if programme.get("channel") not in known:
            problems.append("orphan programme")
            break
        if not programme.get("start") or not programme.get("stop"):
            problems.append("programme without start or stop")
            break
    for channel in root.findall("channel"):
        if not channel_children_ordered(channel):
            problems.append(f"DTD order {channel.get('id')}")
            break
        channel_id = channel.get("id") or ""
        if not acceptable_guide_id(channel_id):
            problems.append(f"unsafe channel id {channel_id}")
            break
    return problems


def content_group(name: str) -> str:
    if tr_epg.is_separator(name):
        return "separador"
    key = tr_epg.station_key(name)
    if key.startswith(VOD_PREFIXES) or key.startswith("redbox"):
        return "vod"
    if any(token in key for token in ("sinema", "movie", "filmbox", "beinmovies", "dizismart")):
        return "cine"
    if any(
        token in key
        for token in ("spor", "sport", "eurosport", "ssport", "fightbox", "nbatv", "exxen")
    ) or key.startswith("bein"):
        return "deportes"
    if any(token in key for token in ("haber", "news", "ntv", "cnn", "bloomberg", "haberturk")):
        return "noticias"
    if any(token in key for token in ("cocuk", "minika", "cartoon", "nick", "disney", "baby", "cbeebies")):
        return "infantil"
    if any(token in key for token in ("muzik", "kral", "powertv", "dreamturk", "numberone")):
        return "musica"
    if any(
        token in key
        for token in ("belgesel", "discovery", "nationalgeographic", "natgeo", "history", "documentary")
    ):
        return "documental"
    return "generalista"


def uncover_reason(name: str) -> str:
    if tr_epg.is_separator(name):
        return "Separador de categoría dentro de la lista, no es un canal"
    key = tr_epg.station_key(name)
    if key.startswith(VOD_PREFIXES):
        return "Vídeo bajo demanda del panel; ninguna guía lineal pública lo publica"
    if "tivibuspor" in key:
        return (
            "Tivibu Spor no está en Digiturk, D-Smart, TV+, Türksat ni EPGShare TR1; "
            "tivibu.com.tr exige un token de abonado"
        )
    if key.startswith("exxensport"):
        return "Exxen Sport no aparece en las parrillas públicas consultadas"
    return "Ninguna fuente pública verificada publica esta emisora con el mismo nombre"


def coverage_report(
    root: ET.Element,
    streams: list[dict],
    clones: dict[str, str] | None = None,
) -> dict[str, object]:
    clones = clones or {}
    channels = programmed_channels(root)
    channel_ids = set(channels)
    covered_rows = []
    uncovered_rows = []
    for stream in streams:
        channel_id = None if tr_epg.is_separator(stream["name"]) else channel_for_stream(
            stream["name"], channels, clones
        )
        group = content_group(stream["name"])
        row = {**stream, "group": group, "channel_id": channel_id or ""}
        if channel_id:
            covered_rows.append(row)
        else:
            row["reason"] = uncover_reason(stream["name"])
            uncovered_rows.append(row)
    buckets: dict[str, set[str]] = defaultdict(set)
    for channel_id, names in channels.items():
        for name in names:
            key = match_key_ap(name)
            if key:
                buckets[key].add(signal_id(channel_id, clones))
    aqua_exact = aqua_ambiguous = aqua_miss = 0
    for stream in streams:
        if tr_epg.is_separator(stream["name"]):
            continue
        key = match_key_ap(stream["name"])
        hits = buckets.get(key, set()) if key else set()
        if len(hits) == 1:
            aqua_exact += 1
        elif len(hits) > 1:
            aqua_ambiguous += 1
        else:
            aqua_miss += 1
    by_group: dict[str, dict[str, int]] = {}
    for row in covered_rows + uncovered_rows:
        bucket = by_group.setdefault(row["group"], {"streams": 0, "covered": 0})
        bucket["streams"] += 1
        if row.get("channel_id"):
            bucket["covered"] += 1
    real_streams = [stream for stream in streams if not tr_epg.is_separator(stream["name"])]
    categories = sorted({stream["category"] for stream in streams if stream.get("category")})
    return {
        "streams": len(streams),
        "real_channels": len(real_streams),
        "separators": len(streams) - len(real_streams),
        "categories": categories,
        "covered": len(covered_rows),
        "uncovered": len(uncovered_rows),
        "uncovered_rows": [
            {"name": row["name"], "xtream_id": row["xtream_id"], "epg_id": row["epg_id"], "reason": row["reason"]}
            for row in uncovered_rows
        ],
        "by_group": by_group,
        "iptv_exact_id": sum(1 for row in covered_rows if row["epg_id"] and row["epg_id"] in channel_ids),
        "clone_resolved": sum(1 for row in covered_rows if row["epg_id"] and clones.get(row["epg_id"])),
        "aquaplay_exact": aqua_exact,
        "aquaplay_ambiguous": aqua_ambiguous,
        "aquaplay_miss": aqua_miss,
        "channels": len(channel_ids),
        "programmes": len(root.findall("programme")),
        "structural_problems": structural_problems(root),
    }


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    aliases = sub.add_parser("aliases")
    aliases.add_argument("--guide", type=Path, required=True)
    aliases.add_argument("--catalog", type=Path, required=True)
    aliases.add_argument("--aliases-out", type=Path, required=True)
    aliases.add_argument("--xtream-out", type=Path, required=True)
    aliases.add_argument("--occupied-guide", action="append", type=Path, default=[])
    report = sub.add_parser("report")
    report.add_argument("--guide", type=Path, required=True)
    report.add_argument("--catalog", type=Path, required=True)
    report.add_argument("--xtream-aliases", type=Path)
    report.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = ET.parse(args.guide).getroot()
    streams = load_streams(args.catalog)
    if args.command == "aliases":
        occupied: set[str] = set()
        for path in args.occupied_guide:
            if path.is_file() and path.stat().st_size:
                guide = ET.parse(path).getroot()
                occupied.update(channel.get("id") or "" for channel in guide.findall("channel"))
        occupied.discard("")
        alias_map, clones = build_alias_maps(root, streams, occupied)
        write_json(args.aliases_out, alias_map)
        write_json(args.xtream_out, clones)
        print(f"Display aliases: {len(alias_map)} channels; Xtream clones: {len(clones)}")
        return 0
    clones = {}
    if args.xtream_aliases and args.xtream_aliases.is_file():
        clones = json.loads(args.xtream_aliases.read_text(encoding="utf-8"))
    summary = coverage_report(root, streams, clones)
    printable = {key: value for key, value in summary.items() if key != "uncovered_rows"}
    print(json.dumps(printable, ensure_ascii=False, indent=2))
    if args.output:
        write_json(args.output, summary)
    return 1 if summary["structural_problems"] else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ET.ParseError, ValueError, json.JSONDecodeError) as exc:
        print(f"Turkish catalog match failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
