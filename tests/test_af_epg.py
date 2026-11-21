import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AF_SCRIPT = ROOT / "scripts" / "af-epg.py"
VALIDATE_SCRIPT = ROOT / "scripts" / "af_publish_validate.py"
PROCESS_SCRIPT = ROOT / "scripts" / "process-epg.py"
STATIONS = ROOT / "epg" / "af-stations.json"
ALIASES = ROOT / "epg" / "aliases-af.json"
XTREAM = ROOT / "epg" / "xtream-aliases-af.json"

SHARED = {
    "2STV.sn@SD",
    "Canal2International.cm@SD",
    "CRTV.cm@SD",
    "ORTM1.ml@SD",
    "ORTBTV.bj@SD",
    "RTI1.ci@SD",
    "TFM.sn@SD",
    "SenTV.sn@SD",
    "NollywoodTV.fr@SD",
    "AlJazeera.qa@Arabic",
    "TraceToca.fr@SD",
    "VoxAfrica.uk@SD",
    "TVCNews.ng@SD",
}
FRESH = {
    "RTS1.sn@SD",
    "RTI2.ci@SD",
    "ORTM2.ml@SD",
    "Canal3.bj@SD",
    "RTB.bf@SD",
    "RwandaTV.rw@SD",
    "M7.ml@SD",
    "BenieTV.sn@SD",
    "WalfTV.sn@SD",
    "AsfiyahiTV.sn@SD",
    "KalacTV.gn@SD",
    "LampFallTV.sn@SD",
    "MalikiaTV.sn@SD",
    "ITV.sn@SD",
    "TM1.ml@SD",
    "KC2.rw@SD",
    "VoxTV.cg@SD",
    "TMA.gp@SD",
}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


af_epg = load_module("af_epg", AF_SCRIPT)


def write_channels(path: Path, rows: list[tuple[str, str, str, str]]) -> None:
    root = ET.Element("channels")
    for site, site_id, xmltv_id, name in rows:
        node = ET.SubElement(
            root,
            "channel",
            site=site,
            lang="fr",
            site_id=site_id,
            xmltv_id=xmltv_id,
        )
        node.text = name
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def write_guide(path: Path, channels: list[tuple[str, str]], programmes: list[tuple[str, str, str]]) -> None:
    root = ET.Element("tv")
    for channel_id, name in channels:
        channel = ET.SubElement(root, "channel", id=channel_id)
        ET.SubElement(channel, "display-name").text = name
    for channel_id, title, start in programmes:
        programme = ET.SubElement(
            root,
            "programme",
            channel=channel_id,
            start=start,
            stop="20261120130000 +0000",
        )
        ET.SubElement(programme, "title").text = title
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def titles(root: ET.Element, channel_id: str) -> list[str]:
    return [
        programme.findtext("title") or ""
        for programme in root.findall("programme")
        if programme.get("channel") == channel_id
    ]


def source_ids(station: dict) -> list[str]:
    return [source["site_id"] for source in station["sources"]]


