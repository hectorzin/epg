"""Regression: Spanish Xtream collision policy and AquaPlay resolve on generated XMLTV."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("process_epg", SCRIPTS / "process-epg.py")
epg = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(epg)
policy = importlib.import_module("es_xtream_policy")
xmltv_gzip = importlib.import_module("xmltv_gzip")

SIM = ROOT / "temp" / "simulate_es_mapping_fix.py"


class EsXtreamPolicyTests(unittest.TestCase):
    def test_denied_clones_absent_from_xtream_json(self):
        xtream = json.loads((ROOT / "epg" / "xtream-aliases.json").read_text(encoding="utf-8"))
        denied = policy.denied_xtream_clone_ids()
        overlap = denied & set(xtream)
        self.assertEqual(overlap, set(), f"denied ids still mapped: {sorted(overlap)}")

    def test_aliases_use_stable_canal_sur_id(self):
        aliases = json.loads((ROOT / "epg" / "aliases.json").read_text(encoding="utf-8"))
        self.assertIn("csurOrange", aliases)
        self.assertNotIn("CanalSur.es", aliases)
        self.assertNotIn("HBO Max 1", aliases.get("13tv", []))
        self.assertIn("Andalucía TV", aliases.get("andatv", []))

    def test_process_epg_purges_denied_clones_and_renames(self):
        guide = ROOT / "guides" / "guide-es.xml"
        if not guide.is_file():
            self.skipTest("guide-es.xml not present locally")
        out = ROOT / "temp" / "guide-es.after.xml"
        rc = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "process-epg.py"),
                "--input",
                str(guide),
                "--output",
                str(out),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(rc.returncode, 0, rc.stderr)
        root = ET.parse(out).getroot()
        ids = {ch.get("id") for ch in root.findall("channel")}
        denied = policy.denied_xtream_clone_ids()
        self.assertFalse(ids & denied)
        self.assertIn("csurOrange", ids)
        self.assertNotIn("CanalSur.es", ids)
        renames = policy.channel_renames()
        if any(cid in ids for cid in renames):
            for old, new in renames.items():
                if new in ids:
                    self.assertNotIn(old, ids)

    def test_aquaplay_simulation_after_generated_guide(self):
        if not SIM.is_file():
            self.skipTest("simulate_es_mapping_fix.py missing")
        after_es = ROOT / "temp" / "guide-es.after.xml"
        after_gl = ROOT / "temp" / "guide.after.xml"
        if not after_es.is_file():
            self.skipTest("generated guide-es.after.xml missing")
        proc = subprocess.run(
            [sys.executable, str(SIM)],
            capture_output=True,
            text=True,
            env={
                **__import__("os").environ,
                "SIM_GUIDE_ES_AFTER": str(after_es),
                "SIM_GUIDE_GLOBAL_AFTER": (
                    str(after_gl)
                    if after_gl.is_file()
                    else str(xmltv_gzip.published_global_guide(ROOT))
                ),
            },
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()