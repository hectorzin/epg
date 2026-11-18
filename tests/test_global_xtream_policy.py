"""Global Xtream/XMLTV policy: denied ids, curated aliases, sanitization."""
from __future__ import annotations

import importlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
import sys

sys.path.insert(0, str(SCRIPTS))
policy = importlib.import_module("es_xtream_policy")


class GlobalXtreamPolicyTests(unittest.TestCase):
    def test_global_policy_file_present(self):
        path = ROOT / "epg" / "global-xtream-policy.json"
        self.assertTrue(path.is_file())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("01tv.fr", data.get("global_denied_xtream_clone_ids", []))

    def test_denied_union_includes_es_and_global(self):
        denied = policy.denied_xtream_clone_ids()
        self.assertIn("01tv.fr", denied)
        self.assertIn("canalsur.es", denied)

    def test_curated_counts_match_audit(self):
        fr = policy.curated_display_aliases("fr")
        pt = policy.curated_display_aliases("pt")
        ar = policy.curated_display_aliases("arabic")
        self.assertEqual(sum(len(v) for v in fr.values()), 25)
        self.assertEqual(sum(len(v) for v in pt.values()), 40)
        self.assertEqual(sum(len(v) for v in ar.values()), 16)

    def test_sanitize_rejects_null_tokens(self):
        dirty = {"ok.id": ["Valid", "null", "", "NULL"], "null": ["x"], "": ["y"]}
        clean = policy.sanitize_display_aliases(dirty)
        self.assertEqual(clean, {"ok.id": ["Valid"]})

    def test_filter_numeric_stream_clones(self):
        mapping = {"12345": "ch0", "panel.es": "ch1"}
        filtered = policy.filter_denied_xtream_aliases(mapping, frozenset())
        self.assertEqual(filtered, {"panel.es": "ch1"})

    def test_regional_alias_files_have_no_forbidden_keys(self):
        for name in ("aliases-fr.json", "aliases-pt.json", "aliases-arabic.json"):
            aliases = json.loads((ROOT / "epg" / name).read_text(encoding="utf-8"))
            safe = policy.sanitize_display_aliases(aliases)
            self.assertEqual(set(safe), set(aliases))


if __name__ == "__main__":
    unittest.main()