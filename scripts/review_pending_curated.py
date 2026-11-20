#!/usr/bin/env python3
"""Individual pending review against national + global XMLTV (curated, no re-grab)."""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from xmltv_gzip import parse_xmltv, published_global_guide  # noqa: E402
from xtream_matching import (  # noqa: E402
    channel_stem,
    disambiguate_by_quality,
    guide_core_key,
    normalize_channel_name,
    panel_core_key,
    valid_panel_epg_id,
)

FAKE_HD_CHARS = re.compile(r"[\u029c\u1d05\u1d2c\uff48\uff44]", re.IGNORECASE)
QUALITY_MARKER = re.compile(
    r"\b(4k|uhd|fhd|full\s*hd|hd|sd|hevc|h265|h264)\b",
    re.IGNORECASE,
)
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

REGION_GUIDES = {
    "fr": ROOT / "guide-fr.xml",
    "arabic": ROOT / "guide-arabic.xml",
}
ALIAS_FILES = {
    "fr": ROOT / "epg" / "aliases-fr.json",
    "arabic": ROOT / "epg" / "aliases-arabic.json",
}
PENDING_FILES = {
    "fr": ROOT / "epg" / "xtream-pending-fr.json",
    "arabic": ROOT / "epg" / "xtream-pending-arabic.json",
}


