import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TR_SCRIPT = ROOT / "scripts" / "tr-epg.py"
MATCH_SCRIPT = ROOT / "scripts" / "tr_catalog_match.py"
PROCESS_SCRIPT = ROOT / "scripts" / "process-epg.py"
PUBLIC_SCRIPT = ROOT / "scripts" / "grab_tr_public.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tr_epg = load_module("tr_epg", TR_SCRIPT)
match = load_module("tr_catalog_match", MATCH_SCRIPT)
public = load_module("grab_tr_public", PUBLIC_SCRIPT)


def write_guide(path, channels, programmes):
    root = ET.Element("tv")
    for channel_id, name in channels:
        channel = ET.SubElement(root, "channel", id=channel_id)
        ET.SubElement(channel, "display-name", lang="tr").text = name
    for channel_id, title, start in programmes:
        programme = ET.SubElement(
            root,
            "programme",
            channel=channel_id,
            start=start,
            stop="20261120120000 +0300",
        )
        title_node = ET.SubElement(programme, "title", lang="tr")
        title_node.text = title
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


class TurkishIdentityTests(unittest.TestCase):
    def test_turkish_letters_quality_and_distinct_feeds(self):
        self.assertEqual(tr_epg.identity_key("TRT ÇOCUK"), tr_epg.identity_key("TR TRT COCUK HD"))
        self.assertEqual(tr_epg.identity_key("DİYANET TV"), tr_epg.identity_key("Diyanet TV"))
        self.assertEqual(tr_epg.identity_key("TRT HABER"), tr_epg.identity_key("TR TRT HABER1080p"))
        self.assertEqual(tr_epg.identity_key("beIN SPORTS 1"), tr_epg.identity_key("TR BEINSPOR 1 HD"))
        self.assertEqual(tr_epg.identity_key("TR BEINSPOR 1 HD"), tr_epg.identity_key("Beinsports"))
        self.assertNotEqual(tr_epg.identity_key("Beinsports"), tr_epg.identity_key("TR BEINSPORT MAX 1 HD"))
        self.assertEqual(tr_epg.identity_key("TR DREAM TV H*"), tr_epg.identity_key("DREAM TÜRK"))
        self.assertEqual(tr_epg.identity_key("TR EKOTURK TV H*"), tr_epg.identity_key("Ekotürk"))
        self.assertEqual(tr_epg.identity_key("TR LALEGUL TV"), tr_epg.identity_key("Lâlegül"))
        self.assertEqual(tr_epg.identity_key("TR TMB TV A*"), tr_epg.identity_key("Tmb"))
        self.assertEqual(tr_epg.identity_key("TR EURO D*"), tr_epg.identity_key("Euro D"))
        self.assertEqual(tr_epg.identity_key("TR NR1 TURK TV HD*"), tr_epg.identity_key("NUMBER1 TURK"))
        self.assertEqual(tr_epg.identity_key("TR NR1 TV HD*"), tr_epg.identity_key("NUMBER1 TV"))
        self.assertEqual(tr_epg.identity_key("TR SEMERKAND TV"), tr_epg.identity_key("SEMERKAND"))
        self.assertNotEqual(tr_epg.identity_key("TR NR1 TURK TV"), tr_epg.identity_key("NR1 DAMAR"))
        self.assertNotEqual(tr_epg.identity_key("TR SHOW TURK"), tr_epg.identity_key("Show"))
        self.assertEqual(tr_epg.identity_key("beIN SPORTS 1"), tr_epg.identity_key("TR BEINSPORT 1 SD"))
        self.assertNotEqual(tr_epg.identity_key("beIN SPORTS 1"), tr_epg.identity_key("beIN SPORTS 2"))
        self.assertNotEqual(tr_epg.identity_key("beIN SPORTS 1"), tr_epg.identity_key("beIN SPORTS HABER"))
        self.assertNotEqual(tr_epg.identity_key("beIN SPORTS 1"), tr_epg.identity_key("beIN SPORTS MAX 1"))
        self.assertEqual(tr_epg.identity_key("S SPORT"), tr_epg.identity_key("TR S SPORTS TV HD"))
        self.assertNotEqual(tr_epg.identity_key("S SPORT"), tr_epg.identity_key("S SPORT 2"))
        self.assertEqual(tr_epg.identity_key("FOX"), tr_epg.identity_key("NOW"))
        self.assertEqual(tr_epg.identity_key("TR FOX TV HD"), tr_epg.identity_key("NOW"))
        self.assertNotEqual(tr_epg.identity_key("FOX"), tr_epg.identity_key("FOX SPORTS"))
        self.assertNotEqual(tr_epg.identity_key("TV8"), tr_epg.identity_key("TV 8.5"))
        self.assertNotEqual(tr_epg.identity_key("TRT SPOR"), tr_epg.identity_key("TRT SPOR YILDIZ"))
        self.assertNotEqual(tr_epg.identity_key("TRT 1"), tr_epg.identity_key("TRT 2"))
        self.assertEqual(tr_epg.identity_key("TRT 3 / TRT SPOR"), tr_epg.identity_key("TRT 3 - SPOR"))
        self.assertNotEqual(tr_epg.identity_key("TRT SPOR"), tr_epg.identity_key("TRT 3 - SPOR"))
        self.assertTrue(tr_epg.is_separator("TR *** T R D i N i ***"))
        self.assertFalse(tr_epg.is_separator("TRT 1"))

    def test_occupied_turkish_id_is_rewritten_and_foreign_ids_are_not_published(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            digiturk = root / "digiturk.xml"
            output = root / "out.xml"
            occupied = root / "guide-nl.xml"
            write_guide(
                digiturk,
                [("TRTTurk.tr@SD", "TRT TÜRK"), ("Rai1.it@SD", "RAI 1")],
                [
                    ("TRTTurk.tr@SD", "Ana Haber", "20261120090000 +0300"),
                    ("Rai1.it@SD", "Telegiornale", "20261120090000 +0300"),
                ],
            )
            write_guide(
                occupied,
                [("TRTTurk.tr@SD", "TRT Turk")],
                [("TRTTurk.tr@SD", "Nederlands", "20261120090000 +0100")],
            )
            tr_epg.write_merged(
                [("digiturk", digiturk, None)],
                output,
                tr_epg.collect_occupied([occupied]),
            )
            merged = ET.parse(output).getroot()
            ids = {channel.get("id") for channel in merged.findall("channel")}
            self.assertIn("TRTTurk.tr@Turkey", ids)
            self.assertNotIn("TRTTurk.tr@SD", ids)
            self.assertNotIn("Rai1.it@SD", ids)
            self.assertTrue(all(str(channel_id).endswith(".tr@SD") or str(channel_id).endswith(".tr@Turkey") for channel_id in ids))
            rai = [channel for channel in merged.findall("channel") if channel.findtext("display-name") == "RAI 1"]
            self.assertEqual(len(rai), 1)
            self.assertTrue(rai[0].get("id").endswith(".tr@SD"))
            titles = [programme.findtext("title") for programme in merged.findall("programme")]
            self.assertEqual(sorted(titles), ["Ana Haber", "Telegiornale"])

    def test_numeric_leading_turkish_ids_stay_canonical(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "dsmart.xml"
            output = root / "out.xml"
            write_guide(
                source,
                [("24TV.tr@SD", "24"), ("360.tr@SD", "360"), ("930", "Show")],
                [
                    ("24TV.tr@SD", "Gece", "20261120010000 +0300"),
                    ("360.tr@SD", "Muzik", "20261120010000 +0300"),
                    ("930", "Dizi", "20261120010000 +0300"),
                ],
            )
            tr_epg.write_merged([("dsmart", source, None)], output, set())
            ids = {channel.get("id") for channel in ET.parse(output).getroot().findall("channel")}
            self.assertIn("24TV.tr@SD", ids)
            self.assertIn("360.tr@SD", ids)
            self.assertNotIn("930", ids)
            self.assertTrue(all(tr_epg.is_published_id(channel_id) for channel_id in ids))

    def test_higher_priority_programme_wins_the_same_start(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            digiturk = root / "digiturk.xml"
            share = root / "share.xml"
            output = root / "out.xml"
            write_guide(
                digiturk,
                [("ATV.tr@SD", "ATV")],
                [("ATV.tr@SD", "Digiturk haber", "20261120080000 +0300")],
            )
            write_guide(
                share,
                [("ATV.HD.tr", "ATV HD")],
                [
                    ("ATV.HD.tr", "EPGShare haber", "20261120080000 +0300"),
                    ("ATV.HD.tr", "Daha sonra", "20261120100000 +0300"),
                ],
            )
            tr_epg.write_merged(
                [("digiturk", digiturk, None), ("epgshare", share, None)],
                output,
                set(),
            )
            merged = ET.parse(output).getroot()
            self.assertIsNotNone(merged.find("channel[@id='ATV.tr@SD']"))
            titles = [programme.findtext("title") for programme in merged.findall("programme")]
            self.assertEqual(titles, ["Digiturk haber", "Daha sonra"])

    def test_exact_xtream_names_and_panel_clone(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guide = root / "guide.xml"
            catalog = root / "catalog.json"
            write_guide(
                guide,
                [("ATV.tr@SD", "ATV"), ("BeINSports1.tr@SD", "beIN SPORTS 1"), ("BeINSports2.tr@SD", "beIN SPORTS 2")],
                [
                    ("ATV.tr@SD", "Haber", "20261120080000 +0300"),
                    ("BeINSports1.tr@SD", "Maç", "20261120080000 +0300"),
                    ("BeINSports2.tr@SD", "Maç 2", "20261120080000 +0300"),
                ],
            )
            catalog.write_text(
                json.dumps(
                    [
                        {"xtream_id": "1", "name": "TR ATV HD", "epg_id": "atv.tr", "category": "[TR] TURKEY"},
                        {"xtream_id": "2", "name": "TR ATV*", "epg_id": "atv.tr", "category": "[TR] TURKEY"},
                        {"xtream_id": "3", "name": "TR BEINSPORT 1 HD", "epg_id": "", "category": "[TR] TURKEY"},
                        {"xtream_id": "4", "name": "TR BEINSPORT 2 HD", "epg_id": "beinsports2.tr", "category": "[TR] TURKEY"},
                    ]
                ),
                encoding="utf-8",
            )
            streams = match.load_streams(catalog)
            aliases, clones = match.build_alias_maps(ET.parse(guide).getroot(), streams, set())
            self.assertEqual(aliases["ATV.tr@SD"], ["TR ATV HD", "TR ATV*"])
            self.assertEqual(clones["atv.tr"], "ATV.tr@SD")
            self.assertEqual(clones["beinsports2.tr"], "BeINSports2.tr@SD")
            self.assertIn("TR BEINSPORT 1 HD", aliases["BeINSports1.tr@SD"])
            self.assertNotIn("TR BEINSPORT 2 HD", aliases["BeINSports1.tr@SD"])

    def test_process_epg_accepts_the_turkish_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "raw.xml"
            output = root / "final.xml"
            aliases = root / "aliases.json"
            clones = root / "xtream.json"
            write_guide(
                source,
                [("ATV.tr@SD", "ATV")],
                [("ATV.tr@SD", "Haber", "20261120080000 +0300")],
            )
            aliases.write_text(json.dumps({"ATV.tr@SD": ["TR ATV HD"]}), encoding="utf-8")
            clones.write_text(json.dumps({"atv.tr": "ATV.tr@SD"}), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(PROCESS_SCRIPT),
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--profile",
                    "tr",
                    "--aliases",
                    str(aliases),
                    "--xtream-aliases",
                    str(clones),
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
            final = ET.parse(output).getroot()
            names = [node.text for node in final.find("channel[@id='ATV.tr@SD']").findall("display-name")]
            self.assertIn("TR ATV HD", names)
            self.assertIsNotNone(final.find("channel[@id='atv.tr']"))
            self.assertEqual(final.find("programme[@channel='atv.tr']/title").text, "Haber")

    def test_dsmart_timestamp_matches_the_upstream_offset(self):
        programmes = public.dsmart_programmes(
            [
                {
                    "day": "2026-11-19T21:00:00Z",
                    "start_date": "2026-11-16T22:30:00Z",
                    "duration": "1:45:00",
                    "program_name": "Şeytanla Bir Gece",
                    "description": "Açıklama",
                    "genre": "sinema/korku-gerilim",
                }
            ]
        )
        self.assertEqual(len(programmes), 1)
        self.assertEqual(public.xmltv_stamp(programmes[0]["start"]), "20261120013000 +0300")
        self.assertEqual(public.xmltv_stamp(programmes[0]["stop"]), "20261120031500 +0300")
        self.assertEqual(programmes[0]["title"], "Şeytanla Bir Gece")
        self.assertEqual(programmes[0]["categories"], ["Sinema", "Korku-gerilim"])

    def test_turksat_clock_crosses_midnight_in_istanbul(self):
        programmes = public.turksat_programmes(
            [
                {"b": "Gece", "c": "23:00", "d": "01:00"},
                {"b": "Sabah", "c": "01:00", "d": "06:00"},
            ],
            datetime(2026, 11, 20).date(),
        )
        self.assertEqual(public.xmltv_stamp(programmes[0]["start"]), "20261120230000 +0300")
        self.assertEqual(public.xmltv_stamp(programmes[0]["stop"]), "20261121010000 +0300")
        self.assertEqual(public.xmltv_stamp(programmes[1]["start"]), "20261121010000 +0300")

    def test_turksat_intermediate_url_is_limited_to_globalsign(self):
        der = b"http://evil.example/a.crt http://secure.globalsign.com/cacert/gsgccr46alphasslca2025.crt"
        self.assertEqual(
            public.aia_crt_urls(der),
            ["http://secure.globalsign.com/cacert/gsgccr46alphasslca2025.crt"],
        )
        self.assertTrue(public.issuer_missing(OSError("certificate verify failed: unable to get local issuer certificate")))
        self.assertFalse(public.issuer_missing(OSError("timed out")))

    def test_tvplus_clock_is_already_istanbul(self):
        when = public.tvplus_when("2026-11-20 02:57:00 UTC+03:00")
        self.assertEqual(public.xmltv_stamp(when), "20261120025700 +0300")

    def test_published_id_keeps_its_spelling_and_current_programmes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = root / "guide-tr.xml"
            current = root / "tvplus.xml"
            output = root / "out.xml"
            write_guide(
                previous,
                [
                    ("AKITTV.tr@SD", "AKİT TV"),
                    ("DaVinci.tr@SD", "Da Vinci"),
                    ("EkolTV.tr@SD", "Ekol TV"),
                    ("KibrisGencTV.tr@SD", "Kıbrıs Genç TV"),
                ],
                [
                    ("AKITTV.tr@SD", "caducado", "20261120070000 +0300"),
                    ("DaVinci.tr@SD", "caducado", "20261120070000 +0300"),
                    ("EkolTV.tr@SD", "caducado", "20261120070000 +0300"),
                    ("KibrisGencTV.tr@SD", "caducado", "20261120070000 +0300"),
                ],
            )
            tree = ET.parse(previous)
            for channel in tree.getroot().findall("channel"):
                if channel.get("id") == "DaVinci.tr@SD":
                    ET.SubElement(channel, "icon", src="https://example.test/davinci.png")
            tree.write(previous, encoding="utf-8", xml_declaration=True)
            write_guide(
                current,
                [
                    ("AkitTV.tr@SD", "AKIT TV"),
                    ("DaVinci.de@SD", "DA VINCI"),
                    ("4355", "EKOL TV"),
                    ("KibrisGencTV.cy@SD", "KIBRIS GENC TV"),
                ],
                [
                    ("AkitTV.tr@SD", "bülten", "20261120080000 +0300"),
                    ("DaVinci.de@SD", "resim", "20261120080000 +0300"),
                    ("4355", "ekol haber", "20261120080000 +0300"),
                    ("KibrisGencTV.cy@SD", "genç", "20261120080000 +0300"),
                ],
            )
            tr_epg.write_merged([("tvplus", current, None)], output, set(), [previous])
            merged = ET.parse(output).getroot()
            ids = {channel.get("id") for channel in merged.findall("channel")}
            self.assertEqual(
                ids,
                {"AKITTV.tr@SD", "DaVinci.tr@SD", "EkolTV.tr@SD", "KibrisGencTV.tr@SD"},
            )
            titles = {programme.findtext("title") for programme in merged.findall("programme")}
            self.assertEqual(titles, {"bülten", "resim", "ekol haber", "genç"})
            davinci = merged.find("channel[@id='DaVinci.tr@SD']")
            self.assertEqual(davinci.find("icon").get("src"), "https://example.test/davinci.png")
            self.assertEqual(
                {programme.get("channel") for programme in merged.findall("programme")},
                ids,
            )

    def test_short_minted_id_does_not_replace_a_published_one(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = root / "guide-tr.xml"
            current = root / "turksat.xml"
            output = root / "out.xml"
            write_guide(
                previous,
                [("24TV.tr@SD", "24"), ("TRT4K.tr@SD", "TRT 4K")],
                [
                    ("24TV.tr@SD", "caducado", "20261120010000 +0300"),
                    ("TRT4K.tr@SD", "caducado", "20261120010000 +0300"),
                ],
            )
            write_guide(
                current,
                [("24.tr@SD", "24"), ("8801", "TRT 4K")],
                [
                    ("24.tr@SD", "gece", "20261120020000 +0300"),
                    ("8801", "belgesel", "20261120020000 +0300"),
                ],
            )
            tr_epg.write_merged([("turksat", current, None)], output, set(), [previous])
            merged = ET.parse(output).getroot()
            ids = {channel.get("id") for channel in merged.findall("channel")}
            self.assertEqual(ids, {"24TV.tr@SD", "TRT4K.tr@SD"})
            titles = {programme.findtext("title") for programme in merged.findall("programme")}
            self.assertEqual(titles, {"gece", "belgesel"})

    def test_occupied_rewrite_is_not_moved_back(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = root / "guide-tr.xml"
            current = root / "digiturk.xml"
            occupied = root / "guide-nl.xml"
            output = root / "out.xml"
            write_guide(
                previous,
                [("TRTTurk.tr@Turkey", "TRT TÜRK")],
                [("TRTTurk.tr@Turkey", "caducado", "20261120090000 +0300")],
            )
            write_guide(
                occupied,
                [("TRTTurk.tr@SD", "TRT Turk")],
                [("TRTTurk.tr@SD", "Nederlands", "20261120090000 +0100")],
            )
            write_guide(
                current,
                [("TRTTurk.tr@SD", "TRT TÜRK")],
                [("TRTTurk.tr@SD", "Ana Haber", "20261120100000 +0300")],
            )
            tr_epg.write_merged(
                [("digiturk", current, None)],
                output,
                tr_epg.collect_occupied([occupied]),
                [previous],
            )
            merged = ET.parse(output).getroot()
            ids = {channel.get("id") for channel in merged.findall("channel")}
            self.assertEqual(ids, {"TRTTurk.tr@Turkey"})
            self.assertEqual(
                [programme.findtext("title") for programme in merged.findall("programme")],
                ["Ana Haber"],
            )

    def test_catalog_channel_without_programmes_keeps_id_and_icon_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = root / "guide-tr.xml"
            catalog = root / "turksat.channels.xml"
            current = root / "turksat.xml"
            output = root / "out.xml"
            write_guide(
                previous,
                [("EkolTV.tr@SD", "Ekol TV"), ("ATV.tr@SD", "ATV")],
                [
                    ("EkolTV.tr@SD", "caducado", "20261120060000 +0300"),
                    ("ATV.tr@SD", "haber", "20261120080000 +0300"),
                ],
            )
            tree = ET.parse(previous)
            for channel in tree.getroot().findall("channel"):
                if channel.get("id") == "EkolTV.tr@SD":
                    ET.SubElement(channel, "icon", src="https://example.test/ekol.png")
            tree.write(previous, encoding="utf-8", xml_declaration=True)
            channels = ET.Element("channels")
            for xmltv_id, name in (("", "Ekol TV"), ("ATV.tr@SD", "ATV")):
                node = ET.SubElement(channels, "channel", site_id=name)
                if xmltv_id:
                    node.set("xmltv_id", xmltv_id)
                node.text = name
            ET.ElementTree(channels).write(catalog, encoding="utf-8", xml_declaration=True)
            write_guide(
                current,
                [("ATV.tr@SD", "ATV")],
                [("ATV.tr@SD", "haber nuevo", "20261120090000 +0300")],
            )
            tr_epg.write_merged([("turksat", current, catalog)], output, set(), [previous])
            merged = ET.parse(output).getroot()
            ekol = merged.find("channel[@id='EkolTV.tr@SD']")
            self.assertIsNotNone(ekol)
            self.assertEqual(ekol.find("icon").get("src"), "https://example.test/ekol.png")
            self.assertEqual(ekol.findtext("display-name"), "Ekol TV")
            programmes = merged.findall("programme")
            self.assertEqual([programme.get("channel") for programme in programmes], ["ATV.tr@SD"])
            self.assertEqual([programme.findtext("title") for programme in programmes], ["haber nuevo"])

    def test_channel_missing_from_every_catalog_is_dropped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = root / "guide-tr.xml"
            catalog = root / "channels.xml"
            current = root / "dsmart.xml"
            output = root / "out.xml"
            write_guide(
                previous,
                [("Gone.tr@SD", "Kanal Kayboldu"), ("ATV.tr@SD", "ATV")],
                [("ATV.tr@SD", "haber", "20261120080000 +0300")],
            )
            channels = ET.Element("channels")
            node = ET.SubElement(channels, "channel", site_id="atv", xmltv_id="ATV.tr@SD")
            node.text = "ATV"
            ET.ElementTree(channels).write(catalog, encoding="utf-8", xml_declaration=True)
            write_guide(
                current,
                [("ATV.tr@SD", "ATV")],
                [("ATV.tr@SD", "haber nuevo", "20261120090000 +0300")],
            )
            tr_epg.write_merged([("dsmart", current, catalog)], output, set(), [previous])
            ids = {channel.get("id") for channel in ET.parse(output).getroot().findall("channel")}
            self.assertEqual(ids, {"ATV.tr@SD"})

    def test_validator_still_rejects_a_missing_previous_channel(self):
        validator = load_module("tr_publish_validate", ROOT / "scripts" / "tr_publish_validate.py")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = root / "guide-tr.xml"
            generated = root / "generated.xml"
            write_guide(
                previous,
                [("AKITTV.tr@SD", "AKİT TV")],
                [("AKITTV.tr@SD", "bülten", "20261120080000 +0300")],
            )
            write_guide(
                generated,
                [("ATV.tr@SD", "ATV")],
                [("ATV.tr@SD", "haber", "20261120080000 +0300")],
            )
            problems = validator.validate(
                generated,
                previous,
                root / "missing-aliases.json",
                root / "missing-clones.json",
            )
            self.assertTrue(any(item.startswith("previous channels missing:") for item in problems))
            self.assertTrue(any("AKITTV.tr@SD" in item for item in problems))
            self.assertTrue(any("minimum" in item for item in problems))


if __name__ == "__main__":
    unittest.main()
