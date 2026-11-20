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
BE_SCRIPT = ROOT / "scripts" / "be-epg.py"
VALIDATE_SCRIPT = ROOT / "scripts" / "be_publish_validate.py"
PROCESS_SCRIPT = ROOT / "scripts" / "process-epg.py"
STATIONS = ROOT / "epg" / "be-stations.json"
ALIASES = ROOT / "epg" / "aliases-be.json"
XTREAM = ROOT / "epg" / "xtream-aliases-be.json"

CATALOG_NAMES = {
    "BE 192 TV",
    "BE 2BE",
    "BE AB EXPLORE",
    "BE AB1 HD",
    "BE AB3 HD",
    "BE ATV ANTWERPEN",
    "BE Acht",
    "BE BOOMERANG",
    "BE BX1",
    "BE CANAL ZOOM",
    "BE CAZ #",
    "BE CINEMA 1",
    "BE Canvas HD",
    "BE Club RTL",
    "BE EEN HD",
    "BE ELEVEN PRO LEAGUE 1 HD",
    "BE ELEVEN PRO LEAGUE 2 HD",
    "BE ELEVEN PRO LEAGUE 3 HD",
    "BE ELEVEN SPORT 3",
    "BE Eclips TV",
    "BE Eleven Sports 1 HD",
    "BE Eleven Sports 2 HD",
    "BE Evenaar",
    "BE Jim Jam",
    "BE KTO",
    "BE Kadet",
    "BE Ketnet",
    "BE Ketop12 HD",
    "BE LA UNE HD",
    "BE LN24",
    "BE La Trois HD",
    "BE Lord TV",
    "BE MATELE",
    "BE NOTELE",
    "BE NRJ Hits",
    "BE Nat Geo HD",
    "BE Petange",
    "BE Play Sports 1 HD (ONLY EVENTS)",
    "BE Play Sports 2 HD (ONLY EVENTS)",
    "BE Play Sports 4 HD (ONLY EVENTS)",
    "BE Play Sports 5 HD (ONLY EVENTS)",
    "BE Play Sports 6 HD (ONLY EVENTS)",
    "BE Plug RTL",
    "BE Q2 HD",
    "BE RTL Luxembourg HD",
    "BE RTL TVI HD",
    "BE RTL ZWEE",
    "BE SERIES",
    "BE TELE BRUXELLERS",
    "BE TELE SAMBRE",
    "BE TFX",
    "BE TIPIK HD",
    "BE TMC",
    "BE TV Lux",
    "BE TV OOST",
    "BE TVL",
    "BE TVO",
    "BE Tipik",
    "BE VICE",
    "BE VIJF TV",
    "BE VTM 2 HD",
    "BE VTM 3",
    "BE VTM 4",
    "BE VTM Gold",
    "BE VTM HD",
    "BE VTM KIDS",
    "BE Vier HD",
    "BE Vitaya HD",
    "BE Voo Sport 1",
    "BE Voo Sport 2",
    "BE Voo Sport World 1",
    "BE Voo Sport World 2",
    "BE Voo Sport World 3 HD",
    "BE XITE",
    "BE ZES",
}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


be_epg = load_module("be_epg", BE_SCRIPT)


def write_channels(path: Path, rows: list[tuple[str, str, str, str]]) -> None:
    root = ET.Element("channels")
    for site, site_id, xmltv_id, name in rows:
        node = ET.SubElement(
            root,
            "channel",
            site=site,
            lang="nl",
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
            stop="20261120130000 +0100",
        )
        ET.SubElement(programme, "title").text = title
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def titles(root: ET.Element, channel_id: str) -> list[str]:
    return [
        programme.findtext("title") or ""
        for programme in root.findall("programme")
        if programme.get("channel") == channel_id
    ]


