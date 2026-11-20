#!/usr/bin/env python3
"""Curated GB Xtream review: dev.linear IDs, NULL panels and safe name matches."""
from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from xtream_matching import (  # noqa: E402
    build_guide_indexes,
    disambiguate_by_quality,
    resolve_row,
    valid_panel_epg_id,
)
from compare_xtream_catalog import catalog_link_stats, merge_aliases_into_names  # noqa: E402
from xtream_pending import classify_pending_row  # noqa: E402

CATALOG_PATH = ROOT / "temp" / "uk-xtream-catalog.json"
GUIDE_PATH = ROOT / "guides" / "guide-gb.xml"
ALIASES_PATH = ROOT / "epg" / "aliases-gb.json"
CLONES_PATH = ROOT / "epg" / "xtream-aliases-gb.json"
PENDING_PATH = ROOT / "epg" / "xtream-pending-gb.json"

DEV_LINEAR_TO_GUIDE: dict[str, str] = {
    "dev.linear.en.100217": "Film4.uk@HD",
    "dev.linear.en.100250": "SkyCinemaSelect.uk@SD",
    "dev.linear.en.100251": "SkySciFi.uk@HD",
    "dev.linear.en.100252": "SkyCinemaSelect.uk@SD",
    "dev.linear.en.100253": "SkyCinemaThriller.uk@HD",
    "dev.linear.en.100257": "SkyCinemaHits.uk@HD",
    "dev.linear.en.100258": "SkyCinemaGreats.uk@HD",
    "dev.linear.en.100259": "SkyCinemaDrama.uk@HD",
    "dev.linear.en.100260": "SkyCinemaFamily.uk@HD",
    "dev.linear.en.100261": "SkyCinemaComedy.uk@HD",
    "dev.linear.en.100262": "SkyCinemaFamily.uk@HD",
    "dev.linear.en.100263": "SkyCinemaAction.uk@HD",
    "dev.linear.en.100277": "GREATmovies.uk@UK",
    "dev.linear.en.100294": "Film4.uk@Plus1",
    "dev.linear.en.100323": "GREATaction.uk@SD",
    "dev.linear.en.100324": "GREATromance.uk@UK",
    "dev.linear.en.100345": "Legend.uk@SD",
    "dev.linear.en.100355": "GREATmovies.uk@UK",
}

