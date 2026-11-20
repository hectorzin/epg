"""Safe Xtream display-name aliases: uniqueness, DTD order, no cross-channel brands."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SPEC = importlib.util.spec_from_file_location("process_epg", SCRIPTS / "process-epg.py")
epg = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(epg)

ALIAS_FILES = {
    "es": ROOT / "epg" / "aliases.json",
    "fr": ROOT / "epg" / "aliases-fr.json",
    "arabic": ROOT / "epg" / "aliases-arabic.json",
    "gb": ROOT / "epg" / "aliases-gb.json",
    "pt": ROOT / "epg" / "aliases-pt.json",
    "nl": ROOT / "epg" / "aliases-nl.json",
    "it": ROOT / "epg" / "aliases-it.json",
    "de": ROOT / "epg" / "aliases-de.json",
}


def _load(path: Path) -> dict[str, list[str]]:
    return json.loads(path.read_text(encoding="utf-8"))


class XtreamDisplayAliasTests(unittest.TestCase):
    def test_all_regional_alias_files_validate(self):
        for profile, path in ALIAS_FILES.items():
            loaded = epg.load_aliases(path, profile="es" if profile == "es" else "regional")
            self.assertTrue(loaded)
            for channel_id, names in loaded.items():
                self.assertEqual(len(names), len(set(names)), channel_id)

    def test_spanish_xtream_quality_names_were_added(self):
        aliases = _load(ALIAS_FILES["es"])
        self.assertIn("ANTENA 3 HD", aliases["a3"])
        self.assertIn("A3 UHD", aliases["a3"])
        self.assertIn("LA 1 UHD", aliases["tve"])
        self.assertIn("TELECINCO HD", aliases["t5"])
        self.assertIn("M+ VAMOS HD", aliases["vamosd"])
        self.assertIn("CAZAyPESCA FULL HD", aliases["cazpes"])
        self.assertIn("DAZN LALIGA HD+", aliases["daznli"])
        self.assertIn("DAZN LALIGA HD 235", aliases["daznli"])
        self.assertIn("M.LCAMPEONES HD+", aliases["chapio"])
        self.assertEqual(
            aliases["mhits"],
            ["M+ Series", "M+ Series 2", "M+ SERIES FULL HD", "M+ SERIES 4K"],
        )
        for n in range(6, 14):
            self.assertEqual(aliases[f"MovistarPlus.chap{n - 1}"], [f"M+LCAMPEON{n}"])
        self.assertEqual(aliases["Orange.11178"], ["TOP BARÇA HD"])
        self.assertEqual(aliases["Rally.TV.de"], ["DAZN RALLY TV"])

    def test_spanish_first_alias_entries_are_preserved(self):
        aliases = _load(ALIAS_FILES["es"])
        self.assertEqual(aliases["a3"][0], "ANTENA 3 FULL HD")
        self.assertEqual(aliases["tve"][0], "LA 1 FULL HD")
        self.assertEqual(aliases["chapio"][0], "M+ LCAMPEONES HD")

    def test_french_planete_names_stay_on_planete_channels(self):
        aliases = _load(ALIAS_FILES["fr"])
        self.assertNotIn("PLANETE +AVENTURE", aliases.get("6ter.fr@SD", []))
        self.assertNotIn("PLANETE+CRIME", aliases.get("13emeRue.fr@SD", []))
        self.assertIn("PLANETE +AVENTURE Full HD", aliases["PlanetePlusAventure.fr@SD"])
        self.assertIn("PLANETE+CRIME Full HD", aliases["PlanetePlusCrime.fr@SD"])
        self.assertEqual(aliases["TF1.fr@4K"], ["TF1 4K"])
        self.assertNotIn("TF1 4K", aliases["TF1.fr@SD"])

    def test_gb_nl_exact_xtream_titles_were_added(self):
        gb = _load(ALIAS_FILES["gb"])
        nl = _load(ALIAS_FILES["nl"])
        self.assertEqual(gb["BloombergTV.us@UK"], ["UK Bloomberg TV"])
        self.assertEqual(gb["SkySportsArena.uk@HD"], ["UK Sky Sports Arena SD"])
        self.assertEqual(gb["W.ie@SD"], ["UK W"])
        self.assertIn("NL TV Oost HD", nl["RTVOost.nl@SD"])
        self.assertIn("NL TV Oost 4K", nl["RTVOost.nl@SD"])
        self.assertEqual(nl["RTVOost.nl@SD"][0], "NL TV Oost HD")

    def test_rtv_noord_is_not_aliased_to_utrecht(self):
        nl = _load(ALIAS_FILES["nl"])
        utrecht = nl["RTVUtrecht.nl@SD"]
        self.assertEqual(utrecht[0], "NL RTV Utrecht 4K")
        self.assertNotIn("NL RTV Noord HD", utrecht)
        self.assertNotIn("NL RTV Noord 4K", utrecht)
        noord = nl["RTVNoord.nl@SD"]
        self.assertEqual(noord, ["NL RTV Noord 4K", "NL RTV Noord HD"])

    def test_added_xtream_names_are_unique_within_each_alias_file(self):
        watched = {
            "es": [
                "ANTENA 3 HD",
                "A3 UHD",
                "LA 1 HD",
                "LA 1 UHD",
                "M+ VAMOS HD",
            ],
            "gb": ["UK Bloomberg TV", "UK Sky Sports Arena SD", "UK W"],
            "nl": ["NL TV Oost 4K", "NL RTV Noord HD", "NL RTV Noord 4K", "NL RTV Utrecht HD"],
            "fr": ["PLANETE +AVENTURE Full HD", "PLANETE+CRIME Full HD", "TF1 4K"],
        }
        for profile, names in watched.items():
            owners: dict[str, list[str]] = {}
            for channel_id, extra in _load(ALIAS_FILES[profile]).items():
                for name in extra:
                    if name in names:
                        owners.setdefault(name, []).append(channel_id)
            collisions = {name: ids for name, ids in owners.items() if len(ids) > 1}
            self.assertEqual(collisions, {}, f"{profile} {collisions}")

    def test_italian_xtream_aliases_remain_empty(self):
        clones = json.loads((ROOT / "epg" / "xtream-aliases-it.json").read_text(encoding="utf-8"))
        self.assertEqual(clones, {})

    def test_no_null_alias_keys_or_blank_names(self):
        forbidden = {"", "null", "none", "undefined"}
        for path in ALIAS_FILES.values():
            aliases = _load(path)
            for channel_id, names in aliases.items():
                self.assertNotIn(channel_id.strip().casefold(), forbidden)
                self.assertTrue(all(name.strip() for name in names), channel_id)

    def test_merge_appends_xtream_names_before_icon_and_preserves_programmes(self):
        source = (
            b'<?xml version="1.0"?><tv date="20261118">'
            b'<channel id="a3"><display-name>Antena 3</display-name>'
            b'<icon src="https://example.com/a3.png"/>'
            b"<url>https://movistarplus.es</url></channel>"
            + b"".join(
                f'<channel id="ch{i}"><display-name>Channel {i}</display-name></channel>'.encode()
                for i in range(120)
            )
            + b"".join(
                (
                    b'<programme start="20261118000000 +0000" stop="20261118010000 +0000" '
                    b'channel="a3"><title>Show</title></programme>'
                )
                for _ in range(20)
            )
            + b"".join(
                (
                    b'<programme start="20261118000000 +0000" stop="20261118010000 +0000" '
                    + f'channel="ch{i % 120}"><title>Show {i}</title></programme>'.encode()
                )
                for i in range(1000)
            )
            + b"</tv>"
        )
        aliases = {f"ch{i}": [f"Alias {i}"] for i in range(65)}
        aliases["a3"] = ["ANTENA 3 HD", "A3 UHD"]
        data, channels, programmes = epg.merge(source, aliases)
        root = epg.parse_xml(data, "test")
        channel = root.find("channel[@id='a3']")
        names = [node.text for node in channel.findall("display-name")]
        self.assertEqual(names[0], "Antena 3")
        self.assertIn("ANTENA 3 HD", names)
        self.assertIn("A3 UHD", names)
        tags = [node.tag for node in channel]
        self.assertEqual(tags, ["display-name", "display-name", "display-name", "icon", "url"])
        self.assertEqual((channels, programmes), (121, 1020))
        self.assertEqual(len(root.findall("programme[@channel='a3']")), 20)

    def test_cli_applies_new_names_on_a_copy_without_changing_source(self):
        guide = ROOT / "guides" / "guide-es.xml"
        if not guide.is_file():
            self.skipTest("guide-es.xml not present")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "guide-es.aliased.xml"
            argv = [
                str(SCRIPTS / "process-epg.py"),
                "--input",
                str(guide),
                "--output",
                str(output),
                "--aliases",
                str(ALIAS_FILES["es"]),
                "--xtream-aliases",
                str(ROOT / "epg" / "xtream-aliases.json"),
                "--profile",
                "es",
            ]
            import sys
            from unittest.mock import patch

            with patch.object(sys, "argv", argv):
                self.assertEqual(epg.main(), 0)
            source = ET.parse(guide).getroot()
            result = ET.parse(output).getroot()
            src_a3 = source.find("channel[@id='a3']")
            out_a3 = result.find("channel[@id='a3']")
            self.assertEqual(src_a3.find("display-name").text, out_a3.find("display-name").text)
            out_names = [n.text for n in out_a3.findall("display-name")]
            self.assertIn("ANTENA 3 HD", out_names)
            self.assertIn("A3 UHD", out_names)
            tags = [node.tag for node in out_a3]
            display_count = tags.count("display-name")
            self.assertEqual(tags[:display_count], ["display-name"] * display_count)
            if "icon" in tags:
                self.assertLess(tags.index("display-name"), tags.index("icon"))
            source_ids = {ch.get("id") for ch in source.findall("channel")}
            result_ids = {ch.get("id") for ch in result.findall("channel")}
            self.assertTrue(source_ids <= result_ids)
            src_prog = {
                (p.get("channel"), p.get("start"), p.findtext("title"))
                for p in source.findall("programme")
            }
            out_prog = {
                (p.get("channel"), p.get("start"), p.findtext("title"))
                for p in result.findall("programme")
                if p.get("channel") in source_ids
            }
            self.assertEqual(src_prog, out_prog)

    def test_raw_national_guides_without_existing_clones_still_process(self):
        """CI feeds the grab/merge XML, which has no Xtream clone ids yet."""
        cases = (
            ("fr", "guides/guide-fr.xml", "epg/aliases-fr.json", "epg/xtream-aliases-fr.json"),
            ("gb", "guides/guide-gb.xml", "epg/aliases-gb.json", "epg/xtream-aliases-gb.json"),
            ("pt", "guides/guide-pt.xml", "epg/aliases-pt.json", "epg/xtream-aliases-pt.json"),
        )
        for profile, guide_rel, alias_rel, clone_rel in cases:
            guide = ROOT / guide_rel
            if not guide.is_file():
                self.skipTest(f"{guide_rel} not present")
            clones = json.loads((ROOT / clone_rel).read_text(encoding="utf-8"))
            aliases = json.loads((ROOT / alias_rel).read_text(encoding="utf-8"))
            root = ET.parse(guide).getroot()
            clone_ids = set(clones)
            for node in list(root):
                if node.tag == "channel" and node.get("id") in clone_ids:
                    root.remove(node)
                elif node.tag == "programme" and node.get("channel") in clone_ids:
                    root.remove(node)
            raw = ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"
            result, channels, programmes = epg.merge(
                raw,
                aliases,
                xtream_aliases=clones,
                alias_mode="regional",
            )
            out = epg.parse_xml(result, profile)
            self.assertGreaterEqual(channels, 100, profile)
            self.assertGreaterEqual(programmes, 1000, profile)
            first_names = {
                ch.get("id"): (ch.find("display-name").text if ch.find("display-name") is not None else None)
                for ch in root.findall("channel")
            }
            for channel in out.findall("channel"):
                cid = channel.get("id")
                if cid in first_names and first_names[cid]:
                    self.assertEqual(channel.find("display-name").text, first_names[cid], cid)
                tags = [child.tag for child in channel]
                if "icon" in tags:
                    self.assertLess(tags.index("display-name"), tags.index("icon"), cid)
            expected_clones = {
                "fr": ("eentertainment.fr", "E.fr@SD"),
                "gb": ("crimeplusinvestigation.uk", "CrimeInv.uk@HD"),
                "pt": ("zapviva.pt", "ZapViva.ao@SD"),
            }
            clone_id, original_id = expected_clones[profile]
            self.assertIsNotNone(out.find(f"channel[@id='{original_id}']"), original_id)
            self.assertIsNotNone(out.find(f"channel[@id='{clone_id}']"), clone_id)


if __name__ == "__main__":
    unittest.main()
