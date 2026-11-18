import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "process-epg.py"
SPEC = importlib.util.spec_from_file_location("update_epg", SCRIPT)
epg = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(epg)


def sample(channels=120, programmes=3000):
    parts = ['<?xml version="1.0"?><tv date="20261114">']
    parts.extend(f'<channel id="ch{i}"><display-name>Channel {i}</display-name></channel>' for i in range(channels))
    parts.extend(f'<programme start="20261115000000 +0000" stop="20261115010000 +0000" channel="ch{i % channels}"><title>Show {i}</title></programme>' for i in range(programmes))
    parts.append("</tv>")
    return "".join(parts).encode()


def xtream_channel(xtream_id, name, epg_id, category="[ES] TDT"):
    return {"xtream_id": xtream_id, "name": name, "epg_id": epg_id, "category": category}


class EpgUpdateTests(unittest.TestCase):
    def setUp(self):
        self.aliases = {f"ch{i}": [f"Alias {i}"] for i in range(65)}
        self.aliases["ch65"] = ["Alias 65", "Second alias 65"]

    def test_valid_xml_aliases_and_programmes_preserved(self):
        data, channels, programmes = epg.merge(sample(), self.aliases)
        root = epg.parse_xml(data, "test")
        self.assertEqual((channels, programmes), (120, 3000))
        self.assertEqual(root.find("channel[@id='ch0']/display-name[2]").text, "Alias 0")
        self.assertEqual(root.find("channel[@id='ch65']/display-name[3]").text, "Second alias 65")
        self.assertEqual(len(root.findall("programme")), 3000)

    def test_idempotent_alias_merge(self):
        first, _, _ = epg.merge(sample(), self.aliases)
        second, _, _ = epg.merge(first, self.aliases)
        self.assertEqual(first, second)

    def test_xtream_alias_clones_channel_and_programmes_without_changing_originals(self):
        mapping = {"antena3.es": "ch0"}
        original = sample()
        result, channels, programmes = epg.merge(original, self.aliases, xtream_aliases=mapping)
        before = epg.parse_xml(original, "source")
        after = epg.parse_xml(result, "result")
        self.assertEqual((channels, programmes), (120, 3000))
        self.assertEqual(len(after.findall("channel")), 121)
        original_programmes = [epg._programme_fingerprint(p) for p in before.findall("programme")]
        final_original_programmes = [
            epg._programme_fingerprint(p)
            for p in after.findall("programme")
            if p.get("channel") != "antena3.es"
        ]
        self.assertEqual(final_original_programmes, original_programmes)
        source_channel = after.find("channel[@id='ch0']")
        cloned_channel = after.find("channel[@id='antena3.es']")
        expected_channel = copy.deepcopy(source_channel)
        expected_channel.set("id", "antena3.es")
        self.assertEqual(epg.ET.tostring(cloned_channel), epg.ET.tostring(expected_channel))
        expected_programmes = [
            epg._programme_fingerprint(epg._programme_with_channel(p, "antena3.es"))
            for p in before.findall("programme[@channel='ch0']")
        ]
        actual_programmes = [
            epg._programme_fingerprint(p) for p in after.findall("programme[@channel='antena3.es']")
        ]
        self.assertEqual(actual_programmes, expected_programmes)

    def test_xtream_merge_is_idempotent_and_does_not_duplicate_clones(self):
        mapping = {"antena3.es": "ch0"}
        first, _, _ = epg.merge(sample(), self.aliases, xtream_aliases=mapping)
        second, _, _ = epg.merge(first, self.aliases, xtream_aliases=mapping)
        self.assertEqual(first, second)
        root = epg.parse_xml(second, "result")
        self.assertEqual(len(root.findall("channel[@id='antena3.es']")), 1)
        self.assertEqual(len(root.findall("programme[@channel='antena3.es']")), 25)

    def test_xtream_alias_conflicts_are_rejected(self):
        with self.assertRaisesRegex(epg.EpgError, "already belongs to a different channel"):
            epg.merge(sample().replace(
                b'<channel id="ch119"><display-name>Channel 119</display-name></channel>',
                b'<channel id="ch119"><display-name>Channel 119</display-name></channel><channel id="antena3.es"><display-name>Other</display-name></channel>',
            ), self.aliases, xtream_aliases={"antena3.es": "ch0"})
        with self.assertRaisesRegex(epg.EpgError, "unknown original channel"):
            epg.merge(sample(), self.aliases, xtream_aliases={"antena3.es": "missing"})
        with self.assertRaisesRegex(epg.EpgError, "empty or NULL"):
            epg.merge(sample(), self.aliases, xtream_aliases={"NULL": "ch0"})

    def test_es_policy_purges_denied_xtream_clones(self):
        mapping = {"denied.clone": "ch0"}
        denied = frozenset({"denied.clone"})
        payload = (
            b'<?xml version="1.0"?><tv>'
            b'<channel id="ch0"><display-name>Ch0</display-name></channel>'
            b'<channel id="denied.clone"><display-name>Bad</display-name></channel>'
            b'<programme start="20261115000000 +0000" stop="20261115010000 +0000" channel="ch0">'
            b"<title>Show</title></programme>"
            b'<programme start="20261115000000 +0000" stop="20261115010000 +0000" channel="denied.clone">'
            b"<title>Bad</title></programme></tv>"
        )
        result, _, _ = epg.merge(
            payload,
            {"ch0": ["Alias"]},
            xtream_aliases={},
            denied_xtream_clones=denied,
            min_channels=1,
            min_programmes=1,
        )
        root = epg.parse_xml(result, "out")
        ids = {ch.get("id") for ch in root.findall("channel")}
        self.assertNotIn("denied.clone", ids)

    def test_xtream_alias_loader_rejects_empty_null_and_multiple_destinations(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "xtream-aliases.json"
            for data in ['{"": "ch0"}', '{"NULL": "ch0"}', '{"x": "ch0", "x": "ch1"}']:
                path.write_text(data, encoding="utf-8")
                with self.assertRaises(epg.EpgError):
                    epg.load_xtream_aliases(path)

    def test_xtream_programme_mismatch_is_rejected(self):
        mapping = {"antena3.es": "ch0"}
        first, _, _ = epg.merge(sample(), self.aliases, xtream_aliases=mapping)
        damaged = first.replace(b"<title>Show 0</title>", b"<title>Changed</title>", 1)
        with self.assertRaises(epg.EpgError):
            epg.merge(damaged, self.aliases, xtream_aliases=mapping)

    def test_catalog_loader_accepts_only_the_four_sanitized_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps([xtream_channel(1, "Channel 0 HD", "provider.ch0")]), encoding="utf-8")
            self.assertEqual(len(epg.load_xtream_catalog(path)), 1)
            path.write_text(json.dumps([{
                **xtream_channel(1, "Channel 0 HD", "provider.ch0"),
                "source_url": "must-not-be-accepted",
            }]), encoding="utf-8")
            with self.assertRaisesRegex(epg.EpgError, "only the four approved fields"):
                epg.load_xtream_catalog(path)
            path.write_text(json.dumps([
                xtream_channel(1, "Channel 0 HD", "provider.ch0"),
                xtream_channel(1, "Channel 1 HD", "provider.ch1"),
            ]), encoding="utf-8")
            with self.assertRaisesRegex(epg.EpgError, "duplicate Xtream ID"):
                epg.load_xtream_catalog(path)

    def test_regional_profile_accepts_partial_alias_files(self):
        aliases = {"ch0": ["Alias 0 HD"]}
        data, channels, programmes = epg.merge(
            sample(channels=120, programmes=3000),
            aliases,
            xtream_aliases={},
            min_channels=100,
            min_programmes=1000,
            alias_mode="regional",
        )
        root = epg.parse_xml(data, "result")
        self.assertEqual(root.find("channel[@id='ch0']/display-name[2]").text, "Alias 0 HD")
        self.assertEqual((channels, programmes), (120, 3000))

    def test_catalog_matches_name_and_duplicates_programmes_for_xtream_id(self):
        source = sample()
        catalog = [
            xtream_channel(1, "[ES] Channel 0 FULL HD", "provider.channel-0"),
            xtream_channel(2, "Channel 0 4K", "provider.channel-0"),
        ]
        mapping, summary = epg.resolve_xtream_catalog(
            epg.parse_xml(source, "source"), catalog, self.aliases, {}
        )
        self.assertEqual(mapping, {"provider.channel-0": "ch0"})
        self.assertEqual(summary["new_aliases"], 1)
        self.assertEqual(summary["new_alias_channels"], 2)
        result, _, original_count = epg.merge(source, self.aliases, xtream_aliases=mapping)
        root = epg.parse_xml(result, "result")
        original = epg.parse_xml(source, "source")
        self.assertEqual(original_count, 3000)
        self.assertEqual(len(root.findall("programme[@channel='provider.channel-0']")), 25)
        self.assertEqual(
            [epg._programme_fingerprint(item) for item in root.findall("programme") if item.get("channel") != "provider.channel-0"],
            [epg._programme_fingerprint(item) for item in original.findall("programme")],
        )

    def test_catalog_keeps_valid_identical_ids_without_cloning(self):
        source = sample()
        mapping, summary = epg.resolve_xtream_catalog(
            epg.parse_xml(source, "source"),
            [xtream_channel(1, "Channel 0 FHD", "ch0")],
            self.aliases,
            {},
        )
        self.assertEqual(mapping, {"ch0": "ch0"})
        self.assertEqual(summary["identifier_match_channels"], 1)
        result, _, _ = epg.merge(source, self.aliases, xtream_aliases=mapping)
        root = epg.parse_xml(result, "result")
        self.assertEqual(len(root.findall("channel[@id='ch0']")), 1)
        self.assertEqual(len(root.findall("programme[@channel='ch0']")), 25)

    def test_catalog_rejects_id_name_contradictions_and_original_id_collisions(self):
        source_root = epg.parse_xml(sample(), "source")
        mapping, summary = epg.resolve_xtream_catalog(
            source_root,
            [xtream_channel(1, "Channel 1", "ch0")],
            self.aliases,
            {},
        )
        self.assertEqual(mapping, {})
        self.assertEqual(summary["ambiguous_epg_ids"], 1)
        mapping, summary = epg.resolve_xtream_catalog(
            source_root,
            [xtream_channel(1, "Channel 0", "ch1")],
            self.aliases,
            {},
        )
        self.assertEqual(mapping, {})
        self.assertEqual(summary["ambiguous_epg_ids"], 1)

    def test_catalog_rejects_shared_epg_ids_for_different_channel_names(self):
        mapping, summary = epg.resolve_xtream_catalog(
            epg.parse_xml(sample(), "source"),
            [
                xtream_channel(1, "Channel 0", "provider.shared"),
                xtream_channel(2, "Channel 1", "provider.shared"),
            ],
            self.aliases,
            {},
        )
        self.assertEqual(mapping, {})
        self.assertEqual(summary["ambiguous_epg_ids"], 1)
        self.assertEqual(summary["ambiguous_channels"], 2)

    def test_catalog_name_match_rejects_ambiguous_originals_and_foreign_regions(self):
        source = sample().replace(
            b'<channel id="ch1"><display-name>Channel 1</display-name></channel>',
            b'<channel id="ch1"><display-name>Channel 0</display-name></channel>',
        )
        mapping, summary = epg.resolve_xtream_catalog(
            epg.parse_xml(source, "ambiguous source"),
            [xtream_channel(1, "Channel 0", "provider.ambiguous")],
            self.aliases,
            {},
        )
        self.assertEqual(mapping, {})
        self.assertEqual(summary["ambiguous_epg_ids"], 1)
        mapping, summary = epg.resolve_xtream_catalog(
            epg.parse_xml(sample(), "source"),
            [xtream_channel(1, "[FR] Channel 0 HD", "provider.foreign", "[FR] TNT")],
            self.aliases,
            {},
        )
        self.assertEqual(mapping, {})
        self.assertEqual(summary["region_mismatches"], 1)
        mapping, summary = epg.resolve_xtream_catalog(
            epg.parse_xml(sample(), "source"),
            [xtream_channel(1, "[FR] Channel 0 HD", "provider.region-conflict", "[ES] TDT")],
            self.aliases,
            {},
        )
        self.assertEqual(mapping, {})
        self.assertEqual(summary["ambiguous_epg_ids"], 1)

    def test_catalog_leaves_missing_ids_pending_and_rejects_suspicious_series_ids(self):
        source = sample().replace(
            b'<channel id="ch0"><display-name>Channel 0</display-name></channel>',
            b'<channel id="ch0"><display-name>Dark</display-name></channel>',
        )
        catalog = [
            xtream_channel(1, "Dark", "dev.series.title.es-dark"),
            xtream_channel(2, "Dark HD", None),
            xtream_channel(3, "[ES] Dark FHD", "NULL"),
            xtream_channel(4, "Dark", ""),
        ]
        mapping, summary = epg.resolve_xtream_catalog(
            epg.parse_xml(source, "source"), catalog, self.aliases, {}
        )
        self.assertEqual(mapping, {})
        self.assertEqual(summary["suspicious_ids"], 1)
        self.assertEqual(summary["pending_no_epg_id"], 3)
        self.assertEqual(summary["pending_name_matches"], 3)
        self.assertEqual(epg.normalize_channel_name("[ES] Canal 2 FULL HD"), "canal2")
        self.assertEqual(epg.normalize_channel_name("BE MAD HD"), "bemad")
        self.assertNotEqual(epg.normalize_channel_name("Canal 2"), epg.normalize_channel_name("Canal 3"))

    def test_catalog_preserves_existing_69_aliases(self):
        configured = epg.load_xtream_aliases(Path(__file__).resolve().parents[1] / "epg" / "xtream-aliases.json")
        self.assertGreaterEqual(len(configured), 69)
        root = epg.ET.Element("tv")
        for original_id in set(configured.values()):
            channel = epg.ET.SubElement(root, "channel", {"id": original_id})
            epg.ET.SubElement(channel, "display-name").text = original_id
        mapping, _ = epg.resolve_xtream_catalog(root, [], {}, configured)
        self.assertEqual(mapping, configured)

    def test_provided_xtream_aliases_are_valid_and_compatible_with_display_aliases(self):
        mapping = epg.load_xtream_aliases(Path(__file__).resolve().parents[1] / "epg" / "xtream-aliases.json")
        established = {
            "antena3.es": "a3", "la1.es": "tve", "la2.es": "la2",
            "cuatro.es": "c4", "telecinco.es": "t5",
        }
        self.assertEqual({key: mapping[key] for key in established}, established)
        self.assertGreaterEqual(len(mapping), 69)
        # Exercise the same merge path with fixture-specific channel IDs.
        test_mapping = {f"xtream-{i}.es": f"ch{i}" for i in range(5)}
        result, _, _ = epg.merge(sample(), self.aliases, xtream_aliases=test_mapping)
        root = epg.parse_xml(result, "result")
        self.assertEqual(root.find("channel[@id='ch0']/display-name[2]").text, "Alias 0")
        self.assertEqual(root.find("channel[@id='xtream-0.es']/display-name[2]").text, "Alias 0")
        self.assertEqual(len(root.findall("programme[@channel='xtream-0.es']")), 25)

    def test_deduplicates_existing_alias(self):
        data = sample().replace(b"<display-name>Channel 0</display-name>", b"<display-name>Channel 0</display-name><display-name>Alias 0</display-name>")
        data = data.replace(b"<display-name>Channel 1</display-name>", b"<display-name>Channel 1</display-name><display-name>Alias 1</display-name>")
        result, _, _ = epg.merge(data, self.aliases)
        root = epg.parse_xml(result, "test")
        for index in range(2):
            names = [item.text for item in root.find(f"channel[@id='ch{index}']").findall("display-name")]
            self.assertEqual(names.count(f"Alias {index}"), 1)

    def test_preserves_existing_bytes_if_aliases_already_present(self):
        data = sample().replace(
            b"<display-name>Channel 0</display-name>",
            b"<display-name>Channel 0</display-name><display-name>Alias 0</display-name>",
        )
        for index in range(1, 65):
            data = data.replace(
                f"<display-name>Channel {index}</display-name>".encode(),
                f"<display-name>Channel {index}</display-name><display-name>Alias {index}</display-name>".encode(),
            )
        data = data.replace(
            b"<display-name>Channel 65</display-name>",
            b"<display-name>Channel 65</display-name><display-name>Alias 65</display-name><display-name>Second alias 65</display-name>",
        )
        result, _, _ = epg.merge(data, self.aliases)
        self.assertEqual(result, data)

    def test_normalizes_git_line_endings_for_comparison(self):
        source = b"\xef\xbb\xbf<tv>\r\n</tv>\r\n"
        expected = b"<tv>\n</tv>"
        self.assertEqual(epg.normalize_for_compare(source), expected)

    def test_missing_channel_fails(self):
        aliases = dict(self.aliases)
        aliases["absent"] = ["No channel"]
        with self.assertRaisesRegex(epg.EpgError, "missing configured channel"):
            epg.merge(sample(), aliases)

    def test_tolerant_mode_skips_absent_display_alias_channels(self):
        aliases = dict(self.aliases)
        aliases["absent"] = ["Optional alias"]
        result, channels, programmes = epg.merge(sample(), aliases, alias_mode="tolerant")
        root = epg.parse_xml(result, "result")
        self.assertEqual((channels, programmes), (120, 3000))
        self.assertIsNone(root.find("channel[@id='absent']"))

    def test_regional_mode_skips_configured_xtream_when_original_absent(self):
        xml = (
            b'<?xml version="1.0"?><tv>'
            b'<channel id="ch1"><display-name>One</display-name></channel>'
            b'<programme start="20261115000000 +0000" stop="20261115010000 +0000" channel="ch1">'
            b"<title>News</title></programme></tv>"
        )
        mapping = {"panel.x": "missing.original"}
        result, channels, programmes = epg.merge(
            xml, {}, xtream_aliases=mapping, min_channels=1, min_programmes=1, alias_mode="regional"
        )
        root = epg.parse_xml(result, "result")
        self.assertIsNone(root.find("channel[@id='panel.x']"))
        self.assertEqual((channels, programmes), (1, 1))

    def test_strict_mode_rejects_configured_xtream_with_missing_original(self):
        xml = (
            b'<?xml version="1.0"?><tv>'
            b'<channel id="ch1"><display-name>One</display-name></channel>'
            b'<programme start="20261115000000 +0000" stop="20261115010000 +0000" channel="ch1">'
            b"<title>News</title></programme></tv>"
        )
        with self.assertRaisesRegex(epg.EpgError, "unknown original channel"):
            epg.merge(xml, {}, xtream_aliases={"panel.x": "missing.original"}, min_channels=1, min_programmes=1)

    def test_regional_xtream_uses_stem_fallback_when_feed_suffix_differs(self):
        xml = (
            b'<?xml version="1.0"?><tv>'
            b'<channel id="MTV.uk@SD"><display-name>MTV</display-name></channel>'
            b'<programme start="20261115000000 +0000" stop="20261115010000 +0000" channel="MTV.uk@SD">'
            b"<title>Hits</title></programme></tv>"
        )
        result, channels, programmes = epg.merge(
            xml,
            {},
            xtream_aliases={"mtv.uk": "MTV.uk@HD"},
            min_channels=1,
            min_programmes=1,
            alias_mode="regional",
        )
        root = epg.parse_xml(result, "result")
        self.assertIsNotNone(root.find("channel[@id='mtv.uk']"))
        self.assertEqual(len(root.findall("programme[@channel='mtv.uk']")), 1)

    def test_display_alias_targets_canonical_id_when_feed_suffix_differs(self):
        xml = (
            b'<?xml version="1.0"?><tv>'
            b'<channel id="MTV.uk@SD"><display-name>MTV</display-name></channel>'
            b'<programme start="20261115000000 +0000" stop="20261115010000 +0000" channel="MTV.uk@SD">'
            b"<title>Hits</title></programme></tv>"
        )
        aliases = {"MTV.uk@HD": ["My MTV"]}
        result, _, _ = epg.merge(
            xml, aliases, xtream_aliases={}, min_channels=1, min_programmes=1, alias_mode="regional"
        )
        root = epg.parse_xml(result, "result")
        names = [node.text for node in root.find("channel[@id='MTV.uk@SD']").findall("display-name")]
        self.assertIn("My MTV", names)

    def test_resolve_xtream_catalog_tolerates_missing_regional_configured(self):
        root = epg.parse_xml(
            b'<?xml version="1.0"?><tv><channel id="a"><display-name>A</display-name></channel>'
            b'<programme start="20261115000000 +0000" stop="20261115010000 +0000" channel="a">'
            b"<title>x</title></programme></tv>",
            "src",
        )
        resolved, summary = epg.resolve_xtream_catalog(
            root, [], {}, {"clone.x": "absent"}, auto_region="GB", tolerate_missing_configured=True
        )
        self.assertEqual(resolved, {})
        self.assertEqual(summary["skipped_configured_xtream"], 1)

    def test_xtream_clone_chain_is_flattened_to_root_on_load(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "xtream.json"
            path.write_text(
                json.dumps({"fox.es.cinesur": "fox.es.skyshowtime1", "fox.es.skyshowtime1": "skysho"}),
                encoding="utf-8",
            )
            mapping = epg.load_xtream_aliases(path)
            self.assertEqual(mapping["fox.es.cinesur"], "skysho")
            self.assertEqual(mapping["fox.es.skyshowtime1"], "skysho")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "xtream-cycle.json"
            path.write_text(json.dumps({"a.es": "b.es", "b.es": "a.es"}), encoding="utf-8")
            with self.assertRaisesRegex(epg.EpgError, "cycle"):
                epg.load_xtream_aliases(path)

    def test_spanish_skyshowtime_panel_clones_root_not_intermediate(self):
        xml = (
            b'<?xml version="1.0"?><tv>'
            b'<channel id="skysho"><display-name>SkyShowtime 1</display-name></channel>'
            b'<programme start="20261115000000 +0000" stop="20261115010000 +0000" channel="skysho">'
            b"<title>Test</title></programme></tv>"
        )
        on_disk = epg.load_xtream_aliases(
            Path(__file__).resolve().parents[1] / "epg" / "xtream-aliases.json"
        )
        self.assertEqual(on_disk.get("fox.es.skyshowtime1"), "skysho")
        self.assertNotIn("fox.es.cinesur", on_disk)
        mapping = {"fox.es.skyshowtime1": "skysho"}
        aliases = {"skysho": ["M+ Cinesur", "SkyShowtime 1"]}
        result, _, _ = epg.merge(xml, aliases, xtream_aliases=mapping, min_channels=1, min_programmes=1)
        root = epg.parse_xml(result, "result")
        self.assertIsNotNone(root.find("channel[@id='fox.es.skyshowtime1']"))
        self.assertIsNone(root.find("channel[@id='fox.es.cinesur']"))
        self.assertEqual(len(root.findall("programme[@channel='fox.es.skyshowtime1']")), 1)

    def test_malformed_or_truncated_xml_fails(self):
        with self.assertRaises(epg.EpgError):
            epg.merge(sample()[:-30], self.aliases)

    def test_coverage_drop_fails(self):
        with self.assertRaisesRegex(epg.EpgError, "coverage dropped"):
            epg.merge(sample(programmes=1000), self.aliases, sample(programmes=5000))

    def test_atomic_failure_does_not_replace_previous_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "guide.xml"
            target.write_bytes(b"previous")
            with self.assertRaises(epg.EpgError):
                epg.merge(b"<tv>", self.aliases)
            self.assertEqual(target.read_bytes(), b"previous")

    def test_atomic_write_and_unchanged_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "guide.xml"
            epg.atomic_write(target, b"valid")
            timestamp = target.stat().st_mtime_ns
            self.assertEqual(target.read_bytes(), b"valid")
            self.assertEqual(target.stat().st_mtime_ns, timestamp)

    def test_alias_json_requires_expected_ids_and_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "aliases.json"
            configured = {f"ch{i}": [f"Alias {i}"] for i in range(60)}
            configured["ch60"] = ["Alias 60", "Second alias 60", "Third alias 60", "Fourth alias 60", "Fifth alias 60", "Sixth alias 60"]
            path.write_text(json.dumps(configured), encoding="utf-8")
            self.assertEqual(sum(map(len, epg.load_aliases(path).values())), 66)
            path.write_text("{}", encoding="utf-8")
            with self.assertRaises(epg.EpgError):
                epg.load_aliases(path)

    def test_cli_processes_local_input_to_separate_output_without_overwriting_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "generated-guide.xml"
            output_path = root / "definitive-guide.xml"
            aliases_path = root / "aliases.json"
            xtream_aliases_path = root / "xtream-aliases.json"
            source = sample()
            source_path.write_bytes(source)
            aliases_path.write_text(json.dumps(self.aliases), encoding="utf-8")
            xtream_aliases_path.write_text(json.dumps({"provider.ch0": "ch0"}), encoding="utf-8")

            argv = [
                str(SCRIPT),
                "--input", str(source_path),
                "--output", str(output_path),
                "--aliases", str(aliases_path),
                "--xtream-aliases", str(xtream_aliases_path),
            ]
            with patch.object(epg.sys, "argv", argv):
                self.assertEqual(epg.main(), 0)

            self.assertEqual(source_path.read_bytes(), source)
            output_root = epg.parse_xml(output_path.read_bytes(), "output")
            self.assertEqual(output_root.find("channel[@id='ch0']/display-name[2]").text, "Alias 0")
            self.assertIsNotNone(output_root.find("channel[@id='provider.ch0']"))
            self.assertEqual(len(output_root.findall("programme[@channel='provider.ch0']")), 25)

    def test_cli_rejects_same_input_and_output_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "guide.xml"
            source = sample()
            source_path.write_bytes(source)
            aliases_path = root / "aliases.json"
            aliases_path.write_text(json.dumps(self.aliases), encoding="utf-8")
            xtream_aliases_path = root / "xtream-aliases.json"
            xtream_aliases_path.write_text("{}", encoding="utf-8")
            argv = [
                str(SCRIPT),
                "--input", str(source_path),
                "--output", str(source_path),
                "--aliases", str(aliases_path),
                "--xtream-aliases", str(xtream_aliases_path),
            ]
            with patch.object(epg.sys, "argv", argv):
                self.assertEqual(epg.main(), 1)
            self.assertEqual(source_path.read_bytes(), source)

    def test_cli_requires_a_local_input_and_has_no_remote_source_default(self):
        with patch.object(epg.sys, "argv", [str(SCRIPT), "--output", "guide.final.xml"]):
            with self.assertRaises(SystemExit):
                epg.main()


if __name__ == "__main__":
    unittest.main()
