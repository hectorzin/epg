"""Tests for scripts/grab_atrescine.py."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
FIXTURE = ROOT / "temp" / "atrescine.html"

SPEC = importlib.util.spec_from_file_location("grab_atrescine", SCRIPTS / "grab_atrescine.py")
grab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(grab)

FAST_SPEC = importlib.util.spec_from_file_location("es_fast_channels", SCRIPTS / "es_fast_channels.py")
fast = importlib.util.module_from_spec(FAST_SPEC)
FAST_SPEC.loader.exec_module(fast)


class GrabAtrescineTests(unittest.TestCase):
    @unittest.skipUnless(FIXTURE.is_file(), "requires temp/atrescine.html fixture")
    def test_parses_fixture_grid(self):
        html = FIXTURE.read_text(encoding="utf-8")
        guide = grab.build_guide(html, days=2)
        programmes = guide.findall("programme")
        self.assertGreaterEqual(len(programmes), 10)
        channel = guide.find("channel")
        assert channel is not None
        self.assertEqual(channel.get("id"), grab.CHANNEL_ID)
        names = {node.text for node in channel.findall("display-name")}
        self.assertIn("Atrescine", names)
        self.assertIn("Atrescine 2", names)

    def test_pluto_catalog_covers_all_hex_ids(self):
        pluto_ids = fast.fast_provider_channel_ids()["Pluto TV"]
        self.assertEqual(len(pluto_ids), 36)
        for channel_id in pluto_ids:
            self.assertGreaterEqual(len(channel_id), 20)


if __name__ == "__main__":
    unittest.main()