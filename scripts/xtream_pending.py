#!/usr/bin/env python3
"""Classify unresolved Xtream catalog rows against an XMLTV guide."""
from __future__ import annotations

from typing import Any

from xtream_matching import (  # noqa: I001
    SECTION_HEADER,
    channel_stem,
    panel_core_key,
    resolve_row,
    valid_panel_epg_id,
)


def channel_programming( guide_ids: set[str], programmed: set[str]) -> dict[str, bool]:
    return {cid: cid in programmed for cid in guide_ids}


def classify_pending_row(
    row: dict[str, Any],
    *,
    channel_ids: set[str],
    programmed: set[str],
    stem_index: dict[str, set[str]],
    name_index: dict[str, set[str]],
    panel_core_index: dict[str, set[str]],
    allow_stream_clone: bool,
    clones: dict[str, str] | None = None,
) -> tuple[str | None, str]:
    """Return (reason_code, detail). reason_code is one of four pending buckets or None if matched."""
    title = str(row.get("name") or "")
    if SECTION_HEADER.match(title.strip()):
        return None, "section_header"

    clone_map = clones or {}
    guide_id, _, kind = resolve_row(
        title=title,
        panel_epg_id=row.get("epg_id"),
        stream_id=str(row.get("xtream_id") or ""),
        channel_ids=channel_ids | set(clone_map),
        stem_index=stem_index,
        name_index=name_index,
        panel_core_index=panel_core_index,
        allow_stream_clone=allow_stream_clone,
    )
    if guide_id:
        return None, kind

    epg_id = (row.get("epg_id") or "").strip()
    if valid_panel_epg_id(epg_id) and epg_id in clone_map:
        root = clone_map[epg_id]
        if root in channel_ids and root in programmed:
            return None, "clone_map"
    if kind in ("ambiguous_name", "ambiguous_stem"):
        return "ambiguous_association", kind

    if valid_panel_epg_id(epg_id):
        if epg_id in channel_ids or epg_id.casefold() in {c.casefold() for c in channel_ids}:
            if epg_id not in programmed and all(
                c not in programmed for c in channel_ids if c.casefold() == epg_id.casefold()
            ):
                return "channel_exists_no_programming", "panel_epg_in_guide_without_programming"
            return "unresolved_matching_with_programming", "panel_epg_known_but_title_mismatch"

        core = panel_core_key(epg_id)
        core_hits = panel_core_index.get(core, set())
        if core_hits:
            if len(core_hits) > 1:
                return "ambiguous_association", "panel_core_multiple_guides"
            target = next(iter(core_hits))
            if target in programmed:
                return "unresolved_matching_with_programming", "panel_core_suggests_programmed_guide"
            return "channel_exists_no_programming", "panel_core_unprogrammed_guide"

        stem_hits = stem_index.get(channel_stem(epg_id), set())
        if len(stem_hits) > 1:
            return "ambiguous_association", "panel_stem_regional"
        if len(stem_hits) == 1:
            target = next(iter(stem_hits))
            if target in programmed:
                return "unresolved_matching_with_programming", "panel_stem_suggests_programmed_guide"
            return "channel_exists_no_programming", "panel_stem_unprogrammed_guide"

        return "channel_not_in_sources", "epg_id_not_in_guide"

    if kind == "no_match":
        return "channel_not_in_sources", "no_guide_channel_or_alias"

    return "channel_not_in_sources", kind


def build_pending_report(
    rows: list[dict[str, Any]],
    *,
    channel_ids: set[str],
    programmed: set[str],
    stem_index: dict[str, set[str]],
    name_index: dict[str, set[str]],
    panel_core_index: dict[str, set[str]],
    allow_stream_clone: bool,
    clones: dict[str, str] | None = None,
    limit: int = 800,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        bucket, detail = classify_pending_row(
            row,
            channel_ids=channel_ids,
            programmed=programmed,
            stem_index=stem_index,
            name_index=name_index,
            panel_core_index=panel_core_index,
            allow_stream_clone=allow_stream_clone,
            clones=clones,
        )
        if not bucket:
            continue
        out.append(
            {
                "xtream_id": row.get("xtream_id"),
                "name": row.get("name"),
                "epg_id": row.get("epg_id"),
                "category": row.get("category"),
                "status": bucket,
                "detail": detail,
            }
        )
        if len(out) >= limit:
            break
    return out