def strip_quality_tokens(text: str) -> str:
    text = FAKE_HD_CHARS.sub("", text)
    text = QUALITY_MARKER.sub("", text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip(" -_+|")


def norm_keys(text: str) -> set[str]:
    keys: set[str] = set()
    for candidate in (text, strip_quality_tokens(text)):
        key = normalize_channel_name(candidate)
        if key:
            keys.add(key)
        compact = normalize_channel_name(candidate.replace("+", " plus "))
        if compact:
            keys.add(compact)
    return keys


class EpgCatalog:
    def __init__(self, paths: list[Path]) -> None:
        self.channels: dict[str, dict] = {}
        self.programmed: set[str] = set()
        self.by_name: dict[str, set[str]] = defaultdict(set)
        self.by_stem: dict[str, set[str]] = defaultdict(set)
        self.by_panel_core: dict[str, set[str]] = defaultdict(set)
        self.sources: dict[str, set[str]] = defaultdict(set)

        for path in paths:
            if not path.is_file():
                continue
            root = parse_xmltv(path)
            label = path.name
            for channel in root.findall("channel"):
                cid = channel.get("id") or ""
                if not cid or cid in self.channels:
                    if cid:
                        self.sources[cid].add(label)
                    continue
                names = [
                    n.text.strip()
                    for n in channel.findall("display-name")
                    if (n.text or "").strip()
                ]
                self.channels[cid] = {"names": names, "icon": channel.find("icon")}
                self.sources[cid].add(label)
                self.by_stem[channel_stem(cid)].add(cid)
                self.by_panel_core[guide_core_key(cid)].add(cid)
                for name in names + [cid]:
                    for key in norm_keys(name):
                        self.by_name[key].add(cid)
            for programme in root.findall("programme"):
                if not (programme.findtext("title") or "").strip():
                    continue
                ch = programme.get("channel") or ""
                if ch:
                    self.programmed.add(ch)

    def allowed_ids(self, profile: str) -> set[str]:
        national = REGION_GUIDES[profile]
        if not national.is_file():
            return set(self.channels)
        root = ET.parse(national).getroot()
        return {c.get("id") for c in root.findall("channel") if c.get("id")}


# Individual decisions after inspecting panel IDs, brands and regional variants.
FR_CURATED_XTREAM: dict[str, tuple[str, str]] = {
    "965": ("CanalPlusKids.fr@SD", "Canal+ Kids; panel 01tv.fr is generic/wrong"),
    "1007": ("RMCSport1.fr@SD", "RMC Sport 1 ↔ rmcsport1.fr"),
    "1329": ("Nickelodeon.fr@SD", "Nickelodeon Full HD → national feed"),
    "1376": ("Nickelodeon.fr@SD", "Nickelodeon 4K → national France parrilla"),
    "1410": ("Nickelodeon.fr@SD", "panel nickelodeon.fr"),
    "1413": ("TeletoonPlus.fr@SD", "TELETOON ↔ teletoonplus.fr"),
    "1421": ("Boomerang.fr@SD", "panel boomerang.fr"),
    "1422": ("CartoonNetworkWesternEurope.uk@SD", "Cartoon Network FR listing"),
}

AR_CURATED_XTREAM: dict[str, tuple[str, str]] = {
    "1517": ("MBC1.ae@SD", "MBC1 HD primary UAE"),
    "1519": ("MBC3.ae@SD", "MBC3 HD UAE"),
    "1524": ("MBCDrama.ae@SD", "MBC Drama HD"),
    "1529": ("MBCMasr.eg@SD", "MBC MASR"),
    "1531": ("MBCDrama.ae@SD", "MBC Drama"),
    "1533": ("MBC3.ae@SD", "MBC 3"),
    "1526": ("MBCPlusDrama.sa@SD", "MBC Drama+ / Plus Drama"),
}

FR_REJECT_XTREAM: dict[str, str] = {
    "957": "Chérie 25 absent from FR/XMLTV sources",
    "964": "Canal+ Cinéma absent in guide",
    "967": "Canal+ Cine multiplex absent",
    "968": "Canal+ Cine multiplex absent",
    "969": "Canal+ Cine multiplex absent",
    "991": "Ligue 1+ 1 absent",
    "992": "Ligue 1+ 2 absent",
    "993": "Ligue 1+ 3 absent",
    "994": "Ligue 1+ 4 absent",
    "995": "Ligue 1+ 5 absent",
    "996": "Ligue 1+ 6 absent",
    "997": "Ligue 1+ 7 absent",
    "998": "Ligue 1+ 8 absent",
    "999": "Ligue 1+ 9 absent",
    "1000": "Ligue 1+ 10 absent",
    "1343": "France 3 4K: cannot confirm national vs regional emission",
}

BEIN_MOVIES = {
    1: "beINMovies1Premiere.qa@SD",
    2: "beINMovies2Action.qa@SD",
    3: "beINMovies3Drama.qa@SD",
    4: "beINMovies4Family.qa@SD",
}
BEIN_SERIES = {
    1: "beINSeries1.qa@SD",
    2: "arabic.beinseries2",
}
BEIN_NUMBERED = re.compile(r"bein\s*(movies?|series)\b.*?(\d)", re.IGNORECASE)

AR_BRAND_MAP: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"baraem|baraeam", re.I), "Baraem.qa@SD", "Baraem/Jeem preschool"),
    (re.compile(r"bein\s*jeem", re.I), "JeemTV.qa@SD", "Jeem TV"),
    (re.compile(r"fatafeat", re.I), "Fatafeat.ae@SD", "Fatafeat cooking"),
    (re.compile(r"gorm?ent", re.I), "beINGourmet.qa@SD", "beIN Gourmet typo"),
    (re.compile(r"fox\s*action", re.I), "FoxActionMoviesMENA.hk@SD", "Fox Action MENA"),
    (re.compile(r"fox\s*mov", re.I), "FoxMoviesMiddleEast.us@SD", "Fox Movies MENA"),
    (re.compile(r"star\s*movies", re.I), "FoxMoviesMiddleEast.us@SD", "Star Movies → Fox Movies MENA feed"),
    (re.compile(r"star\s*world", re.I), "StarWorldMiddleEast.ae@SD", "Star World MENA"),
]

AR_REJECT_XTREAM: dict[str, str] = {
    "1429": "Al Arabiya HD: portrait vs news feeds, no confirmed shared grid",
}