CURATED_XTREAM: dict[str, tuple[str, str]] = {
    "2433": ("BBCOne.uk@HD", "BBC One national HD feed"),
    "2434": ("BBCTwo.uk@HD", "BBC Two national HD feed"),
    "2435": ("BBCThree.uk@HD", "BBC Three HD feed"),
    "2436": ("BBCFour.uk@UKHD", "BBC Four HD feed"),
    "2441": ("ITV1.uk@HD", "ITV1 national HD"),
    "2442": ("ITV2.uk@HD", "ITV2 HD feed (not +1)"),
    "2443": ("ITV3.uk@HD", "ITV3 HD feed"),
    "2444": ("ITV4.uk@HD", "ITV4 HD feed"),
    "2449": ("ITVBe.uk@HD", "ITVBe HD"),
    "2454": ("CBBC.uk@HD", "CITV replaced by CBBC in sources"),
    "2466": ("4seven.uk@HD", "duplicate 4seven listing"),
    "2467": ("5USA.uk@SD", "fiveusa.uk stem"),
    "2468": ("5Action.uk@HD", "5action.uk"),
    "2469": ("5SELECT.uk@SD", "5select.uk"),
    "2470": ("5STAR.uk@SD", "5star.uk"),
    "2478": ("AriseNews.uk@UK", "arisenews.uk"),
    "2479": ("AnimalPlanet.uk@HD", "animalplanet.uk HD"),
    "2494": ("Channel4.uk@UKHD", "channel4.uk SD label → UK HD emission"),
    "2495": ("Channel5.uk@HD", "channel5.uk"),
    "2497": ("ClublandTV.uk@SD", "clublandtv.uk"),
    "2502": ("ComedyCentral.uk@HD", "comedycentral.uk"),
    "2572": ("GBNews.uk@SD", "gbnews.uk"),
    "2581": ("E4.uk@HD", "e4.uk"),
    "2582": ("E4Extra.uk@SD", "e4extra.uk"),
    "2583": ("Gold.uk@SD", "gold.uk"),
    "2584": ("Challenge.uk@SD", "challenge.uk"),
    "2585": ("Alibi.uk@SD", "alibi.uk base (not +1 clone row)"),
    "2588": ("BBCNews.uk@UKHD", "bbcnews.uk"),
    "2589": ("CBeebies.uk@HD", "cbeebies.uk"),
    "2593": ("BBCOne.uk@ScotlandHD", "regional Scotland emission, not London +1"),
    "2594": ("More4.uk@HD", "more4.uk"),
    "2595": ("Quest.uk@HD", "quest.uk"),
    "2610": ("CNNInternational.us@UK", "cnn.uk panel → UK collision feed"),
    "2591": ("SkyNews.uk@HD", "skynews.uk"),
    "2603": ("BabyTV.uk@UK", "babytv.uk"),
    "2607": ("SkySportsGolf.uk@HD", "skysportsgolf.uk"),
    "2608": ("SkySportsMainEvent.uk@HD", "skysportsmainevent.uk"),
    "2684": ("4seven.uk@HD", "second 4seven HD row"),
    "2685": ("Challenge.uk@SD", "challenge HD label → SD id in guide"),
    "2691": ("CBBC.uk@HD", "cbbc.uk"),
    "2500": ("ComedyCentral.uk@Plus1", "Comedy Central +1 in merged UK guide"),
    "2503": ("CrimeInv.uk@HD", "Crime+Inv HD (merged id CrimeInv.uk@HD)"),
    "2646": ("Nickelodeon.uk@Plus1", "Nickelodeon +1 in merged guide"),
    "2650": ("AnimalPlanet.uk@Plus1", "Animal Planet +1 in merged guide"),
}

PANEL_CORE_CLONE: dict[str, str] = {
    "fiveusa.uk": "5USA.uk@SD",
    "5action.uk": "5Action.uk@HD",
    "5select.uk": "5SELECT.uk@SD",
    "5star.uk": "5STAR.uk@SD",
    "channel4.uk": "Channel4.uk@UKHD",
    "channel5.uk": "Channel5.uk@HD",
    "comedycentral.uk": "ComedyCentral.uk@HD",
    "e4.uk": "E4.uk@HD",
    "itv2.uk": "ITV2.uk@HD",
    "itv3.uk": "ITV3.uk@HD",
    "itv4.uk": "ITV4.uk@HD",
    "nickelodeon.uk": "Nickelodeon.uk@HD",
    "channel4.ukplus1": "Channel4.uk@UKPlus1",
    "fivestarplus1.uk": "5STAR.uk@Plus1",
    "fiveusaplus1.uk": "5USA.uk@Plus1",
    "nickjunior.uk": "NickJr.uk@SD",
    "nicktoons.uk": "Nicktoons.uk@SD",
    "cartoonito.uk": "Cartoonito.uk@SD",
    "boomerang.uk": "Boomerang.uk@SD",
    "discoverydmax.uk": "DMAX.uk@UK",
    "arisenews.uk": "AriseNews.uk@UK",
    "animalplanet.uk": "AnimalPlanet.uk@HD",
    "questred.uk": "QuestRed.uk@SD",
    "greattv.uk": "GREATtv.uk@SD",
    "skysportsmainevent.uk": "SkySportsMainEvent.uk@HD",
    "crimeplusinvestigation.uk": "CrimeInv.uk@HD",
    "nickelodeon.ukplus1": "Nickelodeon.uk@Plus1",
    "comedycentral.ukplus1": "ComedyCentral.uk@Plus1",
    "foodnetwork.uk": "FoodNetwork.uk@SD",
    "tlc.uk": "TLC.uk@HD",
    "quest.uk": "Quest.uk@HD",
    "more4.uk": "More4.uk@HD",
    "more4plus1.uk": "More4.uk@Plus1",
    "e4plus1.uk": "E4.uk@Plus1",
    "questplus1.uk": "Quest.uk@Plus1",
    "questredplus1.uk": "QuestRed.uk@Plus1",
    "greattvplus1.uk": "GREATtv.uk@Plus1",
    "greatactionplus1.uk": "GREATaction.uk@Plus1",
    "euronews.uk": "EuronewsEnglish.fr@UK",
    "cnn.uk": "CNNInternational.us@UK",
    "skysportsboxoffice.uk": "SkySportsBoxOffice.uk@UK",
    "disneyjr.uk": "DisneyJr.uk@HD",
}