class BelgianTableTests(unittest.TestCase):
    def test_catalog_names_are_partitioned_without_overlap(self):
        stations, unmatched = be_epg.load_table(STATIONS)
        names = [name for station in stations for name in station["names"]]
        unmatched_names = [row["name"] for row in unmatched]
        self.assertEqual(len(CATALOG_NAMES), 75)
        self.assertEqual(set(names) | set(unmatched_names), CATALOG_NAMES)
        self.assertEqual(len(names) + len(unmatched_names), 75)
        self.assertFalse(set(names) & set(unmatched_names))
        self.assertEqual(json.loads(ALIASES.read_text(encoding="utf-8")), be_epg.display_aliases(stations))
        self.assertEqual(json.loads(XTREAM.read_text(encoding="utf-8")), {})
        self.assertNotIn("BE TV OOST", names)
        self.assertNotIn("BE Voo Sport 1", names)
        self.assertNotIn("BE Jim Jam", names)
        self.assertIn("BE 2BE", names)
        self.assertIn("BE Q2 HD", names)
        self.assertIn("BE Vitaya HD", names)
        self.assertIn("BE Acht", names)
        by_id = {station["id"]: station for station in stations}
        self.assertEqual(
            [(source["site"], source["site_id"]) for source in by_id["BX1.be@SD"]["sources"]],
            [("tv-programme.telecablesat.fr", "382")],
        )
        self.assertEqual(by_id["TVLux.be@SD"]["sources"][0]["site"], "tv.post.lu")

    def test_select_keeps_belgian_targets_and_skips_shared_or_foreign_feeds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "telenet.tv.channels.xml"
            occupied = root / "guide-fr.xml"
            selected = root / "selected.xml"
            write_channels(
                catalog,
                [
                    ("telenet.tv", "vtmhd", "VTM.be@SD", "vtm HD"),
                    ("telenet.tv", "launehd", "LaUne.be@SD", "La Une HD"),
                    ("telenet.tv", "11footbetv", "", "DAZN Eleven Sports 1 FR"),
                    ("telenet.tv", "11football", "", "DAZN Eleven Sports 1"),
                    ("telenet.tv", "natgeofr", "", "Nat Geo FR"),
                    ("telenet.tv", "natgeohd", "", "Nat Geo HD"),
                    ("telenet.tv", "tf1hd", "TF1.fr@SD", "TF1 HD"),
                ],
            )
            write_guide(
                occupied,
                [("LaUne.be@SD", "La Une")],
                [("LaUne.be@SD", "From France", "20261120090000 +0100")],
            )
            count = be_epg.select_channels(catalog, selected, STATIONS, [occupied])
            kept = {
                (channel.get("site_id"), channel.get("xmltv_id"))
                for channel in ET.parse(selected).getroot().findall("channel")
            }
            self.assertEqual(count, 3)
            self.assertEqual(
                kept,
                {("vtmhd", "VTM.be@SD"), ("11football", ""), ("natgeohd", "")},
            )

    def test_merge_reuses_shared_ids_and_does_not_mix_feeds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            telenet_catalog = root / "telenet.channels.xml"
            vtm_catalog = root / "vtm.channels.xml"
            telenet_guide = root / "telenet.xml"
            vtm_guide = root / "vtm.xml"
            france = root / "guide-fr.xml"
            netherlands = root / "guide-nl.xml"
            output = root / "guide-be.xml"
            write_channels(
                telenet_catalog,
                [
                    ("telenet.tv", "vtmhd", "VTM.be@SD", "vtm HD"),
                    ("telenet.tv", "2behd", "VTM2.be@SD", "VTM 2"),
                    ("telenet.tv", "launehd", "LaUne.be@SD", "La Une HD"),
                    ("telenet.tv", "natgeohd", "", "Nat Geo HD"),
                ],
            )
            write_channels(vtm_catalog, [("vtm.be", "vtm", "VTM.be@SD", "VTM")])
            write_guide(
                telenet_guide,
                [
                    ("VTM.be@SD", "vtm HD"),
                    ("VTM2.be@SD", "VTM 2"),
                    ("LaUne.be@SD", "La Une HD"),
                    ("natgeohd", "Nat Geo HD"),
                ],
                [
                    ("VTM.be@SD", "Telenet noon", "20261120120000 +0100"),
                    ("VTM2.be@SD", "Q2 legacy", "20261120100000 +0100"),
                    ("LaUne.be@SD", "From Telenet", "20261120110000 +0100"),
                    ("natgeohd", "Belgian geo", "20261120140000 +0100"),
                ],
            )
            write_guide(
                vtm_guide,
                [("VTM.be@SD", "VTM")],
                [
                    ("VTM.be@SD", "Site noon", "20261120120000 +0100"),
                    ("VTM.be@SD", "Site later", "20261120150000 +0100"),
                ],
            )
            write_guide(
                france,
                [("LaUne.be@SD", "La Une"), ("RTVOost.nl@SD", "Oost")],
                [
                    ("LaUne.be@SD", "From France", "20261120080000 +0100"),
                    ("RTVOost.nl@SD", "Dutch regional", "20261120080000 +0100"),
                ],
            )
            write_guide(
                netherlands,
                [("Ketnet.be@Netherlands", "Ketnet")],
                [("Ketnet.be@Netherlands", "Dutch copy", "20261120080000 +0100")],
            )
            channels, programmes, stats = be_epg.write_merged(
                [
                    ("telenet", telenet_guide, telenet_catalog),
                    ("vtm", vtm_guide, vtm_catalog),
                ],
                output,
                STATIONS,
                [france, netherlands],
                [],
            )
            merged = ET.parse(output).getroot()
            ids = [channel.get("id") for channel in merged.findall("channel")]
            self.assertEqual(channels, len(ids))
            self.assertEqual(len(ids), len(set(ids)))
            self.assertIn("VTM.be@SD", ids)
            self.assertIn("vtm.be", ids)
            self.assertIn("VTM2.be@SD", ids)
            self.assertIn("vtm2.be", ids)
            self.assertIn("LaUne.be@SD", ids)
            self.assertIn("laune.be", ids)
            self.assertIn("NationalGeographic.be@HD", ids)
            self.assertNotIn("natgeohd", ids)
            self.assertNotIn("RTVOost.nl@SD", ids)
            self.assertNotIn("Ketnet.be@Netherlands", ids)
            self.assertNotIn("VOOsportWorld1.be@SD", ids)
            self.assertEqual(titles(merged, "VTM.be@SD"), ["Telenet noon", "Site later"])
            self.assertEqual(titles(merged, "vtm.be"), titles(merged, "VTM.be@SD"))
            self.assertEqual(titles(merged, "LaUne.be@SD"), [])
            self.assertEqual(titles(merged, "laune.be"), ["From France"])
            self.assertEqual(titles(merged, "NationalGeographic.be@HD"), ["Belgian geo"])
            vtm2 = next(channel for channel in merged.findall("channel") if channel.get("id") == "VTM2.be@SD")
            vtm2_names = [node.text for node in vtm2.findall("display-name")]
            self.assertEqual(vtm2_names.count("BE VTM 2 HD"), 1)
            self.assertIn("BE 2BE", vtm2_names)
            self.assertIn("BE Q2 HD", vtm2_names)
            self.assertEqual(stats["grabbed"], 3)
            self.assertEqual(stats["shared"], 1)
            self.assertGreater(programmes, 0)

    def test_french_and_dutch_guides_do_not_already_own_new_belgian_ids(self):
        france = ROOT / "guides" / "guide-fr.xml"
        netherlands = ROOT / "guides" / "guide-nl.xml"
        if not france.is_file() or not netherlands.is_file():
            self.skipTest("national guides are not checked out")
        occupied = be_epg.programmed_ids([france, netherlands])
        stations, _unmatched = be_epg.load_table(STATIONS)
        for station in stations:
            if not station.get("required"):
                continue
            self.assertNotIn(station["id"], occupied, station["id"])
            for source in station["sources"]:
                self.assertNotIn(source["site_id"], occupied, source["site_id"])
        # guide-fr lists LaUne.be@SD as a channel shell and currently has no programmes on it.
        self.assertNotIn("LaUne.be@SD", occupied)
        for shared in ("Play4.be@SD", "VRT1.be@SD", "TFX.fr@SD", "TMC.fr@SD"):
            self.assertIn(shared, occupied)


