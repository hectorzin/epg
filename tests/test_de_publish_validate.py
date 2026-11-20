import importlib.util
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validate = load("de_publish_validate", ROOT / "scripts" / "de_publish_validate.py")
de_epg = validate.de_epg

MIGRATIONS = {
    "DisneyChannel.de@Germany": "DisneyChannel.de@SD",
    "SWRFernsehenBadenWurttemberg.de@Germany": "SWRFernsehenBadenWurttemberg.de@SD",
    "SkyCinemaPremieren.de@Germany": "SkyCinemaPremieren.de@SD",
    "SkySport1.de@Germany": "SkySport1.de@SD",
    "SkySportBundesliga1.de@Germany": "SkySportBundesliga1.de@SD",
    "SuperRTL.de@SD": "RTLSuper.de@Germany",
    "hrfernsehen.de@Germany": "hrfernsehen.de@SD",
}


def write_guide(path: Path, channels: list[tuple[str, str]], programmes: list[tuple[str, str]]) -> None:
    root = ET.Element("tv")
    for channel_id, name in channels:
        channel = ET.SubElement(root, "channel", id=channel_id)
        ET.SubElement(channel, "display-name").text = name
    for channel_id, title in programmes:
        programme = ET.SubElement(
            root,
            "programme",
            channel=channel_id,
            start="20261119010000 +0100",
            stop="20261119020000 +0100",
        )
        ET.SubElement(programme, "title").text = title
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