REJECT_XTREAM: dict[str, str] = {
    "2445": "BT Sport Extra 6 absent after TNT rebrand",
    "2446": "BT Sport Extra 7 absent",
    "2447": "BT Sport Extra 8 absent",
    "2448": "BT Sport Extra 9 absent",
    "2451": "Tiny Pop absent from merged UK sources",
    "2452": "POP absent from merged UK sources",
    "2453": "POP Max absent",
    "2471": "5 STAR+1 separate timeshift — guide has 5STAR.uk@Plus1 via name",
    "2472": "5 USA+1 mapped via plus1 stem when matched",
    "2492": "Cartoon Network absent as standalone timeshift from NULL panel",
    "2523": "Zee TV SD absent — guide has ZeeTVUK.uk@HD",
    "2524": "Utsav Plus absent as SD-only clone",
    "2525": "Utsav Gold SD clone redundant with HD feed",
    "2573": "Good News TV only on EPGShare weak id — rejected",
    "2596": "BBC World News absent as distinct emission",
    "2597": "TG4 Irish regional — guide has TG4.ie@HD",
    "2598": "RTE One absent",
    "2599": "RTE Two absent",
    "2600": "RTE News absent",
    "2601": "RTE JR absent",
    "2602": "Nat Geo SD-only clone ambiguous with HD",
    "2611": "Racing TV exists but NULL panel duplicates RacingTV.uk@HD",
    "2612": "TCM absent from UK merge",
    "2620": "Disney XD absent",
    "2621": "Disney Channel guide uses DisneyChannel.uk@SD",
    "2624": "Watch channel absent",
    "2626": "NBC News Now absent",
    "2628": "NOW Rock guide id NOWRock.uk@SD",
    "2638": "PTV Global absent",
    "2642": "ITV Box Office absent",
    "2657": "ITV +4 absent",
    "2658": "ITV +3 absent",
    "2659": "ITV +2 absent",
    "2660": "ITV Meridian +1 regional absent",
    "2661": "ITV London +1 regional absent",
    "2662": "ITV Granada +1 regional absent",
    "2664": "Channel 4 Scotland +1 absent",
    "2665": "Channel 4 North +1 absent",
    "2666": "Channel 4 London +1 mapped via Channel4.uk@UKPlus1 when justified",
    "2686": "AMC absent from sources",
    "2689": "TCM +1 absent",
}

REGIONAL_PLUS1_RE = re.compile(
    r"\b(ITV\s*1?\s*(?:London|Granada|Meridian)|Channel\s*4\s*(?:London|North|Scotland))\s*\+",
    re.IGNORECASE,
)


def load_guide() -> tuple[set[str], dict[str, list[str]], set[str]]:
    root = ET.parse(GUIDE_PATH).getroot()
    ids: set[str] = set()
    names: dict[str, list[str]] = {}
    programmed: set[str] = set()
    for channel in root.findall("channel"):
        cid = channel.get("id") or ""
        if not cid:
            continue
        ids.add(cid)
        names[cid] = [n.text or "" for n in channel.findall("display-name") if (n.text or "").strip()]
    for programme in root.findall("programme"):
        if (programme.findtext("title") or "").strip():
            programmed.add(programme.get("channel") or "")
    return ids, names, programmed


