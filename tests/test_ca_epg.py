import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CA_SCRIPT = ROOT / "scripts" / "ca-epg.py"
VALIDATE_SCRIPT = ROOT / "scripts" / "ca_publish_validate.py"
PROCESS_SCRIPT = ROOT / "scripts" / "process-epg.py"
STATIONS = ROOT / "epg" / "ca-stations.json"
ALIASES = ROOT / "epg" / "aliases-ca.json"
XTREAM = ROOT / "epg" / "xtream-aliases-ca.json"

KEPT_APART = (
    "CA ABC HD",
    "CA ABC WEST",
    "CA CBS",
    "CA Cbc HD",
    "CA CTV 2",
    "CA CTV Vancouver 2 SD",
    "CA HBO 2",
    "CA SPORTSNET PPV",
    "CA Sportsnet News",
    "CA TVO Kids HD",
    "CA Global News Toronto",
    "Ca - Prime 1 4K",
    "Ca - Prime Classic 1 HD",
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ca_epg = load_module("ca_epg", CA_SCRIPT)


def write_channels(path: Path, rows: list[tuple[str, str, str, str]]) -> None:
    root = ET.Element("channels")
    for site, site_id, xmltv_id, name in rows:
        node = ET.SubElement(
            root,
            "channel",
            site=site,
            lang="en",
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


def source_ids(station: dict, site: str) -> list[str]:
    return [source["site_id"] for source in station["sources"] if source["site"] == site]


class CanadianTableTests(unittest.TestCase):
    def test_catalog_names_are_partitioned_without_overlap(self):
        stations, unmatched = ca_epg.load_table(STATIONS)
        names = [name for station in stations for name in station["names"]]
        unmatched_names = [row["name"] for row in unmatched]
        self.assertEqual(len(names) + len(unmatched_names), 246)
        self.assertEqual(len(set(names) | set(unmatched_names)), 246)
        self.assertFalse(set(names) & set(unmatched_names))
        self.assertEqual(json.loads(ALIASES.read_text(encoding="utf-8")), ca_epg.display_aliases(stations))
        self.assertEqual(json.loads(XTREAM.read_text(encoding="utf-8")), {})
        for name in KEPT_APART:
            self.assertIn(name, unmatched_names, name)
            self.assertNotIn(name, names)
        by_id = {station["id"]: station for station in stations}
        self.assertNotIn("West", source_ids(by_id["Crave1East.ca@HD"], "epgshare01.online")[0])
        self.assertNotIn("West", source_ids(by_id["HBOCanada1.ca@HD"], "epgshare01.online")[0])
        self.assertNotIn("Pacific", source_ids(by_id["CartoonNetwork.ca@HD"], "epgshare01.online")[0])
        self.assertNotIn("YTVP", source_ids(by_id["YTV.ca@HD"], "epgshare01.online")[0])
        regions = [
            source_ids(by_id[channel_id], "epgshare01.online")[0]
            for channel_id in (
                "SportsnetEast.ca@HD",
                "SportsnetOntario.ca@HD",
                "SportsnetPacific.ca@HD",
                "SportsnetWest.ca@HD",
            )
        ]
        self.assertEqual(len(regions), len(set(regions)))
        tsn = [source_ids(by_id[f"TSN{number}.ca@HD"], "epgshare01.online")[0] for number in range(1, 6)]
        self.assertEqual(len(tsn), len(set(tsn)))
        self.assertEqual(by_id["DisneyChannel.ca@HD"]["panel_ids"], ["disneychannel.ca"])
        self.assertEqual(by_id["NFLNetworkCanada.ca@HD"]["panel_ids"], ["nflnetworkcanada.ca"])
        self.assertNotIn("icitelevisionmontreal.ca", by_id["Max.ca@SD"]["panel_ids"])
        self.assertEqual(by_id["LoveNature.ca@SD"]["id"], "LoveNature.ca@SD")
        self.assertEqual(source_ids(by_id["CTVWild.ca@HD"], "epgshare01.online"), ["CA2#CTV.Wild.HD.ca2"])
        self.assertEqual(source_ids(by_id["CTVNature.ca@HD"], "epgshare01.online"), ["CA2#CTV.Nature.HD.ca2"])
        self.assertEqual(source_ids(by_id["CTVSpeed.ca@HD"], "epgshare01.online"), ["CA2#CTV.Speed.HD.ca2"])
        self.assertNotEqual(
            source_ids(by_id["CTVWild.ca@HD"], "epgshare01.online"),
            source_ids(by_id["WildTV.ca@SD"], "epgshare01.online"),
        )
        self.assertNotEqual(
            source_ids(by_id["CTVNature.ca@HD"], "epgshare01.online"),
            source_ids(by_id["DiscoveryChannel.ca@SD"], "epgshare01.online"),
        )
        self.assertEqual(source_ids(by_id["GlobalNewsBC.ca@HD"], "open-epg.com"), ["GlobalNewsBC1.ca"])
        self.assertEqual(source_ids(by_id["GlobalVancouver.ca@HD"], "epgshare01.online"), ["CA2#Global.BC.HD.ca2"])
        self.assertIn("CA BBC World News", by_id["BBCNewsNorthAmerica.ca@SD"]["names"])
        self.assertIn("BBCWORLDNEWS.ca", source_ids(by_id["BBCNewsNorthAmerica.ca@SD"], "open-epg.com"))
        self.assertNotIn("BBCWorldNews.ca@SD", by_id)
        self.assertEqual(source_ids(by_id["Z.ca@HD"], "epgshare01.online"), ["CA2#Z.HD.ca2"])
        self.assertEqual(source_ids(by_id["Temoin.ca@HD"], "epgshare01.online"), ["CA2#TÉMOIN.ca2"])
        self.assertNotIn("Zeste", source_ids(by_id["Z.ca@HD"], "epgshare01.online")[0])
        self.assertNotIn("Zeste", source_ids(by_id["Temoin.ca@HD"], "epgshare01.online")[0])

    def test_select_skips_a_station_already_programmed_elsewhere(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            occupied = root / "guide-nl.xml"
            selected = root / "selected.xml"
            write_guide(
                occupied,
                [("LoveNature.ca@SD", "Love Nature")],
                [("LoveNature.ca@SD", "From NL", "20261120090000 +0000")],
            )
            count = ca_epg.select_channels(None, selected, STATIONS, [occupied], "epgshare01.online")
            kept = {channel.get("site_id") for channel in ET.parse(selected).getroot().findall("channel")}
            self.assertNotIn("CA2#Love.Nature.ca2", kept)
            self.assertIn("CA2#TSN.1.ca2", kept)
            self.assertIn("CA2#TSN.2.HD.ca2", kept)
            self.assertGreater(count, 100)

    def test_merge_keeps_regional_feeds_apart_and_reuses_shared_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "epgshare.channels.xml"
            guide = root / "epgshare.xml"
            netherlands = root / "guide-nl.xml"
            output = root / "guide-ca.xml"
            write_channels(
                catalog,
                [
                    ("epgshare01.online", "CA2#TSN.1.ca2", "CA2#TSN.1.ca2", "TSN 1"),
                    ("epgshare01.online", "CA2#TSN.2.HD.ca2", "CA2#TSN.2.HD.ca2", "TSN 2"),
                    ("epgshare01.online", "CA2#Crave1.HD.ca2", "CA2#Crave1.HD.ca2", "Crave 1"),
                    ("epgshare01.online", "CA2#Love.Nature.ca2", "CA2#Love.Nature.ca2", "Love Nature"),
                    ("epgshare01.online", "CA2#Disney.Channel.Canada.HD.ca2", "CA2#Disney.Channel.Canada.HD.ca2", "Disney"),
                ],
            )
            write_guide(
                guide,
                [
                    ("CA2#TSN.1.ca2", "TSN 1"),
                    ("CA2#TSN.2.HD.ca2", "TSN 2"),
                    ("CA2#Crave1.HD.ca2", "Crave 1"),
                    ("CA2#Love.Nature.ca2", "Love Nature"),
                    ("CA2#Disney.Channel.Canada.HD.ca2", "Disney"),
                ],
                [
                    ("CA2#TSN.1.ca2", "TSN1 game", "20261120120000 +0000"),
                    ("CA2#TSN.2.HD.ca2", "TSN2 game", "20261120120000 +0000"),
                    ("CA2#Crave1.HD.ca2", "Crave east", "20261120120000 +0000"),
                    ("CA2#Love.Nature.ca2", "Should not repeat", "20261120120000 +0000"),
                    ("CA2#Disney.Channel.Canada.HD.ca2", "Disney show", "20261120120000 +0000"),
                ],
            )
            write_guide(
                netherlands,
                [("LoveNature.ca@SD", "Love Nature")],
                [("LoveNature.ca@SD", "From NL", "20261120080000 +0000")],
            )
            _channels, _programmes, stats = ca_epg.write_merged(
                [("epgshare", guide, catalog)],
                output,
                STATIONS,
                [netherlands],
                [],
            )
            merged = ET.parse(output).getroot()
            self.assertEqual(titles(merged, "TSN1.ca@HD"), ["TSN1 game"])
            self.assertEqual(titles(merged, "TSN2.ca@HD"), ["TSN2 game"])
            self.assertEqual(titles(merged, "Crave1East.ca@HD"), ["Crave east"])
            self.assertEqual(titles(merged, "LoveNature.ca@SD"), [])
            self.assertIn("LoveNature.ca@SD", [channel.get("id") for channel in merged.findall("channel")])
            self.assertEqual(titles(merged, "disneychannel.ca"), ["Disney show"])
            self.assertEqual(titles(merged, "DisneyChannel.ca@HD"), ["Disney show"])
            self.assertEqual(stats["shared"], 1)
            self.assertGreater(stats["grabbed"], 0)


class CanadianPublishTests(unittest.TestCase):
    def test_validator_rejects_a_second_schedule_on_a_shared_id(self):
        validate = load_module("ca_publish_validate", VALIDATE_SCRIPT)
        now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S +0000")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guide = root / "guide-ca.xml"
            netherlands = root / "guide-nl.xml"
            write_guide(
                guide,
                [("LoveNature.ca@SD", "Love Nature")],
                [("LoveNature.ca@SD", "Duplicate", now)],
            )
            write_guide(
                netherlands,
                [("LoveNature.ca@SD", "Love Nature")],
                [("LoveNature.ca@SD", "Original", now)],
            )
            problems = validate.validate(guide, None, STATIONS, ALIASES, XTREAM, root)
            self.assertTrue(any("duplicates programmes" in problem for problem in problems), problems)

    def test_process_epg_profile_adds_the_exact_playlist_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "raw.xml"
            output = root / "final.xml"
            now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S +0000")
            write_guide(source, [("CBCToronto.ca@HD", "CBC Toronto")], [("CBCToronto.ca@HD", "News", now)])
            completed = subprocess.run(
                [
                    sys.executable,
                    str(PROCESS_SCRIPT),
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--profile",
                    "ca",
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
            self.assertIn("CA CBC Toronto HD", names)
            self.assertEqual(len(guide.findall("programme")), 1)


if __name__ == "__main__":
    unittest.main()
