"""Xtream/XMLTV policy: ES stable ids, global denied clones, curated display aliases."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "epg" / "es-xtream-policy.json"
GLOBAL_POLICY_PATH = ROOT / "epg" / "global-xtream-policy.json"
ID_RE = re.compile(r"^[^\s<>\"']+$")
FORBIDDEN_ALIAS_TOKENS = frozenset({"", "null", "none", "undefined"})
NUMERIC_ID_RE = re.compile(r"^\d+$")
PROFILE_TO_POLICY_KEY = {
    "es": None,
    "fr": "fr",
    "pt": "pt",
    "arabic": "arabic",
    "gb": None,
    "nl": "nl",
    "it": None,
    "de": None,
    "tr": None,
    "be": None,
    "ca": None,
    "af": None,
}


@lru_cache(maxsize=1)
def load_es_xtream_policy() -> dict:
    if not POLICY_PATH.is_file():
        return {"channel_renames": {}, "denied_xtream_clone_ids": []}
    data = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("es-xtream-policy.json must be an object")
    return data


def channel_renames() -> dict[str, str]:
    raw = load_es_xtream_policy().get("channel_renames") or {}
    return {str(k): str(v) for k, v in raw.items()}


@lru_cache(maxsize=1)
def load_global_xtream_policy() -> dict:
    if not GLOBAL_POLICY_PATH.is_file():
        return {}
    data = json.loads(GLOBAL_POLICY_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("global-xtream-policy.json must be an object")
    return data


def denied_xtream_clone_ids() -> frozenset[str]:
    raw = load_es_xtream_policy().get("denied_xtream_clone_ids") or []
    global_raw = load_global_xtream_policy().get("global_denied_xtream_clone_ids") or []
    return frozenset(str(x) for x in raw) | frozenset(str(x) for x in global_raw)


def global_denied_xtream_clone_ids() -> frozenset[str]:
    return denied_xtream_clone_ids()


def is_forbidden_alias_token(value: str | None) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    if not text or text.casefold() in FORBIDDEN_ALIAS_TOKENS or text.upper() == "NULL":
        return True
    return False


def is_forbidden_channel_id(channel_id: str | None) -> bool:
    if is_forbidden_alias_token(channel_id):
        return True
    if not channel_id or not ID_RE.fullmatch(channel_id.strip()):
        return True
    return False


def sanitize_display_aliases(aliases: dict[str, list[str]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for channel_id, names in aliases.items():
        if is_forbidden_channel_id(channel_id):
            continue
        cleaned: list[str] = []
        for name in names:
            name = (name or "").strip()
            if is_forbidden_alias_token(name):
                continue
            if name not in cleaned:
                cleaned.append(name)
        if cleaned:
            out[channel_id.strip()] = cleaned
    return out


def curated_display_aliases(profile: str) -> dict[str, list[str]]:
    key = PROFILE_TO_POLICY_KEY.get(profile)
    if not key:
        return {}
    raw = load_global_xtream_policy().get("curated_display_aliases") or {}
    block = raw.get(key) or {}
    if not isinstance(block, dict):
        return {}
    return sanitize_display_aliases({str(k): list(v) for k, v in block.items()})


def merge_curated_display_aliases(aliases: dict[str, list[str]], profile: str) -> dict[str, list[str]]:
    merged = sanitize_display_aliases(aliases)
    for channel_id, extra in curated_display_aliases(profile).items():
        bucket = merged.setdefault(channel_id, [])
        for name in extra:
            if name not in bucket:
                bucket.append(name)
    return merged


def filter_numeric_stream_clones(mapping: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in mapping.items() if not NUMERIC_ID_RE.fullmatch(k.strip())}


@lru_cache(maxsize=1)
def intentional_numeric_xtream_clone_ids() -> frozenset[str]:
    """Numeric IDs configured as Xtream clone keys/values (stream clones), not scrape-native ids."""
    out: set[str] = set()
    epg_dir = ROOT / "epg"
    for path in sorted(epg_dir.glob("xtream-aliases*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        for key, value in data.items():
            key_s = str(key).strip()
            val_s = str(value).strip()
            if NUMERIC_ID_RE.fullmatch(key_s):
                out.add(key_s)
            if NUMERIC_ID_RE.fullmatch(val_s):
                out.add(val_s)
    return frozenset(out)


def policy_exempt_programmed_loss(channel_id: str) -> bool:
    """Losses expected after global policy (configured numeric Xtream clones, denied ids)."""
    if not channel_id:
        return False
    if channel_id in denied_xtream_clone_ids():
        return True
    stripped = channel_id.strip()
    return NUMERIC_ID_RE.fullmatch(stripped) is not None and stripped in intentional_numeric_xtream_clone_ids()


def split_policy_exempt_losses(lost_ids: set[str]) -> tuple[set[str], set[str]]:
    exempt = {cid for cid in lost_ids if policy_exempt_programmed_loss(cid)}
    return exempt, lost_ids - exempt


def remap_alias_keys(aliases: dict[str, list[str]], renames: dict[str, str]) -> dict[str, list[str]]:
    if not renames:
        return aliases
    out: dict[str, list[str]] = {}
    for cid, names in aliases.items():
        target = renames.get(cid, cid)
        bucket = out.setdefault(target, [])
        for name in names:
            if name not in bucket:
                bucket.append(name)
    return out


def apply_channel_id_renames(root, renames: dict[str, str]) -> None:
    if not renames:
        return
    for channel in root.findall("channel"):
        cid = channel.get("id") or ""
        if cid in renames:
            channel.set("id", renames[cid])
    for programme in root.findall("programme"):
        ch = programme.get("channel") or ""
        if ch in renames:
            programme.set("channel", renames[ch])


def purge_denied_clone_channels(root, denied: frozenset[str]) -> None:
    if not denied:
        return
    for channel in list(root.findall("channel")):
        if (channel.get("id") or "") in denied:
            root.remove(channel)
    for programme in list(root.findall("programme")):
        if (programme.get("channel") or "") in denied:
            root.remove(programme)


def filter_denied_xtream_aliases(mapping: dict[str, str], denied: frozenset[str]) -> dict[str, str]:
    if not denied:
        cleaned = dict(mapping)
    else:
        cleaned = {k: v for k, v in mapping.items() if k not in denied}
    return filter_numeric_stream_clones(cleaned)