AR_REJECT_TITLE_SUBSTR: list[tuple[str, str]] = [
    ("mubasher", "Al Jazeera Mubasher feeds not in arabic guide"),
    ("jazeera english", "Al Jazeera English not captured in guide-arabic"),
    ("bbc", "BBC channels not in arabic national guide"),
    ("cnbc arabiya", "CNBC Arabiya missing"),
    ("nile news", "Nile News missing"),
    ("iraqia", "Iraqia channels missing"),
    ("mayadeen", "Al Mayadeen missing"),
    ("ir iran", "Iran International missing"),
]


def brand_rule_match(
    title: str, profile: str, catalog: EpgCatalog, allowed: set[str]
) -> tuple[str | None, str]:
    if profile != "arabic":
        return None, ""
    numbered = BEIN_NUMBERED.search(title)
    if numbered:
        kind = numbered.group(1).casefold()
        slot = int(numbered.group(2))
        if kind.startswith("movie") and slot in BEIN_MOVIES:
            channel_id = BEIN_MOVIES[slot]
            if channel_id in allowed and channel_id in catalog.programmed:
                return channel_id, f"brand_map:beIN Movies slot {slot}"
        if kind.startswith("series") and slot in BEIN_SERIES:
            channel_id = BEIN_SERIES[slot]
            if channel_id in allowed and channel_id in catalog.programmed:
                return channel_id, f"brand_map:beIN Series slot {slot}"
    for pattern, channel_id, note in AR_BRAND_MAP:
        if pattern.search(title) and channel_id in allowed and channel_id in catalog.programmed:
            return channel_id, f"brand_map:{note}"
    return None, ""


def score_candidates(
    row: dict,
    catalog: EpgCatalog,
    allowed: set[str],
) -> list[tuple[str, str, str]]:
    """Return list of (channel_id, reason, confidence)."""
    title = str(row.get("name") or "")
    epg_id = (row.get("epg_id") or "").strip()
    xtream_id = str(row.get("xtream_id") or "")
    found: list[tuple[str, str, str]] = []

    if epg_id and valid_panel_epg_id(epg_id):
        if epg_id in catalog.channels and epg_id in allowed:
            found.append((epg_id, "exact_panel_epg_id", "high"))
        stem_hits = {c for c in catalog.by_stem.get(channel_stem(epg_id), set()) if c in allowed}
        if len(stem_hits) == 1:
            found.append((next(iter(stem_hits)), "panel_stem_unique", "high"))
        core_hits = {c for c in catalog.by_panel_core.get(panel_core_key(epg_id), set()) if c in allowed}
        if len(core_hits) == 1:
            found.append((next(iter(core_hits)), "panel_core_unique", "medium"))

    title_hits: set[str] = set()
    for key in norm_keys(title):
        title_hits |= {c for c in catalog.by_name.get(key, set()) if c in allowed}
    if len(title_hits) == 1:
        found.append((next(iter(title_hits)), "title_unique", "high"))
    elif len(title_hits) > 1:
        pick = disambiguate_by_quality(title, title_hits)
        if pick and pick in allowed:
            found.append((pick, "title_quality_disambig", "medium"))

    brand_id, brand_note = brand_rule_match(title, row.get("_profile", ""), catalog, allowed)
    if brand_id:
        found.append((brand_id, brand_note, "high"))

    curated = FR_CURATED_XTREAM if row.get("_profile") == "fr" else AR_CURATED_XTREAM
    if xtream_id in curated:
        target, note = curated[xtream_id]
        if target in catalog.channels and target in allowed:
            found.append((target, f"curated:{note}", "high"))

    deduped: dict[str, tuple[str, str]] = {}
    rank = {"high": 3, "medium": 2, "low": 1}
    for cid, reason, conf in found:
        prev = deduped.get(cid)
        if not prev or rank[conf] > rank[prev[1]]:
            deduped[cid] = (reason, conf)
    return [(cid, reason, conf) for cid, (reason, conf) in deduped.items()]