class BelgianPublishTests(unittest.TestCase):
    def test_validator_accepts_grabbed_channels_and_shared_panel_ids(self):
        stations, _unmatched = be_epg.load_table(STATIONS)
        validate = load_module("be_publish_validate", VALIDATE_SCRIPT)
        now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S +0000")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guide = root / "guide-be.xml"
            france = root / "guide-fr.xml"
            required = [station for station in stations if station.get("required")]
            channels = [(station["id"], station["names"][0]) for station in required]
            programmes = [
                (station["id"], f"{station['id']} {index}", now)
                for station in required
                for index in range(15)
            ]
            for station in required:
                for panel in station["panel_ids"]:
                    channels.append((panel, station["names"][0]))
                    programmes.extend((panel, f"{panel} {index}", now) for index in range(15))
            channels.append(("LaUne.be@SD", "La Une"))
            channels.append(("laune.be", "BE LA UNE HD"))
            programmes.append(("laune.be", "From France", now))
            write_guide(guide, channels, programmes)
            write_guide(
                france,
                [("LaUne.be@SD", "La Une")],
                [("LaUne.be@SD", "From France", now)],
            )
            problems = validate.validate(guide, None, STATIONS, ALIASES, XTREAM, root)
            self.assertEqual(problems, [], problems)

    def test_validator_rejects_a_second_schedule_on_a_shared_id(self):
        validate = load_module("be_publish_validate", VALIDATE_SCRIPT)
        now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S +0000")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guide = root / "guide-be.xml"
            france = root / "guide-fr.xml"
            write_guide(
                guide,
                [("LaUne.be@SD", "La Une")],
                [("LaUne.be@SD", "Duplicate", now)],
            )
            write_guide(
                france,
                [("LaUne.be@SD", "La Une")],
                [("LaUne.be@SD", "Original", now)],
            )
            problems = validate.validate(guide, None, STATIONS, ALIASES, XTREAM, root)
            self.assertTrue(any("duplicates programmes" in problem for problem in problems), problems)

    def test_process_epg_profile_adds_the_exact_playlist_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "raw.xml"
            output = root / "final.xml"
            now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S +0000")
            write_guide(source, [("VTM.be@SD", "vtm HD")], [("VTM.be@SD", "Nieuws", now)])
            completed = subprocess.run(
                [
                    sys.executable,
                    str(PROCESS_SCRIPT),
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--profile",
                    "be",
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
            names = [
                node.text
                for node in guide.find("channel").findall("display-name")
            ]
            self.assertIn("BE VTM HD", names)
            self.assertEqual(len(guide.findall("programme")), 1)


if __name__ == "__main__":
    unittest.main()
