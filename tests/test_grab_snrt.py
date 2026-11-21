import importlib.util
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "grab_snrt.py"
TZ = ZoneInfo("Africa/Casablanca")

HTML = """
<html><head><title>شبكة برامج قناة العيون | SNRT</title></head><body>
<div class="row grille-line 20261121 d-none">
  <div class="col grille-time">21H00</div>
  <h2 class="program-title-sm">نشرة العيون</h2>
  <div class="program-description-sm">أخبار الجهة</div>
</div>
<div class="row grille-line 20261121">
  <div class="col grille-time">22H15</div>
  <h2 class="program-title-sm">حرف وتحف</h2>
</div>
<div class="row grille-line 20261122">
  <div class="col grille-time">06H00</div>
  <h2 class="program-title-sm">صباح العيون</h2>
</div>
<div class="row grille-line 20261123">
  <div class="col grille-time">08H00</div>
  <h2 class="program-title-sm">خارج النافذة</h2>
</div>
</body></html>
"""


def load_module():
    spec = importlib.util.spec_from_file_location("grab_snrt", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SnrtGridTests(unittest.TestCase):
    def test_grid_keeps_two_local_days_and_chains_stops(self):
        grab = load_module()
        rows = grab.parse_grid(HTML)
        window = {datetime(2026, 11, 21).date(), datetime(2026, 11, 22).date()}
        kept = [row for row in rows if row["start"].astimezone(TZ).date() in window]
        self.assertEqual([row["title"] for row in kept], ["نشرة العيون", "حرف وتحف", "صباح العيون"])
        self.assertEqual(kept[0]["stop"], kept[1]["start"])
        self.assertEqual(kept[1]["stop"], kept[2]["start"])
        self.assertEqual(kept[0]["description"], "أخبار الجهة")
        self.assertNotIn("خارج النافذة", [row["title"] for row in kept])

    def test_radio_nodes_are_refused(self):
        grab = load_module()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "channels.xml"
            path.write_text(
                '<channels><channel site="snrt.ma" site_id="4076" '
                'xmltv_id="Radio.ma@SD" expect="إذاعة">Alidaa</channel></channels>',
                encoding="utf-8",
            )
            with self.assertRaises(grab.GrabError):
                grab.parse_channels_file(path)

    def test_append_skips_a_signal_already_programmed_elsewhere(self):
        grab = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "guide.xml"
            occupied = root / "guide-fr.xml"
            target.write_text(
                "<tv><channel id=\"Other.ma@SD\"><display-name>Other</display-name></channel></tv>",
                encoding="utf-8",
            )
            occupied.write_text(
                "<tv><channel id=\"LaayouneTV.ma@SD\"><display-name>Laâyoune</display-name></channel>"
                "<programme start=\"20261121140000 +0100\" stop=\"20261121150000 +0100\" "
                "channel=\"LaayouneTV.ma@SD\"><title>Ya publicada</title></programme></tv>",
                encoding="utf-8",
            )
            incoming = ET.Element("tv")
            channel = ET.SubElement(incoming, "channel", id="LaayouneTV.ma@SD")
            ET.SubElement(channel, "display-name").text = "Laâyoune"
            programme = ET.SubElement(
                incoming,
                "programme",
                channel="LaayouneTV.ma@SD",
                start="20261121140000 +0100",
                stop="20261121150000 +0100",
            )
            ET.SubElement(programme, "title").text = "Duplicada"
            fresh = ET.SubElement(incoming, "channel", id="TamazightTV.ma@SD")
            ET.SubElement(fresh, "display-name").text = "Tamazight"
            fresh_programme = ET.SubElement(
                incoming,
                "programme",
                channel="TamazightTV.ma@SD",
                start="20261121140000 +0100",
                stop="20261121150000 +0100",
            )
            ET.SubElement(fresh_programme, "title").text = "أمازيغ"
            added = grab.append_unoccupied(target, incoming, [occupied])
            merged = ET.parse(target).getroot()
            self.assertEqual(added, ["TamazightTV.ma@SD"])
            self.assertIsNone(merged.find("channel[@id='LaayouneTV.ma@SD']"))
            self.assertEqual(
                [node.text for node in merged.findall("programme/title")],
                ["أمازيغ"],
            )


if __name__ == "__main__":
    unittest.main()
