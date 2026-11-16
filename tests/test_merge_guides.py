import importlib.util
import tempfile
import contextlib
import io
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "merge-guides.py"
SPEC = importlib.util.spec_from_file_location("merge_guides", SCRIPT)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def guide(channels, programmes):
    root = ET.Element("tv")
    for cid, name in channels:
        ch = ET.SubElement(root, "channel", id=cid)
        ET.SubElement(ch, "display-name").text = name
    for cid, start, stop, title in programmes:
        p = ET.SubElement(root, "programme", channel=cid, start=start, stop=stop)
        ET.SubElement(p, "title").text = title
    return root


class MergeTests(unittest.TestCase):
    def test_priority_new_channels_overlap_and_dazn_completion(self):
        main = guide(
            [("MovistarPlus.playdc", "Disney Junior"), ("MovistarPlus.dazb2", "DAZN 2")],
            [("MovistarPlus.playdc", "20261115090000 +0000", "20261115100000 +0000", "Disney original"),
             ("MovistarPlus.dazb2", "20261115090000 +0000", "20261115100000 +0000", "Hoops")],
        )
        orange = guide(
            [("Orange.1", "New channel"), ("MovistarPlus.playdc", "Disney Channel"), ("MovistarPlus.dazb2", "DAZN alt")],
            [("Orange.1", "20261115090000 +0000", "20261115100000 +0000", "New show"),
             ("Orange.1", "20261115093000 +0000", "20261115103000 +0000", "Overlap"),
             ("MovistarPlus.playdc", "20261115090000 +0000", "20261115100000 +0000", "Disney duplicate"),
             ("MovistarPlus.dazb2", "20261115100000 +0000", "20261115110000 +0000", "Supplement")],
        )
        ep = guide([("ElPais.5", "Another")], [("ElPais.5", "20261115090000 +0000", "20261115100000 +0000", "Else")])
        out, channels, progs, completed, skipped = mod.merge(main, orange, ep)
        self.assertEqual({c.get("id") for c in out.findall("channel")}, {"MovistarPlus.playdc", "MovistarPlus.dazb2", "Orange.1", "ElPais.5"})
        self.assertEqual(out.find("channel[@id='MovistarPlus.playdc']/display-name[2]").text, "Disney Channel")
        self.assertEqual([p.findtext("title") for p in out.findall("programme[@channel='MovistarPlus.playdc']")], ["Disney original"])
        self.assertEqual([p.findtext("title") for p in out.findall("programme[@channel='MovistarPlus.dazb2']")], ["Hoops", "Supplement"])
        self.assertIn("MovistarPlus.dazb2", completed["orange"])
        self.assertEqual(skipped["overlap"], 1)
        self.assertEqual(channels, {"orange": 1, "elpais": 1})

    def test_exact_duplicates_and_source_priority(self):
        primary = guide([("main", "Main")], [("main", "20261115090000 +0000", "20261115100000 +0000", "Primary")])
        orange = guide([("main", "Renamed"), ("new", "New")], [
            ("new", "20261115090000 +0000", "20261115100000 +0000", "New programme"),
        ])
        elpais = guide([("other", "Other")], [
            ("other", "20261115090000 +0000", "20261115100000 +0000", "Other programme"),
        ])
        out, _, _, _, skipped = mod.merge(primary, orange, elpais)
        self.assertEqual(out.find("channel[@id='main']/display-name").text, "Main")
        self.assertEqual(out.find("channel[@id='new']/display-name").text, "New")
        self.assertEqual(skipped["duplicate"], 0)

    def test_secondary_failure_keeps_primary_and_aliases(self):
        primary = guide([("main", "Main"), ("MovistarPlus.playdc", "Disney Junior")], [
            ("main", "20261115000000 +0000", "20261115010000 +0000", "Keep me"),
        ])
        orange = guide([("MovistarPlus.playdc", "Disney Channel")], [])
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            out, *_ = mod.merge(primary, orange, None)
        self.assertIn("elpais feed unavailable", stderr.getvalue())
        names = [n.text for n in out.find("channel[@id='MovistarPlus.playdc']").findall("display-name")]
        self.assertEqual(names, ["Disney Junior", "Disney Channel"])
        self.assertEqual(out.find("programme").findtext("title"), "Keep me")
        ids = {c.get("id") for c in out.findall("channel")}
        self.assertTrue(all(p.get("channel") in ids for p in out.findall("programme")))

    def test_partial_total_failures_and_references(self):
        primary = guide([("main", "Main")], [("main", "20261115000000 +0000", "20261115010000 +0000", "Keep")])
        out, *_ = mod.merge(primary, None, None)
        self.assertEqual(len(out.findall("programme")), 1)
        self.assertEqual({p.get("channel") for p in out.findall("programme")}, {c.get("id") for c in out.findall("channel")})


if __name__ == "__main__":
    unittest.main()
