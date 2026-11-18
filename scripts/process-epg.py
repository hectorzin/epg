#!/usr/bin/env python3
"""Safely merge display-name and Xtream ID aliases into an XMLTV document."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from xtream_matching import channel_stem  # noqa: E402

MIN_CHANNELS = 100
MIN_PROGRAMMES = 1000
MAX_DROP_RATIO = 0.60
MAX_DOWNLOAD_BYTES = 80 * 1024 * 1024
EXPECTED_ALIAS_COUNT = 66
MIN_ALIAS_IDS = 60
ID_RE = re.compile(r"^[^\s<>\"']+$")
XTREAM_NULLS = {"null", "none", "undefined"}
XTREAM_CATALOG_FIELDS = {"xtream_id", "name", "epg_id", "category"}
COUNTRY_CODES = ("AF", "AR", "BE", "CA", "DE", "DZ", "ES", "FR", "GB", "IT", "MA", "NL", "PR", "PT", "TN", "TR", "UK")
COUNTRY_PREFIX_RE = re.compile(
    rf"^\s*(?:\[({'|'.join(COUNTRY_CODES)})\]\s*|({'|'.join(COUNTRY_CODES)})\s*[:|/_-]\s*)",
    re.IGNORECASE,
)
TECHNICAL_SUFFIX_RE = re.compile(
    r"(?:[\s._()\[\]-]*)(?:FULL[\s._-]*HD|FHD|UHD|HD|SD|4K|HEVC|H265|H264)[\s)\]]*$",
    re.IGNORECASE,
)
SUSPICIOUS_XTREAM_ID_PREFIXES = ("dev.series.title.",)


class EpgError(Exception):
    pass


def parse_xml(data: bytes, label: str) -> ET.Element:
    if not data or len(data) > MAX_DOWNLOAD_BYTES:
        raise EpgError(f"{label}: empty document or size limit exceeded")
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise EpgError(f"{label}: DTD and entity declarations are not accepted")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise EpgError(f"{label}: malformed or truncated XML ({exc})") from exc
    if root.tag != "tv":
        raise EpgError(f"{label}: root element must be <tv>")
    return root


def validate_tree(root: ET.Element, label: str) -> tuple[dict[str, ET.Element], int]:
    channels: dict[str, ET.Element] = {}
    for channel in root.findall("channel"):
        channel_id = channel.get("id")
        if not channel_id or not ID_RE.fullmatch(channel_id) or channel_id in channels:
            raise EpgError(f"{label}: missing, invalid, or duplicate channel id")
        channels[channel_id] = channel
    programmes = root.findall("programme")
    for programme in programmes:
        if not programme.get("start") or not programme.get("stop") or not programme.get("channel"):
            raise EpgError(f"{label}: programme is missing start, stop, or channel")
        if programme.get("channel") not in channels:
            raise EpgError(f"{label}: programme references an unknown channel")
    return channels, len(programmes)


def load_aliases(path: Path, *, profile: str = "es") -> dict[str, list[str]]:
    try:
        aliases = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EpgError(f"could not read aliases JSON: {exc}") from exc
    if not isinstance(aliases, dict):
        raise EpgError("aliases JSON must be an object of channel ID to display names")
    if profile == "es":
        if len(aliases) < MIN_ALIAS_IDS:
            raise EpgError(f"aliases JSON must contain at least {MIN_ALIAS_IDS} channel IDs")
    elif not aliases:
        raise EpgError("regional aliases JSON is empty")
    for channel_id, names in aliases.items():
        if not isinstance(channel_id, str) or not ID_RE.fullmatch(channel_id):
            raise EpgError("aliases JSON contains an invalid channel ID")
        if not isinstance(names, list) or not names or any(not isinstance(n, str) or not n.strip() for n in names):
            raise EpgError(f"aliases JSON has invalid display names for channel {channel_id}")
        if len(set(names)) != len(names):
            raise EpgError(f"aliases JSON contains duplicate names for channel {channel_id}")
    alias_count = sum(map(len, aliases.values()))
    if profile == "es" and alias_count < EXPECTED_ALIAS_COUNT:
        raise EpgError(f"aliases JSON must contain at least the expected {EXPECTED_ALIAS_COUNT} custom display names")
    return aliases


def _json_object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise EpgError(f"Xtream aliases JSON contains duplicate ID {key!r}")
        result[key] = value
    return result


def normalize_xtream_clone_map(mapping: dict[str, str]) -> dict[str, str]:
    """Flatten clone chains so every alias points at a root channel, never another clone."""
    normalized: dict[str, str] = {}
    for alias_id, original_id in mapping.items():
        if alias_id == original_id:
            continue
        target = original_id
        visited = {alias_id}
        while target in mapping:
            if target in visited:
                raise EpgError(f"Xtream alias chain contains a cycle at {alias_id}")
            visited.add(target)
            target = mapping[target]
        normalized[alias_id] = target
    clone_ids = set(normalized)
    for alias_id, target in normalized.items():
        if target in clone_ids and target != alias_id:
            raise EpgError(
                f"Xtream alias {alias_id} references clone channel {target}; originals must not be clone IDs"
            )
    return normalized


def load_xtream_aliases(path: Path) -> dict[str, str]:
    """Load Xtream ID -> original XMLTV ID pairs, rejecting ambiguous entries."""
    try:
        aliases = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_json_object_without_duplicate_keys
        )
    except (OSError, json.JSONDecodeError, EpgError) as exc:
        raise EpgError(f"could not read Xtream aliases JSON: {exc}") from exc
    if not isinstance(aliases, dict):
        raise EpgError("Xtream aliases JSON must be an object of alias ID to original ID")
    for alias_id, original_id in aliases.items():
        if (
            not isinstance(alias_id, str)
            or not alias_id.strip()
            or alias_id.strip().casefold() in XTREAM_NULLS
            or not ID_RE.fullmatch(alias_id)
        ):
            raise EpgError("Xtream aliases JSON contains an empty, NULL, or invalid alias ID")
        if not isinstance(original_id, str) or not original_id.strip() or not ID_RE.fullmatch(original_id):
            raise EpgError(f"Xtream aliases JSON has an invalid original ID for {alias_id}")
    return normalize_xtream_clone_map(aliases)


def load_xtream_catalog(path: Path) -> list[dict[str, object]]:
    """Load the sanitized Xtream export, rejecting fields that could leak secrets."""
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EpgError(f"could not read Xtream catalog JSON: {exc}") from exc
    if not isinstance(catalog, list):
        raise EpgError("Xtream catalog JSON must be a list of channel records")

    seen_xtream_ids: set[str] = set()
    for index, channel in enumerate(catalog):
        if not isinstance(channel, dict) or set(channel) != XTREAM_CATALOG_FIELDS:
            raise EpgError(f"Xtream catalog record {index} must contain only the four approved fields")
        raw_xtream_id = channel["xtream_id"]
        if isinstance(raw_xtream_id, bool) or not isinstance(raw_xtream_id, (int, str)):
            raise EpgError(f"Xtream catalog record {index} has an invalid Xtream ID")
        xtream_id = str(raw_xtream_id).strip()
        if not xtream_id or xtream_id.casefold() in XTREAM_NULLS or not ID_RE.fullmatch(xtream_id):
            raise EpgError(f"Xtream catalog record {index} has an invalid Xtream ID")
        if xtream_id in seen_xtream_ids:
            raise EpgError(f"Xtream catalog contains duplicate Xtream ID {xtream_id}")
        seen_xtream_ids.add(xtream_id)
        if not isinstance(channel["name"], str) or not isinstance(channel["category"], str):
            raise EpgError(f"Xtream catalog record {index} has an invalid name or category")
        if channel["epg_id"] is not None and not isinstance(channel["epg_id"], str):
            raise EpgError(f"Xtream catalog record {index} has an invalid EPG ID")
    return catalog


def channel_countries(name: str, category: str = "") -> set[str]:
    countries: set[str] = set()
    for value in (category, name):
        match = COUNTRY_PREFIX_RE.match(value or "")
        if match:
            countries.add((match.group(1) or match.group(2)).upper())
    return countries


def programmed_channels(root: ET.Element) -> set[str]:
    channel_ids = {c.get("id") for c in root.findall("channel") if c.get("id")}
    return {
        p.get("channel")
        for p in root.findall("programme")
        if (p.findtext("title") or "").strip() and p.get("channel") in channel_ids
    }


def pick_canonical_original(original_id: str, candidates: set[str]) -> str | None:
    """Pick one guide channel when a configured original is missing but stem matches."""
    if original_id in candidates:
        return original_id
    stems = {c for c in candidates if channel_stem(c) == channel_stem(original_id)}
    if not stems:
        return None
    upper = original_id.upper()
    if "@HD" in upper or "@UKHD" in upper or "@FHD" in upper:
        hd = {c for c in stems if re.search(r"@(?:UK)?HD\b", c.upper())}
        if len(hd) == 1:
            return next(iter(hd))
    if upper.endswith("@SD"):
        sd = {c for c in stems if c.upper().endswith("@SD")}
        if len(sd) == 1:
            return next(iter(sd))
    if len(stems) == 1:
        return next(iter(stems))
    return None


def filter_configured_xtream_aliases(
    configured: dict[str, str],
    channel_ids: set[str],
    original_pool: set[str],
    *,
    tolerate_missing_original: bool,
) -> tuple[dict[str, str], list[str]]:
    """Return clones applicable to this guide; optionally skip absent originals (regional runs)."""
    applicable: dict[str, str] = {}
    skipped: list[str] = []
    for xtream_id, original_id in configured.items():
        target = pick_canonical_original(original_id, original_pool)
        if target is None:
            if tolerate_missing_original:
                skipped.append(xtream_id)
                continue
            raise EpgError(
                f"configured Xtream alias {xtream_id} references unknown original channel {original_id}"
            )
        if xtream_id == target:
            continue
        if xtream_id in channel_ids and target not in channel_ids:
            raise EpgError(f"configured Xtream alias {xtream_id} collides with an original channel ID")
        applicable[xtream_id] = target
    return applicable, skipped


def normalize_channel_name(name: str) -> str:
    """Normalize presentation details while preserving channel numbers."""
    value = unicodedata.normalize("NFKD", name or "")
    value = "".join(character for character in value if not unicodedata.combining(character)).casefold().strip()
    while True:
        without_country = COUNTRY_PREFIX_RE.sub("", value).strip()
        if without_country == value:
            break
        value = without_country
    while True:
        without_suffix = TECHNICAL_SUFFIX_RE.sub("", value).strip()
        if without_suffix == value:
            break
        value = without_suffix
    return "".join(character for character in value if character.isalnum())


def resolve_xtream_catalog(
    root: ET.Element,
    catalog: list[dict[str, object]],
    display_aliases: dict[str, list[str]],
    configured_aliases: dict[str, str],
    *,
    auto_region: str = "ES",
    tolerate_missing_configured: bool = False,
) -> tuple[dict[str, str], dict[str, int]]:
    """Resolve safe catalog matches to original guide IDs and summarize coverage."""
    channels, _ = validate_tree(root, "source")
    names_to_ids: dict[str, set[str]] = {}
    for channel_id, channel in channels.items():
        names = [node.text or "" for node in channel.findall("display-name")]
        names.extend(display_aliases.get(channel_id, []))
        for name in names:
            normalized = normalize_channel_name(name)
            if normalized:
                names_to_ids.setdefault(normalized, set()).add(channel_id)

    groups: dict[str, list[dict[str, object]]] = {}
    pending_channels: list[dict[str, object]] = []
    for channel in catalog:
        epg_id = channel["epg_id"]
        if not isinstance(epg_id, str) or not epg_id.strip() or epg_id.strip().casefold() in XTREAM_NULLS:
            pending_channels.append(channel)
            continue
        if epg_id != epg_id.strip() or not ID_RE.fullmatch(epg_id):
            pending_channels.append(channel)
            continue
        groups.setdefault(epg_id, []).append(channel)

    programmed = programmed_channels(root)
    resolved, skipped_configured = filter_configured_xtream_aliases(
        configured_aliases,
        set(channels),
        set(channels),
        tolerate_missing_original=tolerate_missing_configured,
    )

    summary = {
        "catalog_channels": len(catalog),
        "covered_channels": 0,
        "configured_alias_channels": 0,
        "identifier_match_channels": 0,
        "name_match_channels": 0,
        "new_aliases": 0,
        "new_alias_channels": 0,
        "ambiguous_epg_ids": 0,
        "ambiguous_channels": 0,
        "uncovered_epg_ids": 0,
        "uncovered_channels": 0,
        "pending_no_epg_id": len(pending_channels),
        "pending_name_matches": 0,
        "region_mismatches": 0,
        "suspicious_ids": 0,
        "skipped_configured_xtream": len(skipped_configured),
    }

    # Existing curated mappings remain authoritative only when all catalog uses
    # consistently support the same destination name.
    for xtream_id, original_id in configured_aliases.items():
        rows = groups.get(xtream_id)
        if not rows:
            continue
        name_keys = {normalize_channel_name(str(row["name"])) for row in rows}
        regions = set().union(
            *(channel_countries(str(row["name"]), str(row["category"])) for row in rows)
        )
        name_matches = names_to_ids.get(next(iter(name_keys)), set()) if len(name_keys) == 1 else set()
        if (
            len(name_keys) != 1
            or "" in name_keys
            or len(regions) > 1
            or (regions and regions != {auto_region})
            or name_matches != {original_id}
        ):
            raise EpgError(f"configured Xtream alias {xtream_id} conflicts with its catalog channel names")
        summary["configured_alias_channels"] += len(rows)
        summary["covered_channels"] += len(rows)

    for epg_id, rows in groups.items():
        if epg_id in configured_aliases:
            continue
        name_keys = {normalize_channel_name(str(row["name"])) for row in rows}
        regions = set().union(
            *(channel_countries(str(row["name"]), str(row["category"])) for row in rows)
        )
        if len(name_keys) != 1 or "" in name_keys or len(regions) > 1:
            summary["ambiguous_epg_ids"] += 1
            summary["ambiguous_channels"] += len(rows)
            continue

        name_key = next(iter(name_keys))
        matches = names_to_ids.get(name_key, set())
        if epg_id in channels:
            if matches == {epg_id}:
                resolved[epg_id] = epg_id
                summary["identifier_match_channels"] += len(rows)
                summary["covered_channels"] += len(rows)
            else:
                summary["ambiguous_epg_ids"] += 1
                summary["ambiguous_channels"] += len(rows)
            continue

        if len(matches) > 1:
            summary["ambiguous_epg_ids"] += 1
            summary["ambiguous_channels"] += len(rows)
            continue
        if len(matches) == 1:
            region = next(iter(regions)) if regions else None
            if region and region != auto_region:
                summary["uncovered_epg_ids"] += 1
                summary["uncovered_channels"] += len(rows)
                summary["region_mismatches"] += 1
                continue
            if epg_id.casefold().startswith(SUSPICIOUS_XTREAM_ID_PREFIXES):
                summary["uncovered_epg_ids"] += 1
                summary["uncovered_channels"] += len(rows)
                summary["suspicious_ids"] += 1
                continue
            original_id = next(iter(matches))
            resolved[epg_id] = original_id
            summary["name_match_channels"] += len(rows)
            summary["new_alias_channels"] += len(rows)
            summary["new_aliases"] += 1
            summary["covered_channels"] += len(rows)
            continue

        summary["uncovered_epg_ids"] += 1
        summary["uncovered_channels"] += len(rows)

    for channel in pending_channels:
        if normalize_channel_name(str(channel["name"])) in names_to_ids:
            summary["pending_name_matches"] += 1
    return resolved, summary


def _programme_with_channel(programme: ET.Element, channel_id: str) -> ET.Element:
    duplicate = copy.deepcopy(programme)
    duplicate.set("channel", channel_id)
    return duplicate


def _programme_fingerprint(programme: ET.Element) -> bytes:
    return ET.tostring(programme, encoding="utf-8")


def merge(
    source: bytes,
    aliases: dict[str, list[str]],
    baseline: bytes | None = None,
    xtream_aliases: dict[str, str] | None = None,
    *,
    min_channels: int = MIN_CHANNELS,
    min_programmes: int = MIN_PROGRAMMES,
    alias_mode: str = "strict",
) -> tuple[bytes, int, int]:
    root = parse_xml(source, "input XMLTV")
    xtream_aliases = xtream_aliases or {}
    # Recognize and remove exact aliases generated by an earlier run before
    # taking the original-programme baseline. A conflicting source channel is
    # rejected below unless its metadata and complete programme set match the
    # configured clone exactly.
    if xtream_aliases:
        initial_channels, _ = validate_tree(root, "input XMLTV")
        for xtream_id, original_id in xtream_aliases.items():
            if xtream_id == original_id:
                continue
            existing = initial_channels.get(xtream_id)
            if existing is None:
                continue
            if original_id not in initial_channels:
                if alias_mode in ("regional", "tolerant"):
                    continue
                raise EpgError(f"Xtream alias {xtream_id} references unknown original channel {original_id}")
            expected_channel = copy.deepcopy(initial_channels[original_id])
            expected_channel.set("id", xtream_id)
            expected_channel_bytes = ET.tostring(expected_channel, encoding="utf-8")
            if ET.tostring(existing, encoding="utf-8") != expected_channel_bytes:
                raise EpgError(f"Xtream alias {xtream_id} already belongs to a different channel")
            original_programmes = [p for p in root.findall("programme") if p.get("channel") == original_id]
            alias_programmes = [p for p in root.findall("programme") if p.get("channel") == xtream_id]
            expected = sorted(
                repr(_programme_fingerprint(_programme_with_channel(p, xtream_id)))
                for p in original_programmes
            )
            actual = sorted(repr(_programme_fingerprint(p)) for p in alias_programmes)
            if expected != actual:
                raise EpgError(f"Xtream alias {xtream_id} has ambiguous or different programme records")
            root.remove(existing)
            for programme in alias_programmes:
                root.remove(programme)
    channels, programme_count = validate_tree(root, "input XMLTV")
    if len(channels) < min_channels or programme_count < min_programmes:
        raise EpgError(
            f"input XMLTV: coverage below minimum ({len(channels)} channels, {programme_count} programmes)"
        )
    programme_fingerprint = [_programme_fingerprint(node) for node in root.findall("programme")]
    original_channels = set(channels)
    incoming_aliases = aliases
    remapped_aliases: dict[str, list[str]] = {}
    resolved_alias_keys: set[str] = set()
    for channel_id, names in incoming_aliases.items():
        target = channel_id if channel_id in channels else pick_canonical_original(channel_id, set(channels))
        if not target or target not in channels:
            continue
        resolved_alias_keys.add(channel_id)
        bucket = remapped_aliases.setdefault(target, [])
        for name in names:
            if name not in bucket:
                bucket.append(name)
    aliases = remapped_aliases
    missing = sorted(set(incoming_aliases) - resolved_alias_keys)
    if missing and alias_mode == "strict":
        raise EpgError("source is missing configured channel IDs: " + ", ".join(missing))
    if missing and alias_mode in ("regional", "tolerant"):
        aliases = {channel_id: names for channel_id, names in aliases.items() if channel_id in channels}
    tolerate_xtream = alias_mode in ("regional", "tolerant")
    programmed = {
        p.get("channel")
        for p in root.findall("programme")
        if (p.findtext("title") or "").strip()
    }
    xtream_aliases, _skipped = filter_configured_xtream_aliases(
        xtream_aliases or {},
        set(channels),
        {c for c in programmed if c in channels},
        tolerate_missing_original=tolerate_xtream,
    )
    alias_destinations: dict[str, str] = {}
    for xtream_id, original_id in xtream_aliases.items():
        if not isinstance(xtream_id, str) or not xtream_id.strip() or xtream_id.strip().casefold() in XTREAM_NULLS:
            raise EpgError("Xtream alias is empty or NULL")
        if not isinstance(original_id, str) or not original_id.strip():
            raise EpgError(f"Xtream alias {xtream_id} has no original channel")
        if xtream_id in alias_destinations and alias_destinations[xtream_id] != original_id:
            raise EpgError(f"Xtream alias {xtream_id} has multiple possible destinations")
        if original_id not in channels:
            if tolerate_xtream:
                continue
            raise EpgError(f"Xtream alias {xtream_id} references unknown original channel {original_id}")
        alias_destinations[xtream_id] = original_id
    if baseline:
        old_channels, old_programmes = validate_tree(parse_xml(baseline, "local baseline"), "local baseline")
        if len(old_channels) < MIN_CHANNELS or old_programmes < MIN_PROGRAMMES:
            raise EpgError("local baseline coverage is below the safety minimum")
        channel_floor = max(MIN_CHANNELS, int(len(old_channels) * (1 - MAX_DROP_RATIO)))
        programme_floor = max(MIN_PROGRAMMES, int(old_programmes * (1 - MAX_DROP_RATIO)))
        if len(channels) < channel_floor or programme_count < programme_floor:
            raise EpgError("coverage dropped more than the permitted 60% from the current local guide")

    aliases_complete = True
    for channel_id, names in aliases.items():
        channel = channels[channel_id]
        existing = {node.text for node in channel.findall("display-name")}
        if all(name in existing for name in names):
            continue
        aliases_complete = False
        for name in names:
            if name not in existing:
                ET.SubElement(channel, "display-name").text = name
                existing.add(name)

    # Add the intentional ID clones after display-name aliases so the cloned
    # channel retains all existing metadata and alias names.
    current_programmes = list(root.findall("programme"))
    programmes_by_channel: dict[str, list[ET.Element]] = {}
    for programme in current_programmes:
        programmes_by_channel.setdefault(programme.get("channel", ""), []).append(programme)
    for xtream_id, original_id in alias_destinations.items():
        if xtream_id == original_id:
            continue
        expected_channel = copy.deepcopy(channels[original_id])
        expected_channel.set("id", xtream_id)
        root.append(expected_channel)
        channels[xtream_id] = expected_channel
        for programme in programmes_by_channel.get(original_id, []):
            duplicate = _programme_with_channel(programme, xtream_id)
            root.append(duplicate)

    has_new_xtream_ids = any(xtream_id != original_id for xtream_id, original_id in alias_destinations.items())
    if aliases_complete and not has_new_xtream_ids:
        result = source
    else:
        result = ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"
    # Reparse the serialized form and verify the programme stream was preserved exactly.
    final_root = parse_xml(result, "merged output")
    final_channels, final_programmes = validate_tree(final_root, "merged output")
    final_fingerprint = [
        _programme_fingerprint(node)
        for node in final_root.findall("programme")
        if node.get("channel") in original_channels
    ]
    if len(final_fingerprint) != programme_count or final_fingerprint != programme_fingerprint:
        raise EpgError("programme records changed during serialization")
    for channel_id, names in aliases.items():
        actual = [node.text for node in final_channels[channel_id].findall("display-name")]
        if any(name not in actual for name in names):
            raise EpgError(f"alias verification failed for channel {channel_id}")
    for xtream_id, original_id in alias_destinations.items():
        if xtream_id not in final_channels:
            raise EpgError(f"Xtream channel verification failed for {xtream_id}")
        source_meta = copy.deepcopy(final_channels[original_id])
        source_meta.set("id", xtream_id)
        if ET.tostring(source_meta, encoding="utf-8") != ET.tostring(final_channels[xtream_id], encoding="utf-8"):
            raise EpgError(f"Xtream channel metadata changed for {xtream_id}")
        expected = sorted(
            _programme_fingerprint(_programme_with_channel(programme, xtream_id))
            for programme in final_root.findall(f"programme[@channel='{original_id}']")
        )
        actual = sorted(
            map(_programme_fingerprint, final_root.findall(f"programme[@channel='{xtream_id}']"))
        )
        if expected != actual:
            raise EpgError(f"Xtream programme verification failed for {xtream_id}")
    return result, len(original_channels), programme_count


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as output:
            temp_name = output.name
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--input", type=Path, required=True, help="Local XMLTV generated by this repository")
    parser.add_argument("--output", type=Path, required=True, help="Write the definitive XMLTV to a separate path")
    parser.add_argument("--baseline", type=Path, help="Optional local guide used for coverage-drop validation")
    parser.add_argument("--aliases", type=Path, default=root / "epg" / "aliases.json")
    parser.add_argument("--xtream-aliases", type=Path, default=root / "epg" / "xtream-aliases.json")
    parser.add_argument(
        "--profile",
        choices=("es", "fr", "arabic", "gb"),
        default="es",
        help="Alias validation profile (regional guides use relaxed display-name counts)",
    )
    parser.add_argument("--min-channels", type=int, default=MIN_CHANNELS)
    parser.add_argument("--min-programmes", type=int, default=MIN_PROGRAMMES)
    parser.add_argument(
        "--xtream-catalog",
        type=Path,
        help="Optional sanitized catalog supplied locally; catalog data is not bundled",
    )
    args = parser.parse_args()
    try:
        protected_paths = [args.input, args.aliases, args.xtream_aliases]
        if args.baseline:
            protected_paths.append(args.baseline)
        if args.xtream_catalog:
            protected_paths.append(args.xtream_catalog)
        if args.output.resolve() in {path.resolve() for path in protected_paths}:
            raise EpgError("output path must differ from the guide and configuration input files")
        profile = args.profile
        alias_profile = "es" if profile == "es" else "regional"
        alias_mode = "tolerant" if profile == "es" else "regional"
        aliases = load_aliases(args.aliases, profile=alias_profile)
        configured_xtream_aliases = (
            load_xtream_aliases(args.xtream_aliases) if args.xtream_aliases.is_file() else {}
        )
        xtream_catalog = load_xtream_catalog(args.xtream_catalog) if args.xtream_catalog else []
        source = args.input.read_bytes()
        baseline = args.baseline.read_bytes() if args.baseline else None
        source_root = parse_xml(source, "input XMLTV")
        auto_region = {"es": "ES", "fr": "FR", "arabic": "ARABIC", "gb": "GB"}[profile]
        tolerate_configured = profile != "es"
        xtream_aliases, xtream_summary = resolve_xtream_catalog(
            source_root,
            xtream_catalog,
            aliases,
            configured_xtream_aliases,
            auto_region=auto_region,
            tolerate_missing_configured=tolerate_configured,
        )
        result, channels, programmes = merge(
            source,
            aliases,
            baseline,
            xtream_aliases,
            min_channels=args.min_channels,
            min_programmes=args.min_programmes,
            alias_mode=alias_mode,
        )
        atomic_write(args.output, result)
        print(f"Wrote {args.output} ({channels} channels, {programmes} programmes, {len(aliases)} display alias IDs, {len(xtream_aliases)} Xtream IDs)")
        print(
            "Xtream catalog: "
            f"{xtream_summary['catalog_channels']} channels; "
            f"{xtream_summary['covered_channels']} covered "
            f"({xtream_summary['configured_alias_channels']} via existing aliases, "
            f"{xtream_summary['identifier_match_channels']} by identical ID, "
            f"{xtream_summary['name_match_channels']} by name); "
            f"{xtream_summary['new_aliases']} new aliases; "
            f"{xtream_summary['ambiguous_epg_ids']} ambiguous EPG IDs "
            f"({xtream_summary['ambiguous_channels']} channels); "
            f"{xtream_summary['uncovered_channels']} valid-ID channels without coverage "
            f"({xtream_summary['uncovered_epg_ids']} IDs, "
            f"{xtream_summary['region_mismatches']} regional, {xtream_summary['suspicious_ids']} suspicious); "
            f"{xtream_summary['pending_no_epg_id']} pending without a valid EPG ID "
            f"({xtream_summary['pending_name_matches']} name matches retained pending)."
        )
        return 0
    except (EpgError, OSError) as exc:
        print(f"EPG update failed: {exc}", file=sys.stderr)
        return 1


def normalize_for_compare(data: bytes) -> bytes:
    # Git on Windows may check out text with CRLF; compare XML semantics while
    # keeping the producer's bytes untouched when no alias update is needed.
    normalized = data.replace(b"\r\n", b"\n").rstrip(b"\n")
    return normalized.removeprefix(b"\xef\xbb\xbf")


if __name__ == "__main__":
    raise SystemExit(main())