class AfricanTableTests(unittest.TestCase):
    def test_catalog_names_are_partitioned_without_overlap(self):
        stations, unmatched = af_epg.load_table(STATIONS)
        names = [name for station in stations for name in station["names"]]
        unmatched_names = [row["name"] for row in unmatched]
        self.assertEqual(len(stations), 31)
        self.assertEqual(len(names) + len(unmatched_names), 106)
        self.assertEqual(len(names), len(set(names)))
        self.assertFalse(set(names) & set(unmatched_names))
        self.assertEqual(json.loads(ALIASES.read_text(encoding="utf-8")), af_epg.display_aliases(stations))
        self.assertEqual(json.loads(XTREAM.read_text(encoding="utf-8")), {})
        by_id = {station["id"]: station for station in stations}
        self.assertEqual(set(by_id), SHARED | FRESH)
        self.assertEqual(source_ids(by_id["Canal2International.cm@SD"]), ["sn#180172"])
        self.assertEqual(source_ids(by_id["CRTV.cm@SD"]), ["sn#180010"])
        self.assertEqual(source_ids(by_id["AlJazeera.qa@Arabic"]), ["sn#180277"])
        self.assertEqual(source_ids(by_id["RTS1.sn@SD"]), ["sn#180076"])
        self.assertEqual(source_ids(by_id["RTI2.ci@SD"]), ["sn#180271"])
        self.assertEqual(source_ids(by_id["ORTM1.ml@SD"]), ["sn#180069"])
        self.assertEqual(source_ids(by_id["ORTM2.ml@SD"]), ["sn#180397"])
        self.assertEqual(source_ids(by_id["RTB.bf@SD"]), ["sn#180121"])
        self.assertEqual(source_ids(by_id["NollywoodTV.fr@SD"]), ["sn#180270"])
        self.assertEqual(source_ids(by_id["TMA.gp@SD"]), ["TMA.gp@SD"])
        self.assertEqual(by_id["ORTBTV.bj@SD"]["sources"], [])
        self.assertEqual(by_id["TraceToca.fr@SD"]["sources"], [])
        self.assertEqual(by_id["TVCNews.ng@SD"]["sources"], [])
        self.assertNotIn("RTS1.ch@SD", by_id)
        self.assertNotIn("TVMInternacional.mz@SD", by_id)
        self.assertNotIn("NollywoodTVEpic.fr@SD", by_id)
        for name in (
            "AF RTS 3 -Senegal",
            "AF TV5 Monde info",
            "AF TV7 Colmar",
            "AF Cis TV -Congo",
            "AF Espace TV -Cameron",
            "AF Impac TV -Cameron",
            "AF VOX AFRICA News",
            "AF TVM1 -Mozambique",
            "AF Tv Mocambique -Mozambique",
            "IR Hadi TV3",
        ):
            self.assertIn(name, unmatched_names)

    def test_select_skips_shared_ids_and_other_feeds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "canalplus.channels.xml"
            occupied = root / "guide-fr.xml"
            selected = root / "selected.xml"
            write_channels(
                catalog,
                [
                    ("canalplus.com", "sn#180171", "", "RTI 1"),
                    ("canalplus.com", "sn#180076", "", "RTS"),
                    ("canalplus.com", "sn#180666", "", "RTS 2"),
                    ("canalplus.com", "sn#180671", "", "CANAL 2 MOVIES"),
                    ("canalplus.com", "sn#180172", "", "CANAL 2 INTER"),
                    ("canalplus.com", "sn#180297", "", "AL JAZEERA ENG"),
                    ("canalplus.com", "sn#180277", "", "AL JAZEERA"),
                    ("canalplus.com", "sn#180271", "", "RTI2"),
                ],
            )
            write_guide(
                occupied,
                [
                    ("RTI1.ci@SD", "RTI 1"),
                    ("Canal2International.cm@SD", "Canal 2"),
                    ("AlJazeera.qa@Arabic", "Al Jazeera"),
                ],
                [
                    ("RTI1.ci@SD", "From France", "20261120090000 +0000"),
                    ("Canal2International.cm@SD", "From France", "20261120090000 +0000"),
                    ("AlJazeera.qa@Arabic", "From France", "20261120090000 +0000"),
                ],
            )
            count = af_epg.select_channels(catalog, selected, STATIONS, [occupied])
            kept = {channel.get("site_id") for channel in ET.parse(selected).getroot().findall("channel")}
            self.assertEqual(count, 2)
            self.assertEqual(kept, {"sn#180076", "sn#180271"})

    def test_merge_reuses_shared_ids_and_keeps_variants_apart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "canalplus.channels.xml"
            guide = root / "canalplus.xml"
            france = root / "guide-fr.xml"
            output = root / "guide-af.xml"
            write_channels(
                catalog,
                [
                    ("canalplus.com", "sn#180076", "", "RTS"),
                    ("canalplus.com", "sn#180271", "", "RTI2"),
                    ("canalplus.com", "sn#180069", "", "ORTM1"),
                    ("canalplus.com", "sn#180397", "", "ORTM2"),
                ],
            )
            write_guide(
                guide,
                [
                    ("sn#180076", "RTS"),
                    ("sn#180271", "RTI2"),
                    ("sn#180069", "ORTM1"),
                    ("sn#180397", "ORTM2"),
                ],
                [
                    ("sn#180076", "JT Senegal", "20261120120000 +0000"),
                    ("sn#180271", "RTI 2 show", "20261120120000 +0000"),
                    ("sn#180069", "Should not repeat", "20261120120000 +0000"),
                    ("sn#180397", "ORTM 2 show", "20261120120000 +0000"),
                ],
            )
            write_guide(
                france,
                [("ORTM1.ml@SD", "ORTM"), ("RTI1.ci@SD", "RTI 1")],
                [
                    ("ORTM1.ml@SD", "From France", "20261120080000 +0000"),
                    ("RTI1.ci@SD", "From France", "20261120080000 +0000"),
                ],
            )
            _channels, _programmes, stats = af_epg.write_merged(
                [("canalplus", guide, catalog)],
                output,
                STATIONS,
                [france],
                [],
            )
            merged = ET.parse(output).getroot()
            self.assertEqual(titles(merged, "RTS1.sn@SD"), ["JT Senegal"])
            self.assertEqual(titles(merged, "RTI2.ci@SD"), ["RTI 2 show"])
            self.assertEqual(titles(merged, "ORTM2.ml@SD"), ["ORTM 2 show"])
            self.assertEqual(titles(merged, "ORTM1.ml@SD"), [])
            self.assertEqual(titles(merged, "RTI1.ci@SD"), [])
            ids = {channel.get("id") for channel in merged.findall("channel")}
            self.assertIn("ORTM1.ml@SD", ids)
            self.assertIn("RTI1.ci@SD", ids)
            self.assertNotIn("RTS1.ch@SD", ids)
            self.assertGreaterEqual(stats["shared"], 2)
            self.assertGreaterEqual(stats["grabbed"], 3)

    def test_fresh_ids_are_not_already_programmed_elsewhere(self):
        present: set[str] = set()
        watched = SHARED | FRESH | {"RTS1.ch@SD", "RTS2.ch@SD", "TVMInternacional.mz@SD"}
        for name in ("guide-fr.xml", "guide-pt.xml", "guide-gb.xml", "guide-arabic.xml"):
            path = ROOT / "guides" / name
            for _event, elem in ET.iterparse(path, events=("end",)):
                if elem.tag == "programme" and elem.get("channel") in watched:
                    if (elem.findtext("title") or "").strip():
                        present.add(elem.get("channel") or "")
                if elem.tag in {"programme", "channel"}:
                    elem.clear()
        self.assertTrue(SHARED <= present, sorted(SHARED - present))
        self.assertFalse(FRESH & present, sorted(FRESH & present))
        self.assertNotIn("TVMInternacional.mz@SD", FRESH)

    def test_validator_rejects_a_second_schedule_on_a_shared_id(self):
        validate = load_module("af_publish_validate", VALIDATE_SCRIPT)
        now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S +0000")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guide = root / "guide-af.xml"
            france = root / "guide-fr.xml"
            write_guide(
                guide,
                [("RTI1.ci@SD", "RTI 1")],
                [("RTI1.ci@SD", "Duplicate", now)],
            )
            write_guide(
                france,
                [("RTI1.ci@SD", "RTI 1")],
                [("RTI1.ci@SD", "Original", now)],
            )
            problems = validate.validate(guide, None, STATIONS, ALIASES, XTREAM, root)
            self.assertTrue(any("duplicates programmes" in problem for problem in problems), problems)

    def test_process_epg_profile_adds_the_exact_playlist_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "raw.xml"
            output = root / "final.xml"
            now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S +0000")
            later = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y%m%d%H%M%S +0000")
            write_guide(
                source,
                [("RTS1.sn@SD", "RTS")],
                [("RTS1.sn@SD", "Journal", now), ("RTS1.sn@SD", "Magazine", later)],
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(PROCESS_SCRIPT),
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--profile",
                    "af",
                    "--aliases",
                    str(ALIASES),
                    "--xtream-aliases",
                    str(XTREAM),
                    "--min-channels",
                    "1",
                    "--min-programmes",
                    "1",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            guide = ET.parse(output).getroot()
            names = [node.text for node in guide.find("channel").findall("display-name")]
            self.assertIn("AF RTS 1 -Senegal", names)
            self.assertEqual(len(guide.findall("programme")), 2)


if __name__ == "__main__":
    unittest.main()