def pick_match(row: dict, candidates: list[tuple[str, str, str]], catalog: EpgCatalog) -> tuple[str | None, str]:
    xtream_id = str(row.get("xtream_id") or "")
    profile = row.get("_profile", "")

    if profile == "fr" and xtream_id in FR_REJECT_XTREAM:
        return None, FR_REJECT_XTREAM[xtream_id]
    if profile == "arabic" and xtream_id in AR_REJECT_XTREAM:
        return None, AR_REJECT_XTREAM[xtream_id]
    if profile == "arabic":
        title_cf = str(row.get("name") or "").casefold()
        for needle, msg in AR_REJECT_TITLE_SUBSTR:
            if needle in title_cf:
                return None, msg

    high = [c for c in candidates if c[2] == "high"]
    if len(high) == 1:
        return high[0][0], high[0][1]
    if len(high) > 1:
        programmed = [c for c in high if c[0] in catalog.programmed]
        if len(programmed) == 1:
            return programmed[0][0], programmed[0][1] + "+programmed"
        return None, "ambiguous_high_confidence"
    return None, "no_fiable_match"


def merge_alias(aliases: dict[str, list[str]], channel_id: str, xtream_title: str) -> bool:
    title = xtream_title.strip()
    if not title:
        return False
    bucket = aliases.setdefault(channel_id, [])
    if title in bucket:
        return False
    bucket.append(title)
    return True


def review_profile(profile: str, dry_run: bool) -> dict:
    pending_path = PENDING_FILES[profile]
    pending = json.loads(pending_path.read_text(encoding="utf-8"))
    paths = [REGION_GUIDES[profile], published_global_guide(ROOT)]
    catalog = EpgCatalog(paths)
    allowed = catalog.allowed_ids(profile)
    aliases = json.loads(ALIAS_FILES[profile].read_text(encoding="utf-8"))

    reviewed = 0
    new_aliases = 0
    resolved = 0
    still_pending: list[dict] = []
    log: list[dict] = []

    for row in pending:
        reviewed += 1
        row = {**row, "_profile": profile}
        candidates = score_candidates(row, catalog, allowed)
        guide_id, decision = pick_match(row, candidates, catalog)

        global_hint = None
        epg_id = (row.get("epg_id") or "").strip()
        if epg_id and valid_panel_epg_id(epg_id) and epg_id in catalog.channels and epg_id not in allowed:
            global_hint = {
                "exists_in_global": True,
                "guide_id": epg_id,
                "sources": sorted(catalog.sources.get(epg_id, set())),
                "programmed": epg_id in catalog.programmed,
            }

        entry = {
            "xtream_id": row.get("xtream_id"),
            "name": row.get("name"),
            "epg_id": row.get("epg_id"),
            "candidates": [{"id": c[0], "reason": c[1], "confidence": c[2]} for c in candidates],
            "global_crossref": global_hint,
            "decision": decision,
            "matched_guide_id": guide_id,
        }
        log.append(entry)

        if guide_id and guide_id in allowed:
            if guide_id not in catalog.programmed:
                entry["decision"] = "rejected_unprogrammed"
                still_pending.append(row)
                continue
            if merge_alias(aliases, guide_id, str(row.get("name") or "")):
                new_aliases += 1
            resolved += 1
        else:
            still_pending.append(
                {
                    **{k: v for k, v in row.items() if not k.startswith("_")},
                    "status": row.get("status", "channel_not_in_sources"),
                    "detail": decision,
                    "reviewed_candidates": len(candidates),
                }
            )

    report = {
        "profile": profile,
        "reviewed_individually": reviewed,
        "new_alias_names": new_aliases,
        "newly_resolved": resolved,
        "still_pending": len(still_pending),
    }
    review_path = ROOT / "temp" / f"pending-review-{profile}.json"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(
        json.dumps({"summary": report, "log": log}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    if not dry_run:
        ALIAS_FILES[profile].write_text(
            json.dumps(aliases, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        pending_path.write_text(
            json.dumps(still_pending, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profiles", nargs="*", choices=("fr", "arabic"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    profiles = args.profiles or ["fr", "arabic"]
    summaries = [review_profile(p, args.dry_run) for p in profiles]
    print(json.dumps(summaries, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())