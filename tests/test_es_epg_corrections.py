"""Regression tests for Spanish loop-channel EPG and FAST alias policy."""
from __future__ import annotations

import importlib.util
import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
POLICY = ROOT / "epg" / "es-xtream-policy.json"
ALIASES = ROOT / "epg" / "aliases.json"
XTREAM = ROOT / "epg" / "xtream-aliases.json"

SPEC = importlib.util.spec_from_file_location("process_epg", SCRIPTS / "process-epg.py")
epg = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(epg)

POLICY_SPEC = importlib.util.spec_from_file_location("es_xtream_policy", SCRIPTS / "es_xtream_policy.py")
policy_mod = importlib.util.module_from_spec(POLICY_SPEC)
POLICY_SPEC.loader.exec_module(policy_mod)


class SpanishLoopEpgTests(unittest.TestCase):
    def test_skysho_not_used_as_xtream_bucket(self):
        aliases = json.loads(ALIASES.read_text(encoding="utf-8"))
        self.assertNotIn("skysho", aliases)
        self.assertNotIn("M+ Acción 2", aliases.get("cpacci", []))
        self.assertNotIn("M+ Drama 2", aliases.get("cpcole", []))

    def test_mv1_covers_cine_panel_streams(self):
        aliases = json.loads(ALIASES.read_text(encoding="utf-8"))
        self.assertIn("M+ Cine", aliases["mv1"])
        self.assertIn("M+ Cine Selección", aliases["mv1"])

    def test_virtual_panel_ids_are_blocked_from_resolution(self):
        blocked = policy_mod.denied_xtream_epg_resolve_ids()
        self.assertIn("fox.es.cinesur", blocked)
        self.assertIn("fox.es.accion2", blocked)
        self.assertNotIn("cima.es.a3cine", blocked)
        self.assertNotIn("cima.es.iberian", blocked)
        self.assertIn("fox.es.skyshowtime1", blocked)

    def test_atrescine_and_iberian_xtream_aliases(self):
        xtream = json.loads(XTREAM.read_text(encoding="utf-8"))
        self.assertEqual(xtream.get("cima.es.a3cine"), "cima.es.a3cine")
        self.assertEqual(xtream.get("cima.es.iberian"), "SundanceTV.es")

    def test_movistarplus_xtream_targets_discovered_ids(self):
        xtream = json.loads(XTREAM.read_text(encoding="utf-8"))
        self.assertEqual(xtream.get("movistarplus.es"), "MovistarPlus.freeli")
        self.assertEqual(xtream.get("cima.es.bbchistory"), "MovistarPlus.bbhis")

    def test_moviestardrama_no_longer_cloned_to_drama2(self):
        xtream = json.loads(XTREAM.read_text(encoding="utf-8"))
        self.assertNotIn("moviestardrama.es", xtream)

    def test_cinesur_does_not_inherit_skyshowtime_programming(self):
        xml = (
            b'<?xml version="1.0"?><tv>'
            b'<channel id="skysho"><display-name>SkyShowtime 1</display-name></channel>'
            b'<channel id="mv1"><display-name>M+ Estrenos</display-name><display-name>M+ Cine</display-name></channel>'
            b'<programme start="20261115000000 +0000" stop="20261115010000 +0000" channel="skysho">'
            b"<title>Blaze y los Monster Machines</title></programme>"
            b'<programme start="20261115000000 +0000" stop="20261115010000 +0000" channel="mv1">'
            b"<title>Estreno real</title></programme></tv>"
        )
        catalog = [{"epg_id": "fox.es.cinesur", "name": "M+ Cinesur", "category": "[ES] CINE"}]
        aliases = json.loads(ALIASES.read_text(encoding="utf-8"))
        root = epg.parse_xml(xml, "src")
        resolved, _ = epg.resolve_xtream_catalog(
            root,
            catalog,
            aliases,
            {},
            denied_epg_resolve=policy_mod.denied_xtream_epg_resolve_ids(),
        )
        self.assertNotIn("fox.es.cinesur", resolved)

    def test_fast_channel_lists_exist(self):
        expected = {
            "es-pluto.channels.xml": 36,
            "es-samsung.channels.xml": 4,
            "es-rakuten.channels.xml": 8,
        }
        for name, count in expected.items():
            path = ROOT / "epg" / name
            self.assertTrue(path.is_file(), name)
            root = ET.parse(path).getroot()
            self.assertEqual(len(root.findall("channel")), count, name)


if __name__ == "__main__":
    unittest.main()