#!/usr/bin/env python3
"""Curated FAST channel IDs for Spanish coverage stats."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ATRESCINE_ID = "cima.es.a3cine"


def _ids_from_channels_xml(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    root = ET.parse(path).getroot()
    out: set[str] = set()
    for channel in root.findall("channel"):
        xmltv_id = (channel.get("xmltv_id") or "").strip()
        if xmltv_id:
            out.add(xmltv_id)
    return out


def fast_provider_channel_ids() -> dict[str, set[str]]:
    """Map provider label -> xmltv channel ids from curated channel lists."""
    epg = ROOT / "epg"
    return {
        "Pluto TV": _ids_from_channels_xml(epg / "es-pluto.channels.xml"),
        "Samsung TV Plus": _ids_from_channels_xml(epg / "es-samsung.channels.xml"),
        "Rakuten (EPGShare)": _ids_from_channels_xml(epg / "es-rakuten.channels.xml"),
        "Atrescine": {ATRESCINE_ID},
    }


def channel_provider_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for provider, ids in fast_provider_channel_ids().items():
        for channel_id in ids:
            mapping[channel_id] = provider
    return mapping