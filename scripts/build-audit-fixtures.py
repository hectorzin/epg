#!/usr/bin/env python3
"""Create source XMLTV test feeds from the local epg-audit JSON snapshots."""
import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

audit, rootdir, outdir = map(Path, sys.argv[1:4])
outdir.mkdir(parents=True, exist_ok=True)


def channel_nodes(filename):
    return ET.parse(rootdir / filename).getroot().findall("channel")


def add_channel(root, source):
    channel = ET.SubElement(root, "channel", id=source.get("xmltv_id"))
    ET.SubElement(channel, "display-name").text = (source.text or "").strip()


def add_program(root, channel_id, start, stop, title, description=None):
    if not channel_id or not title or stop <= start:
        return
    p = ET.SubElement(root, "programme", channel=channel_id,
                       start=start.strftime("%Y%m%d%H%M%S +0000"),
                       stop=stop.strftime("%Y%m%d%H%M%S +0000"))
    ET.SubElement(p, "title").text = title
    if description:
        ET.SubElement(p, "desc").text = description


orange_channels = channel_nodes("sites/orangetv.orange.es/orange-selected.channels.xml")
orange_by_site = {c.get("site_id"): c for c in orange_channels}
orange_root = ET.Element("tv")
for c in orange_channels:
    add_channel(orange_root, c)

# Each local segment is a flat array of {channelExternalId, programs} blocks.
orange_program_count = 0
for segment in range(1, 4):
    blocks = json.loads((audit / f"orange-{segment}.json").read_text(encoding="utf-8"))
    for block in blocks:
        source_channel = orange_by_site.get(str(block.get("channelExternalId")))
        if source_channel is None:
            continue
        target_id = source_channel.get("xmltv_id")
        if source_channel.get("site_id") == "11232":
            target_id = "MovistarPlus.dazb2"
        elif source_channel.get("site_id") == "11270":
            target_id = "MovistarPlus.dazb3"
        elif source_channel.get("site_id") == "11015":
            target_id = "MovistarPlus.playdc"
        elif source_channel.get("site_id") in {
            "1054", "1055", "1056", "11036", "1096", "1097", "1098", "1099",
        }:
            target_id = {
                "1054": "MovistarPlus.chap5",
                "1055": "MovistarPlus.chap6",
                "1056": "MovistarPlus.chap7",
                "11036": "MovistarPlus.chap8",
                "1096": "MovistarPlus.chap9",
                "1097": "MovistarPlus.chap10",
                "1098": "MovistarPlus.chap11",
                "1099": "MovistarPlus.chap12",
            }[source_channel.get("site_id")]
        for item in block.get("programs", []):
            try:
                start = datetime.fromtimestamp(float(item["startDate"]) / 1000, timezone.utc)
                stop = datetime.fromtimestamp(float(item["endDate"]) / 1000, timezone.utc)
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            title = (item.get("name") or "").strip()
            before = len(orange_root.findall("programme"))
            add_program(orange_root, target_id, start, stop, title, item.get("description"))
            orange_program_count += len(orange_root.findall("programme")) - before

elp_channels = channel_nodes("sites/programacion-tv.elpais.com/elpais-selected.channels.xml")
elp_by_site = {c.get("site_id"): c for c in elp_channels}
elp_root = ET.Element("tv")
for c in elp_channels:
    add_channel(elp_root, c)
elp_program_count = 0
items = json.loads((audit / "elpais-programs.json").read_text(encoding="utf-8"))
for block in items:
    source_channel = elp_by_site.get(str(block.get("idCanal")))
    if source_channel is None:
        continue
    for item in block.get("programas", []):
        try:
            start = datetime.strptime(item["iniDate"], "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=ZoneInfo("Europe/Madrid")
            ).astimezone(timezone.utc)
            stop = datetime.strptime(item["endDate"], "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=ZoneInfo("Europe/Madrid")
            ).astimezone(timezone.utc)
        except (KeyError, TypeError, ValueError):
            continue
        title = (item.get("title") or item.get("name") or "").strip()
        before = len(elp_root.findall("programme"))
        add_program(elp_root, source_channel.get("xmltv_id"), start, stop, title, item.get("description"))
        elp_program_count += len(elp_root.findall("programme")) - before

for filename, tree in (("orange.audit.xml", orange_root), ("elpais.audit.xml", elp_root)):
    ET.ElementTree(tree).write(outdir / filename, encoding="utf-8", xml_declaration=True)
print(f"Offline feeds: Orange {orange_program_count} programmes; El País {elp_program_count} programmes")
