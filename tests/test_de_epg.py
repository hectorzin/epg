import importlib.util
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DE_SCRIPT = ROOT / "scripts" / "de-epg.py"
MATCH_SCRIPT = ROOT / "scripts" / "de_catalog_match.py"
PROCESS_SCRIPT = ROOT / "scripts" / "process-epg.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


de_epg = load_module("de_epg", DE_SCRIPT)
match = load_module("de_catalog_match", MATCH_SCRIPT)
process_epg = load_module("process_epg", PROCESS_SCRIPT)


def write_guide(path, channels, programmes):
    root = ET.Element("tv")
    for channel_id, name in channels:
        channel = ET.SubElement(root, "channel", id=channel_id)
        ET.SubElement(channel, "url").text = "https://example.test"
        ET.SubElement(channel, "display-name").text = name
    for channel_id, title, start in programmes:
        programme = ET.SubElement(
            root,
            "programme",
            channel=channel_id,
            start=start,
            stop="20261119120000 +0100",
        )
        ET.SubElement(programme, "title").text = title
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


class GermanIdentityTests(unittest.TestCase):
    def test_quality_variants_share_a_signal_and_other_feeds_stay_apart(self):
        self.assertEqual(de_epg.identity_key("ZDF HD"), de_epg.identity_key("ZDF 4K"))
        self.assertEqual(de_epg.identity_key("DE ZDF HD"), de_epg.identity_key("ZDF"))
        self.assertEqual(de_epg.identity_key("ARD"), de_epg.identity_key("Das Erste"))
        self.assertNotEqual(de_epg.identity_key("ARD"), de_epg.identity_key("ARD-alpha"))
        self.assertNotEqual(
            de_epg.identity_key("National Geographic"),
            de_epg.identity_key("National Geographic (Sky)"),
        )
        self.assertNotEqual(de_epg.identity_key("NDR"), de_epg.identity_key("NDR Fernsehen Hamburg"))
        self.assertNotEqual(de_epg.identity_key("Comedy Central"), de_epg.identity_key("Comedy Central +1"))
        self.assertNotEqual(de_epg.identity_key("Sky Sport 1"), de_epg.identity_key("Sky Sport 10"))
        self.assertEqual(de_epg.station_key("Pro7"), de_epg.station_key("ProSieben"))
        self.assertEqual(de_epg.station_key("Kabel 1"), de_epg.station_key("Kabel Eins"))

    def test_numeric_magenta_id_uses_the_verified_xmltv_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guide = root / "magenta.xml"
            output = root / "out.xml"
            write_guide(
                guide,
                [("262264872014", "ZDF")],
                [("262264872014", "heute", "20261119010000 +0100")],
            )
            identities = {"site_ids": {"262264872014": "ZDF.de@SD"}, "stations": {"zdf": "ZDF.de@SD"}}
            de_epg.write_merged([("magenta", guide, None)], output, set(), identities=identities)
            merged = ET.parse(output).getroot()
            self.assertIsNotNone(merged.find("channel[@id='ZDF.de@SD']"))
            self.assertIsNone(merged.find("channel[@id='262264872014']"))
            self.assertEqual(merged.find("channel[@id='ZDF.de@SD']/display-name").text, "ZDF")
            tags = [node.tag for node in merged.find("channel[@id='ZDF.de@SD']")]
            self.assertEqual(tags[0], "display-name")
            self.assertLess(tags.index("display-name"), tags.index("url"))

    def test_occupied_id_is_rewritten_to_germany(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guide = root / "magenta.xml"
            output = root / "out.xml"
            write_guide(
                guide,
                [("ZDF.de@SD", "ZDF")],
                [("ZDF.de@SD", "heute", "20261119010000 +0100")],
            )
            de_epg.write_merged(
                [("magenta", guide, None)],
                output,
                {"ZDF.de@SD"},
                identities={"site_ids": {}, "stations": {}},
            )
            merged = ET.parse(output).getroot()
            self.assertIsNotNone(merged.find("channel[@id='ZDF.de@Germany']"))
            self.assertIsNone(merged.find("channel[@id='ZDF.de@SD']"))

    def test_incorrect_panel_id_is_not_published(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guide = root / "web.xml"
            output = root / "out.xml"
            write_guide(
                guide,
                [("vox.de", "VOX")],
                [("vox.de", "Show", "20261119010000 +0100")],
            )
            de_epg.write_merged(
                [("magentaweb", guide, None)],
                output,
                set(),
                identities={"site_ids": {}, "stations": {}},
            )
            ids = {channel.get("id") for channel in ET.parse(output).getroot().findall("channel")}
            self.assertNotIn("vox.de", ids)
            self.assertIn("VOX.de@SD", ids)

    def test_austrian_nick_is_dropped_and_orf_is_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guide = root / "tvheute.xml"
            output = root / "out.xml"
            write_guide(
                guide,
                [("NickelodeonAustria.at@SD", "NICK"), ("ORF1.at@SD", "ORF1")],
                [
                    ("NickelodeonAustria.at@SD", "Nick", "20261119010000 +0100"),
                    ("ORF1.at@SD", "Zeit im Bild", "20261119010000 +0100"),
                ],
            )
            de_epg.write_merged(
                [("tvheute", guide, None)],
                output,
                set(),
                identities={"site_ids": {}, "stations": {}},
            )
            ids = {channel.get("id") for channel in ET.parse(output).getroot().findall("channel")}
            self.assertEqual(ids, {"ORF1.at@SD"})

    def test_later_source_only_fills_empty_start_times(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            magenta = root / "magenta.xml"
            web = root / "web.xml"
            output = root / "out.xml"
            write_guide(
                magenta,
                [("100", "History")],
                [("100", "Magenta hour", "20261119010000 +0100")],
            )
            write_guide(
                web,
                [("History.de@SD", "The HISTORY Channel")],
                [
                    ("History.de@SD", "Web hour", "20261119010000 +0100"),
                    ("History.de@SD", "Web only", "20261119030000 +0100"),
                ],
            )
            identities = {
                "site_ids": {"100": "History.de@SD"},
                "stations": {"history": "History.de@SD"},
            }
            _channels, programmes, choices, _collisions = de_epg.write_merged(
                [("magenta", magenta, None), ("magentaweb", web, None)],
                output,
                set(),
                identities=identities,
            )
            titles = sorted(
                programme.findtext("title")
                for programme in ET.parse(output).getroot().findall("programme")
            )
            self.assertEqual(programmes, 2)
            self.assertEqual(titles, ["Magenta hour", "Web only"])
            self.assertEqual(choices["History.de@SD"]["name"], "History")

    def test_secondary_source_does_not_displace_a_covered_priority_identity(self):
        pairs = [
            ("492496936303", "Disney Channel", "Disney", "DisneyChannel.de@SD"),
            ("262277160060", "Super RTL", "RTLS", "RTLSuper.de@Germany"),
            ("389264936266", "Sky Cinema Premiere", "SKYci", "SkyCinemaPremieren.de@SD"),
            ("274350120288", "hr-fernsehen", "HR", "hrfernsehen.de@SD"),
            ("274350120291", "SWR Fernsehen BW", "SWR", "SWRFernsehenBadenWurttemberg.de@SD"),
            ("389265448072", "Sky Sport Top Event", "SKYsp1", "SkySport1.de@SD"),
            ("389264424237", "Sky Sport Bundesliga", "SKYbl", "SkySportBundesliga1.de@SD"),
        ]
        identities = {
            "site_ids": {
                "492496936303": "DisneyChannel.de@SD",
                "262277160060": "RTLSuper.de@SD",
                "389264936266": "SkyCinemaPremieren.de@SD",
                "274350120288": "hrfernsehen.de@SD",
                "274350120291": "SWRFernsehenBadenWurttemberg.de@SD",
                "389265448072": "SkySport1.de@SD",
                "389264424237": "SkySportBundesliga1.de@SD",
            },
            "stations": {},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            magenta = root / "magenta.xml"
            secondary = root / "tvheute.xml"
            output = root / "out.xml"
            write_guide(
                magenta,
                [(site_id, name) for site_id, name, _short, _published in pairs],
                [
                    (site_id, f"{name} programme", "20261119010000 +0100")
                    for site_id, name, _short, _published in pairs
                ],
            )
            write_guide(
                secondary,
                [(published if published != "RTLSuper.de@Germany" else "RTLSuper.de@SD", short) for _site, _name, short, published in pairs],
                [
                    (
                        published if published != "RTLSuper.de@Germany" else "RTLSuper.de@SD",
                        f"{short} programme",
                        "20261119020000 +0100",
                    )
                    for _site, _name, short, published in pairs
                ],
            )
            hints = {
                de_epg.identity_key("Disney"): "DisneyChannel.de@SD",
                de_epg.identity_key("Disney Channel"): "DisneyChannel.de@Germany",
            }
            _channels, _programmes, choices, collisions = de_epg.write_merged(
                [("magenta", magenta, None), ("tvheute", secondary, None)],
                output,
                {"RTLSuper.de@SD"},
                canonical_hints=hints,
                identities=identities,
            )
            merged = ET.parse(output).getroot()
            names = {
                channel.get("id"): channel.findtext("display-name")
                for channel in merged.findall("channel")
            }
            for _site, name, short, published in pairs:
                self.assertEqual(names.get(published), name, published)
                self.assertNotIn(short, names.values(), short)
                self.assertEqual(choices[published]["identity_source"], "magenta")
            dropped = {row["name"] for row in collisions if row.get("rewritten_id") == "dropped"}
            self.assertEqual(dropped, {short for _site, _name, short, _published in pairs})

    def test_same_source_stations_that_share_an_id_both_remain(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            magenta = root / "magenta.xml"
            output = root / "out.xml"
            write_guide(
                magenta,
                [("8", "Sky Sport 8"), ("10", "Sky Sport 10")],
                [
                    ("8", "Match 8", "20261119010000 +0100"),
                    ("10", "Match 10", "20261119010000 +0100"),
                ],
            )
            de_epg.write_merged(
                [("magenta", magenta, None)],
                output,
                set(),
                identities={"site_ids": {"8": "SkySport10.de@SD"}, "stations": {}},
            )
            merged = ET.parse(output).getroot()
            names = {
                channel.get("id"): channel.findtext("display-name")
                for channel in merged.findall("channel")
            }
            self.assertEqual(names.get("SkySport10.de@SD"), "Sky Sport 8")
            self.assertIn("Sky Sport 10", names.values())
            self.assertNotEqual(
                next(channel_id for channel_id, name in names.items() if name == "Sky Sport 10"),
                "SkySport10.de@SD",
            )

    def test_uncovered_identity_still_accepts_the_secondary_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            magenta = root / "magenta.xml"
            secondary = root / "tvheute.xml"
            output = root / "out.xml"
            write_guide(
                magenta,
                [("100", "Disney Channel")],
                [("100", "Sendepause", "20261119010000 +0100")],
            )
            write_guide(
                secondary,
                [("DisneyChannel.de@SD", "Disney")],
                [("DisneyChannel.de@SD", "Bluey", "20261119020000 +0100")],
            )
            de_epg.write_merged(
                [("magenta", magenta, None), ("tvheute", secondary, None)],
                output,
                set(),
                identities={"site_ids": {"100": "DisneyChannel.de@SD"}, "stations": {}},
            )
            merged = ET.parse(output).getroot()
            self.assertEqual(
                merged.find("channel[@id='DisneyChannel.de@SD']/display-name").text,
                "Disney",
            )

    def test_select_skips_a_covered_identity_and_duplicate_site(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "channels.xml"
            covered = root / "covered.xml"
            output = root / "selected.xml"
            ET.ElementTree(
                ET.fromstring(
                    """
                    <channels>
                      <channel site="www.magenta.tv" site_id="1" xmltv_id="">ZDF</channel>
                      <channel site="www.magenta.tv" site_id="2" xmltv_id="">ZDF</channel>
                      <channel site="www.magenta.tv" site_id="3" xmltv_id="">RTL</channel>
                      <channel site="tvheute.at" site_id="9" xmltv_id="ProSiebenAustria.at@SD">ProSieben</channel>
                    </channels>
                    """
                )
            ).write(catalog, encoding="utf-8", xml_declaration=True)
            write_guide(
                covered,
                [("ZDF.de@SD", "ZDF")],
                [("ZDF.de@SD", "heute", "20261119010000 +0100")],
            )
            count = de_epg.select_channels(catalog, output, covered_guides=[covered])
            selected = ET.parse(output).getroot()
            site_ids = [channel.get("site_id") for channel in selected.findall("channel")]
            self.assertEqual(count, 1)
            self.assertEqual(site_ids, ["3"])

    def test_reliable_clone_and_rejected_shared_id(self):
        root = ET.fromstring(
            """
            <tv>
              <channel id="ZDF.de@SD"><display-name>ZDF</display-name></channel>
              <channel id="Vox.de@SD"><display-name>VOX</display-name></channel>
              <channel id="VOXup.de@SD"><display-name>VOXup</display-name></channel>
              <channel id="RTL.de@SD"><display-name>RTL</display-name></channel>
              <programme channel="ZDF.de@SD" start="20261119010000 +0100" stop="20261119020000 +0100"><title>heute</title></programme>
              <programme channel="Vox.de@SD" start="20261119010000 +0100" stop="20261119020000 +0100"><title>a</title></programme>
              <programme channel="VOXup.de@SD" start="20261119010000 +0100" stop="20261119020000 +0100"><title>b</title></programme>
              <programme channel="RTL.de@SD" start="20261119010000 +0100" stop="20261119020000 +0100"><title>c</title></programme>
            </tv>
            """
        )
        streams = [
            {"name": "DE ZDF HD", "epg_id": "zdf.de"},
            {"name": "DE ZDF 4K", "epg_id": "zdf.de"},
            {"name": "DE Vox HD", "epg_id": "vox.de"},
            {"name": "DE VOXUP", "epg_id": "vox.de"},
            {"name": "DE RTL 4K", "epg_id": "deutschewelle.de"},
            {"name": "DE RTL HD", "epg_id": None},
        ]
        aliases, clones = match.build_alias_maps(root, streams, occupied_ids=set())
        self.assertEqual(clones["zdf.de"], "ZDF.de@SD")
        self.assertNotIn("vox.de", clones)
        self.assertNotIn("deutschewelle.de", clones)
        self.assertNotIn("123456", clones)
        names = [name for bucket in aliases.values() for name in bucket]
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("DE ZDF HD", aliases["ZDF.de@SD"])
        self.assertIn("DE ZDF 4K", aliases["ZDF.de@SD"])
        self.assertIn("DE RTL 4K", aliases["RTL.de@SD"])
        self.assertNotIn("DE Vox HD", aliases["VOXup.de@SD"])

    def test_profile_de_appends_xtream_names_after_the_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "raw.xml"
            output = root / "final.xml"
            aliases = root / "aliases.json"
            xtream = root / "xtream.json"
            write_guide(
                source,
                [("ZDF.de@Germany", "ZDF")],
                [("ZDF.de@Germany", "heute", "20261119010000 +0100")],
            )
            aliases.write_text(json.dumps({"ZDF.de@Germany": ["DE ZDF HD", "DE ZDF 4K"]}), encoding="utf-8")
            xtream.write_text(json.dumps({"zdf.de": "ZDF.de@Germany"}), encoding="utf-8")
            import sys
            from unittest.mock import patch

            argv = [
                "process-epg.py",
                "--input",
                str(source),
                "--output",
                str(output),
                "--aliases",
                str(aliases),
                "--xtream-aliases",
                str(xtream),
                "--profile",
                "de",
                "--min-channels",
                "1",
                "--min-programmes",
                "1",
            ]
            with patch.object(sys, "argv", argv):
                self.assertEqual(process_epg.main(), 0)
            merged = ET.parse(output).getroot()
            original = merged.find("channel[@id='ZDF.de@Germany']")
            names = [node.text for node in original.findall("display-name")]
            self.assertEqual(names[0], "ZDF")
            self.assertEqual(names[1:], ["DE ZDF HD", "DE ZDF 4K"])
            tags = [node.tag for node in original]
            self.assertLess(tags.index("display-name"), tags.index("url"))
            clone = merged.find("channel[@id='zdf.de']")
            self.assertEqual([node.text for node in clone.findall("display-name")], names)
            self.assertEqual(
                merged.find("programme[@channel='zdf.de']/title").text,
                "heute",
            )


class GermanAliasFileTests(unittest.TestCase):
    def test_committed_aliases_do_not_reuse_unsafe_ids(self):
        aliases = json.loads((ROOT / "epg" / "aliases-de.json").read_text(encoding="utf-8"))
        clones = json.loads((ROOT / "epg" / "xtream-aliases-de.json").read_text(encoding="utf-8"))
        self.assertTrue(aliases)
        self.assertTrue(clones)
        seen = {}
        for channel_id, names in aliases.items():
            self.assertFalse(de_epg.is_incorrect_panel_id(channel_id), channel_id)
            self.assertFalse(de_epg.NUMERIC_ID_RE.fullmatch(channel_id), channel_id)
            for name in names:
                self.assertNotIn(name, seen, name)
                seen[name] = channel_id
        for alias_id, original_id in clones.items():
            self.assertNotIn(alias_id.casefold(), de_epg.INCORRECT_IDS)
            self.assertFalse(alias_id.isdigit(), alias_id)
            self.assertNotIn(alias_id.casefold(), {"null", "none", "undefined"})
            self.assertNotEqual(alias_id, original_id)
            owners = [channel_id for channel_id, names in aliases.items() if channel_id == original_id]
            self.assertTrue(owners or original_id, original_id)
        curated = {
            "WeltderWunderTV.de@SD": "DE WELT DER WUNDER TV",
            "BabyTV.de@SD": "DE baby",
            "WDR.de@SD": "DE Wdr Tv",
            "MDRFernsehenSachsen.de@SD": "DE MDR SACHSEN HD",
            "RAN1.de@SD": "DE Ran 1Tv",
            "RBW.de@SD": "DE Rbw Tv",
            "Rally.TV.de": "DAZN RALLY TV",
        }
        for channel_id, title in curated.items():
            self.assertIn(title, aliases[channel_id])
        self.assertEqual(clones["weltderwunder.de"], "WeltderWunderTV.de@SD")
        self.assertEqual(clones["babytv.de"], "BabyTV.de@SD")
        self.assertEqual(clones["wdr.de"], "WDR.de@SD")
        self.assertEqual(clones["mdrsachsen.de"], "MDRFernsehenSachsen.de@SD")
        for incorrect in de_epg.INCORRECT_IDS:
            self.assertNotIn(incorrect, clones)
            self.assertNotIn(incorrect, aliases)

    def test_shared_rally_id_is_kept_when_occupied_by_spain(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guide = root / "epgshare.xml"
            output = root / "out.xml"
            write_guide(
                guide,
                [("Rally.TV.de", "Rally TV")],
                [("Rally.TV.de", "Season Review - WRC 2026", "20261120090028 +0000")],
            )
            de_epg.write_merged(
                [("epgshare", guide, None)],
                output,
                {"Rally.TV.de"},
                identities={"site_ids": {}, "stations": {}},
            )
            merged = ET.parse(output).getroot()
            ids = {channel.get("id") for channel in merged.findall("channel")}
            self.assertEqual(ids, {"Rally.TV.de"})
            self.assertEqual(merged.find("channel[@id='Rally.TV.de']/display-name").text, "Rally TV")

    def test_epgshare_is_lowest_priority_source(self):
        self.assertEqual(de_epg.SOURCE_PRIORITY["epgshare"], 1)
        self.assertLess(de_epg.SOURCE_PRIORITY["epgshare"], de_epg.SOURCE_PRIORITY["tvheute"])
        self.assertEqual(de_epg.SHARED_XMLTV_IDS, frozenset({"Rally.TV.de"}))


if __name__ == "__main__":
    unittest.main()