class GermanCanonicalMigrationTests(unittest.TestCase):
    def test_committed_migration_is_exactly_the_priority_renames(self):
        self.assertEqual(de_epg.CANONICAL_ID_MIGRATIONS, MIGRATIONS)
        destinations = set(MIGRATIONS.values())
        self.assertEqual(len(destinations), len(MIGRATIONS))
        for old_id, destination in MIGRATIONS.items():
            self.assertFalse(de_epg.is_incorrect_panel_id(old_id), old_id)
            self.assertFalse(de_epg.is_incorrect_panel_id(destination), destination)
            self.assertTrue(de_epg.is_strong_id(destination), destination)
            self.assertNotIn(old_id.casefold(), de_epg.INCORRECT_IDS)

    def test_same_station_with_real_programmes_may_change_id(self):
        names = {
            "DisneyChannel.de@Germany": "Disney Channel",
            "SWRFernsehenBadenWurttemberg.de@Germany": "SWR Fernsehen BW",
            "SkyCinemaPremieren.de@Germany": "Sky Cinema Premiere",
            "SkySport1.de@Germany": "Sky Sport Top Event",
            "SkySportBundesliga1.de@Germany": "Sky Sport Bundesliga",
            "SuperRTL.de@SD": "Super RTL",
            "hrfernsehen.de@Germany": "hr-fernsehen",
        }
        previous = ET.Element("tv")
        generated = ET.Element("tv")
        for old_id, name in names.items():
            channel = ET.SubElement(previous, "channel", id=old_id)
            ET.SubElement(channel, "display-name").text = name
            destination = MIGRATIONS[old_id]
            moved = ET.SubElement(generated, "channel", id=destination)
            ET.SubElement(moved, "display-name").text = name
            programme = ET.SubElement(
                generated,
                "programme",
                channel=destination,
                start="20261119010000 +0100",
            )
            ET.SubElement(programme, "title").text = "heute"
        problems = validate.missing_channel_problems(previous, generated, set(names))
        self.assertEqual(problems, [])

    def test_abbreviation_is_not_the_same_station(self):
        previous = ET.Element("tv")
        old = ET.SubElement(previous, "channel", id="DisneyChannel.de@Germany")
        ET.SubElement(old, "display-name").text = "Disney Channel"
        generated = ET.Element("tv")
        channel = ET.SubElement(generated, "channel", id="DisneyChannel.de@SD")
        ET.SubElement(channel, "display-name").text = "Disney"
        programme = ET.SubElement(generated, "programme", channel="DisneyChannel.de@SD", start="20261119010000 +0100")
        ET.SubElement(programme, "title").text = "Bluey"
        problems = validate.missing_channel_problems(
            previous, generated, {"DisneyChannel.de@Germany"}
        )
        self.assertTrue(any("not the same station" in problem for problem in problems))

    def test_destination_without_real_programmes_is_rejected(self):
        previous = ET.Element("tv")
        old = ET.SubElement(previous, "channel", id="hrfernsehen.de@Germany")
        ET.SubElement(old, "display-name").text = "hr-fernsehen"
        generated = ET.Element("tv")
        channel = ET.SubElement(generated, "channel", id="hrfernsehen.de@SD")
        ET.SubElement(channel, "display-name").text = "hr-fernsehen"
        programme = ET.SubElement(generated, "programme", channel="hrfernsehen.de@SD", start="20261119010000 +0100")
        ET.SubElement(programme, "title").text = "Sendepause"
        problems = validate.missing_channel_problems(previous, generated, {"hrfernsehen.de@Germany"})
        self.assertTrue(any("no real programmes" in problem for problem in problems))

    def test_empty_kept_channel_is_not_a_loss(self):
        previous = ET.Element("tv")
        generated = ET.Element("tv")
        for channel_id, name in (
            ("ZDF.de@Germany", "ZDF"),
            ("SkySportBundesliga9.de@SD", "Sky Sport Bundesliga 8"),
        ):
            channel = ET.SubElement(previous, "channel", id=channel_id)
            ET.SubElement(channel, "display-name").text = name
            kept = ET.SubElement(generated, "channel", id=channel_id)
            ET.SubElement(kept, "display-name").text = name
        old = ET.SubElement(
            previous,
            "programme",
            channel="SkySportBundesliga9.de@SD",
            start="20261118010000 +0100",
        )
        ET.SubElement(old, "title").text = "TEST"
        programme = ET.SubElement(
            generated, "programme", channel="ZDF.de@Germany", start="20261119010000 +0100"
        )
        ET.SubElement(programme, "title").text = "heute"
        generated_ids = {channel.get("id") for channel in generated.findall("channel")}
        previous_ids = {channel.get("id") for channel in previous.findall("channel")}
        missing = {channel_id for channel_id in previous_ids if channel_id and channel_id not in generated_ids}
        problems = validate.missing_channel_problems(previous, generated, missing)
        self.assertEqual(missing, set())
        self.assertEqual(problems, [])

    def test_unlisted_disappearance_is_still_rejected(self):
        previous = ET.Element("tv")
        for channel_id, name in (("ZDF.de@Germany", "ZDF"), ("Other.de@SD", "Other")):
            channel = ET.SubElement(previous, "channel", id=channel_id)
            ET.SubElement(channel, "display-name").text = name
        generated = ET.Element("tv")
        channel = ET.SubElement(generated, "channel", id="ZDF.de@Germany")
        ET.SubElement(channel, "display-name").text = "ZDF"
        problems = validate.missing_channel_problems(previous, generated, {"Other.de@SD"})
        self.assertEqual(problems, ["previous channels missing: Other.de@SD"])

    def test_incorrect_id_cannot_be_migrated_away(self):
        previous = ET.Element("tv")
        old = ET.SubElement(previous, "channel", id="deutschewelle.de")
        ET.SubElement(old, "display-name").text = "Deutsche Welle"
        generated = ET.Element("tv")
        channel = ET.SubElement(generated, "channel", id="DeutscheWelle.de@SD")
        ET.SubElement(channel, "display-name").text = "Deutsche Welle"
        programme = ET.SubElement(
            generated, "programme", channel="DeutscheWelle.de@SD", start="20261119010000 +0100"
        )
        ET.SubElement(programme, "title").text = "Journal"
        problems = validate.missing_channel_problems(
            previous,
            generated,
            {"deutschewelle.de"},
            {"deutschewelle.de": "DeutscheWelle.de@SD"},
        )
        self.assertTrue(any("incorrect id" in problem for problem in problems))
        self.assertFalse(any("previous channels missing" in problem for problem in problems))

    def test_two_channels_cannot_claim_one_destination(self):
        previous = ET.Element("tv")
        for channel_id in ("SkySport1.de@Germany", "SKYsp1.de@SD"):
            channel = ET.SubElement(previous, "channel", id=channel_id)
            ET.SubElement(channel, "display-name").text = "Sky Sport Top Event"
        generated = ET.Element("tv")
        channel = ET.SubElement(generated, "channel", id="SkySport1.de@SD")
        ET.SubElement(channel, "display-name").text = "Sky Sport Top Event"
        programme = ET.SubElement(generated, "programme", channel="SkySport1.de@SD", start="20261119010000 +0100")
        ET.SubElement(programme, "title").text = "NHL"
        problems = validate.missing_channel_problems(
            previous,
            generated,
            {"SkySport1.de@Germany", "SKYsp1.de@SD"},
            {"SkySport1.de@Germany": "SkySport1.de@SD", "SKYsp1.de@SD": "SkySport1.de@SD"},
        )
        self.assertTrue(any("claimed by" in problem for problem in problems))


