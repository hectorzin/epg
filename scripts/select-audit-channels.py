#!/usr/bin/env python3
"""Create curated Orange and El País channel lists from local audit snapshots."""
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

AUDIT = Path(sys.argv[1])
ROOT = Path(__file__).resolve().parents[1]
ORANGE_IDS = {
    "11093", "11281", "1089", "11091", "11094", "11092", "11095", "11096", "11097",
    "11182", "11098", "11099", "11102", "11103", "11100", "11183", "11184", "11120",
    "11121", "11128", "11104", "11105", "1081", "1095", "1086", "2209", "12007",
    "12006", "11273", "11106", "11107", "11232", "11270", "11015",
}
# El País candidates confirmed by the audit, curated to avoid channel clones,
# ambiguous names, and obsolete/rebranded duplicates. Keep this list explicit.
ELPAIS_CANDIDATE_IDS = {
    "18", "32", "34", "35", "36", "38", "39", "242", "280", "316",
    "324", "400", "416", "449", "521", "541", "551", "566", "567", "570",
    "582", "604", "608", "615", "629",
}
slug = lambda s: re.sub(r"[^a-z0-9]+", "", s.lower())
mov = ET.parse(ROOT / "sites/movistarplus.es/movistarplus.es.channels.xml").getroot()
mov_names = {slug((c.text or "").strip()) for c in mov.findall("channel")}
mov_ids = {c.get("xmltv_id") for c in mov.findall("channel") if c.get("xmltv_id")}

catalog = json.loads((AUDIT / "orange-channels.json").read_text(encoding="utf-8"))["response"]
observed = set()
for i in range(1, 4):
    data = json.loads((AUDIT / f"orange-{i}.json").read_text(encoding="utf-8"))
    for item in data:
        for prog in item.get("programs", []):
            if prog.get("name") and prog.get("startDate") and prog.get("endDate"):
                observed.add(str(item.get("channelExternalId")))
orange = ET.Element("channels")
for entry in catalog:
    sid, name = str(entry.get("externalChannelId", "")), (entry.get("name") or "").strip()
    normalized = slug(name)
    if sid not in ORANGE_IDS or sid not in observed or not name:
        continue
    if any(x in normalized for x in ("prueba", "test", "promo", "autopromocion")):
        continue
    if normalized in mov_names or (sid == "11015"):
        continue
    xmlid = f"Orange.{sid}"
    ET.SubElement(orange, "channel", {"site": "orangetv.orange.es", "lang": "es", "xmltv_id": xmlid, "site_id": sid}).text = name

elp_catalog = json.loads((AUDIT / "elpais-channels.json").read_text(encoding="utf-8"))
epg = ET.Element("channels")
elp_programs = json.loads((AUDIT / "elpais-programs.json").read_text(encoding="utf-8"))
active = {str(item.get("idCanal")) for item in elp_programs if item.get("programas")}
for key, entry in elp_catalog.items():
    sid, name = str(entry.get("id", key)), (entry.get("nombre") or "").strip()
    normalized = slug(name)
    if sid not in ELPAIS_CANDIDATE_IDS or sid not in active or not name or normalized in mov_names:
        continue
    if any(x in normalized for x in ("prueba", "test", "promo")):
        continue
    if sid == "292":
        continue  # Disney is explicitly represented by the Orange special case.
    ET.SubElement(epg, "channel", {"site": "programacion-tv.elpais.com", "lang": "es", "xmltv_id": f"ElPais.{sid}", "site_id": sid}).text = name

for name, tree in (("orange-selected.channels.xml", orange), ("elpais-selected.channels.xml", epg)):
    ET.indent(tree, space="    ")
    (ROOT / "sites" / ("orangetv.orange.es" if name.startswith("orange") else "programacion-tv.elpais.com") / name).write_bytes(
        ET.tostring(tree, encoding="utf-8", xml_declaration=True) + b"\n"
    )
print(f"Selected Orange {len(orange.findall('channel'))} channels; El País {len(epg.findall('channel'))} channels")