def merge_alias(aliases: dict[str, list[str]], guide_id: str, title: str) -> None:
    title = title.strip()
    if not title:
        return
    bucket = aliases.setdefault(guide_id, [])
    if title not in bucket:
        bucket.append(title)


def merge_clone(clones: dict[str, str], clone_id: str, guide_id: str) -> bool:
    if not clone_id or clone_id == guide_id:
        return False
    if clone_id in clones and clones[clone_id] != guide_id:
        return False
    clones[clone_id] = guide_id
    return True


def main() -> int:
    if not CATALOG_PATH.is_file() or not GUIDE_PATH.is_file():
        print("Missing catalog or guide-gb.xml", file=sys.stderr)
        return 1
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    guide_ids, guide_names, programmed = load_guide()
    stem_index, name_index, panel_core_index = build_guide_indexes(guide_ids, guide_names)
    aliases = json.loads(ALIASES_PATH.read_text(encoding="utf-8")) if ALIASES_PATH.is_file() else {}
    clones = json.loads(CLONES_PATH.read_text(encoding="utf-8")) if CLONES_PATH.is_file() else {}

    curated_applied: list[dict[str, str]] = []
    covered_xtream: set[str] = set()

    for row in catalog:
        xtream_id = str(row["xtream_id"])
        title = str(row.get("name") or "")
        epg_id = (row.get("epg_id") or "").strip()
        reject_clone = xtream_id in REJECT_XTREAM or bool(REGIONAL_PLUS1_RE.search(title))
        guide_id = None
        clone_id = None
        reason = ""

        if xtream_id in CURATED_XTREAM:
            guide_id, reason = CURATED_XTREAM[xtream_id]
            if guide_id not in guide_ids or guide_id not in programmed:
                guide_id = None
        elif epg_id in DEV_LINEAR_TO_GUIDE:
            guide_id = DEV_LINEAR_TO_GUIDE[epg_id]
            clone_id = epg_id
            reason = "dev.linear"
        elif epg_id.casefold() in PANEL_CORE_CLONE:
            guide_id = PANEL_CORE_CLONE[epg_id.casefold()]
            clone_id = epg_id.strip()
            reason = "panel_core_curated"
        elif valid_panel_epg_id(epg_id):
            pid = epg_id.strip()
            if pid in guide_ids:
                guide_id = pid
                reason = "exact_panel"
            else:
                resolved, resolved_clone, kind = resolve_row(
                    title=title.replace("UK ", "", 1),
                    panel_epg_id=pid,
                    stream_id=xtream_id,
                    channel_ids=guide_ids,
                    stem_index=stem_index,
                    name_index=name_index,
                    panel_core_index=panel_core_index,
                    allow_stream_clone=False,
                )
                if resolved and resolved in programmed:
                    guide_id = resolved
                    clone_id = resolved_clone
                    reason = kind
        else:
            resolved, resolved_clone, kind = resolve_row(
                title=title.replace("UK ", "", 1),
                panel_epg_id=None,
                stream_id=xtream_id,
                channel_ids=guide_ids,
                stem_index=stem_index,
                name_index=name_index,
                panel_core_index=panel_core_index,
                allow_stream_clone=False,
            )
            if resolved and resolved in programmed:
                guide_id = resolved
                clone_id = resolved_clone
                reason = kind

        if not guide_id or guide_id not in guide_ids or guide_id not in programmed:
            continue
        covered_xtream.add(xtream_id)
        merge_alias(aliases, guide_id, title)
        if (
            not reject_clone
            and clone_id
            and clone_id != guide_id
            and valid_panel_epg_id(clone_id)
        ):
            merge_clone(clones, clone_id, guide_id)
        curated_applied.append(
            {"xtream_id": xtream_id, "guide_id": guide_id, "clone_id": clone_id or "", "reason": reason}
        )

    for clone_id, guide_id in PANEL_CORE_CLONE.items():
        if guide_id in guide_ids and guide_id in programmed and clone_id not in clones:
            if valid_panel_epg_id(clone_id) and clone_id != guide_id and clone_id not in guide_ids:
                clones[clone_id] = guide_id

    for epg_id, guide_id in DEV_LINEAR_TO_GUIDE.items():
        if guide_id in guide_ids and epg_id not in clones:
            clones[epg_id] = guide_id

    # Flatten: never point clone to another clone
    for clone_id, guide_id in list(clones.items()):
        while guide_id in clones and clones[guide_id] != guide_id:
            guide_id = clones[guide_id]
        clones[clone_id] = guide_id
        if clone_id == guide_id:
            del clones[clone_id]

    def clone_allowed(clone_id: str, guide_id: str, title: str) -> bool:
        if guide_id not in guide_ids or clone_id == guide_id:
            return False
        plus_feed = "@plus1" in guide_id.casefold() or guide_id.endswith("+1")
        title_cf = title.casefold()
        if plus_feed and not any(token in title_cf for token in ("+1", "plus 1", "plus1")):
            return False
        return True

    panel_title_by_id = {
        (row.get("epg_id") or "").strip().casefold(): str(row.get("name") or "")
        for row in catalog
        if valid_panel_epg_id(row.get("epg_id"))
    }
    filtered_clones: dict[str, str] = {}
    for clone_id, guide_id in clones.items():
        if guide_id not in guide_ids or clone_id == guide_id:
            continue
        title = panel_title_by_id.get(clone_id.casefold(), "")
        if not clone_allowed(clone_id, guide_id, title):
            continue
        filtered_clones[clone_id] = guide_id
    clones = filtered_clones
    aliases = {cid: names for cid, names in aliases.items() if cid in guide_ids}

    enriched_names = merge_aliases_into_names(guide_ids, guide_names, aliases)
    pending: list[dict[str, str]] = []
    for row in catalog:
        xtream_id = str(row["xtream_id"])
        if catalog_link_stats(
            [row],
            channel_ids=guide_ids,
            display_names=enriched_names,
            clones=clones,
            programmed=programmed,
            allow_stream_clone=False,
        )["matched_to_guide"]:
            continue
        bucket, detail = classify_pending_row(
            row,
            channel_ids=guide_ids | set(clones),
            programmed=programmed,
            stem_index=stem_index,
            name_index=name_index,
            panel_core_index=panel_core_index,
            allow_stream_clone=False,
            clones=clones,
        )
        if not bucket:
            continue
        pending.append(
            {
                "xtream_id": xtream_id,
                "name": str(row.get("name") or ""),
                "epg_id": row.get("epg_id"),
                "category": row.get("category"),
                "status": bucket,
                "detail": detail,
            }
        )

    ALIASES_PATH.write_text(json.dumps(aliases, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    CLONES_PATH.write_text(json.dumps(clones, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    PENDING_PATH.write_text(json.dumps(pending, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    review_path = ROOT / "temp" / "gb-xtream-curated-log.json"
    review_path.write_text(json.dumps(curated_applied, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    matched = {
        str(row["xtream_id"])
        for row in catalog
        if catalog_link_stats(
            [row],
            channel_ids=guide_ids,
            display_names=enriched_names,
            clones=clones,
            programmed=programmed,
            allow_stream_clone=False,
        )["matched_to_guide"]
    }

    print(
        json.dumps(
            {
                "catalog_rows": len(catalog),
                "curated_links": len(curated_applied),
                "display_alias_channels": len(aliases),
                "clone_mappings": len(clones),
                "pending": len(pending),
                "estimated_coverage": len(matched),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())