class GermanPublishValidateTests(unittest.TestCase):
    def test_validator_accepts_the_rename_and_still_rejects_other_losses(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = root / "previous.xml"
            generated = root / "generated.xml"
            aliases = root / "aliases.json"
            clones = root / "clones.json"
            write_guide(
                previous,
                [("DisneyChannel.de@Germany", "Disney Channel"), ("ZDF.de@Germany", "ZDF")],
                [("DisneyChannel.de@Germany", "Micky"), ("ZDF.de@Germany", "heute")],
            )
            write_guide(
                generated,
                [("DisneyChannel.de@SD", "Disney Channel"), ("ZDF.de@Germany", "ZDF")],
                [("DisneyChannel.de@SD", "Micky"), ("ZDF.de@Germany", "heute")],
            )
            aliases.write_text(
                json.dumps({"DisneyChannel.de@SD": ["DE Disney Channel HD"]}),
                encoding="utf-8",
            )
            clones.write_text(json.dumps({"disneychannel.de": "DisneyChannel.de@SD"}), encoding="utf-8")
            with patch.object(validate, "MIN_CHANNELS", 1), patch.object(validate, "MIN_PROGRAMMES", 1):
                self.assertEqual(validate.validate(generated, previous, aliases, clones), [])
            write_guide(
                generated,
                [("DisneyChannel.de@SD", "Disney Channel")],
                [("DisneyChannel.de@SD", "Micky")],
            )
            with patch.object(validate, "MIN_CHANNELS", 1), patch.object(validate, "MIN_PROGRAMMES", 1):
                problems = validate.validate(generated, previous, aliases, clones)
            self.assertTrue(any("ZDF.de@Germany" in problem for problem in problems))

    def test_duplicate_and_incorrect_channel_ids_stay_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guide = root / "guide.xml"
            previous = root / "previous.xml"
            aliases = root / "aliases.json"
            clones = root / "clones.json"
            aliases.write_text("{}", encoding="utf-8")
            clones.write_text("{}", encoding="utf-8")
            write_guide(previous, [("ZDF.de@Germany", "ZDF")], [("ZDF.de@Germany", "heute")])
            tree = ET.Element("tv")
            for _ in range(2):
                channel = ET.SubElement(tree, "channel", id="ZDF.de@Germany")
                ET.SubElement(channel, "display-name").text = "ZDF"
            programme = ET.SubElement(tree, "programme", channel="ZDF.de@Germany", start="20261119010000 +0100")
            ET.SubElement(programme, "title").text = "heute"
            ET.ElementTree(tree).write(guide, encoding="utf-8", xml_declaration=True)
            with patch.object(validate, "MIN_CHANNELS", 1), patch.object(validate, "MIN_PROGRAMMES", 1):
                problems = validate.validate(guide, previous, aliases, clones)
            self.assertTrue(any("duplicate or empty channel ids" in problem for problem in problems))
            write_guide(guide, [("vox.de", "VOX")], [("vox.de", "heute")])
            with patch.object(validate, "MIN_CHANNELS", 1), patch.object(validate, "MIN_PROGRAMMES", 1):
                problems = validate.validate(guide, previous, aliases, clones)
            self.assertTrue(any("unsafe channel id vox.de" in problem for problem in problems))
            self.assertTrue(any("ZDF.de@Germany" in problem for problem in problems))

    def test_validator_accepts_a_catalog_channel_without_programmes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = root / "previous.xml"
            generated = root / "generated.xml"
            aliases = root / "aliases.json"
            clones = root / "clones.json"
            write_guide(
                previous,
                [("ZDF.de@Germany", "ZDF"), ("SkySportBundesliga9.de@SD", "Sky Sport Bundesliga 8")],
                [("ZDF.de@Germany", "heute"), ("SkySportBundesliga9.de@SD", "TEST")],
            )
            write_guide(
                generated,
                [("ZDF.de@Germany", "ZDF"), ("SkySportBundesliga9.de@SD", "Sky Sport Bundesliga 8")],
                [("ZDF.de@Germany", "heute")],
            )
            aliases.write_text(
                json.dumps({"SkySportBundesliga9.de@SD": ["DE Sky Sport Bundesliga 8 HD [ Match Time ]"]}),
                encoding="utf-8",
            )
            clones.write_text("{}", encoding="utf-8")
            with patch.object(validate, "MIN_CHANNELS", 1), patch.object(validate, "MIN_PROGRAMMES", 1):
                self.assertEqual(validate.validate(generated, previous, aliases, clones), [])
