import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "xtream_matching.py"
SPEC = importlib.util.spec_from_file_location("xtream_matching", SCRIPT)
match = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(match)


class XtreamMatchingTests(unittest.TestCase):
    def test_stem_and_quality_disambiguation(self):
        guide_ids = {"TF1.fr@SD", "TF1.fr@4K"}
        stems, names, core = match.build_guide_indexes(
            guide_ids,
            {"TF1.fr@SD": ["France 2"], "TF1.fr@4K": ["TF1 4K"]},
        )
        guide_id, clone_id, kind = match.resolve_row(
            title="TF1 4K",
            panel_epg_id="tf1.fr",
            stream_id="1",
            channel_ids=guide_ids,
            stem_index=stems,
            name_index=names,
            panel_core_index=core,
            allow_stream_clone=False,
        )
        self.assertEqual(kind, "stem_quality")
        self.assertEqual(guide_id, "TF1.fr@4K")
        self.assertIsNone(clone_id)

    def test_ambiguous_regional_stem_is_rejected(self):
        regionals = {f"France3.fr@{region}" for region in ("Bretagne", "Alsace")}
        stems, names, core = match.build_guide_indexes(regionals, {cid: [cid] for cid in regionals})
        guide_id, _, kind = match.resolve_row(
            title="France 3 HD",
            panel_epg_id="france3.fr",
            stream_id="2",
            channel_ids=regionals,
            stem_index=stems,
            name_index=names,
            panel_core_index=core,
            allow_stream_clone=False,
        )
        self.assertIsNone(guide_id)
        self.assertEqual(kind, "ambiguous_stem")

    def test_numeric_stream_clone_only_when_epg_missing(self):
        guide_ids = {"arabic.beinsports1"}
        stems, names, core = match.build_guide_indexes(guide_ids, {"arabic.beinsports1": ["beIN SPORTS 1"]})
        guide_id, clone_id, kind = match.resolve_row(
            title="beIN SPORTS 1",
            panel_epg_id=None,
            stream_id="984",
            channel_ids=guide_ids,
            stem_index=stems,
            name_index=names,
            panel_core_index=core,
            allow_stream_clone=True,
        )
        self.assertEqual(kind, "display_name")
        self.assertEqual(guide_id, "arabic.beinsports1")
        self.assertEqual(clone_id, "984")

    def test_stream_id_is_not_used_as_panel_epg_id(self):
        self.assertFalse(match.valid_panel_epg_id("12345"))

    def test_fake_hd_unicode_and_panel_core_bein_fr(self):
        guide_ids = {"beINSports1.qa@France"}
        stems, names, core = match.build_guide_indexes(
            guide_ids, {"beINSports1.qa@France": ["beIN SPORTS 1"]}
        )
        guide_id, clone_id, kind = match.resolve_row(
            title="beIN Sports 1 \u029c\u1d05",
            panel_epg_id="beinsports1.fr",
            stream_id="1",
            channel_ids=guide_ids,
            stem_index=stems,
            name_index=names,
            panel_core_index=core,
            allow_stream_clone=False,
        )
        self.assertEqual(kind, "panel_core")
        self.assertEqual(guide_id, "beINSports1.qa@France")
        self.assertEqual(clone_id, "beinsports1.fr")

    def test_gb_playlist_region_is_recognised(self):
        self.assertEqual(match.classify_playlist_region("[GB] ENGLAND"), "GB")
        self.assertEqual(match.classify_playlist_region("[UK] HD"), "GB")

    def test_portugal_playlist_region_is_recognised(self):
        self.assertEqual(match.classify_playlist_region("[PR] Portugal"), "PT")
        self.assertEqual(match.classify_playlist_region("[PT] VIP"), "PT")

    def test_nl_and_it_playlist_regions_are_recognised(self):
        self.assertEqual(match.classify_playlist_region("[NL] HOLLANDS"), "NL")
        self.assertEqual(match.classify_playlist_region("[IT] ITALY"), "IT")
        self.assertEqual(match.classify_playlist_region("[DE] SKY DUTCH"), "DE")
        self.assertEqual(match.classify_playlist_region("[TR] TURKEY"), "TR")
        self.assertNotEqual(match.classify_playlist_region("[DE] SKY DUTCH"), "NL")

    def test_grand_ecran_feed_maps_without_numeric_suffix(self):
        guide_ids = {"CanalPlusGrandEcran.fr@SD"}
        stems, names, core = match.build_guide_indexes(
            guide_ids, {"CanalPlusGrandEcran.fr@SD": ["CANAL+ GRAND ECRAN"]}
        )
        guide_id, _, kind = match.resolve_row(
            title="Grand Ecran 1",
            panel_epg_id=None,
            stream_id="99",
            channel_ids=guide_ids,
            stem_index=stems,
            name_index=names,
            panel_core_index=core,
            allow_stream_clone=False,
        )
        self.assertEqual(kind, "display_name")
        self.assertEqual(guide_id, "CanalPlusGrandEcran.fr@SD")


if __name__ == "__main__":
    unittest.main()