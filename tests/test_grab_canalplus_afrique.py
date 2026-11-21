import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "grab_canalplus_afrique.py"

DAY = {
    "timeSlices": [
        {
            "contents": [
                {
                    "title": "RTS 1 Sénégal",
                    "startTime": 1795240800000,
                    "endTime": 1795244400000,
                    "onClick": {"URLPage": "https://hodor.canalplus.pro/api/v2/detail/should-not-be-requested"},
                },
                {
                    "title": "Journal",
                    "startTime": 1795244400000,
                    "endTime": 1795248000000,
                },
            ]
        }
    ]
}


def load_module():
    spec = importlib.util.spec_from_file_location("grab_canalplus_afrique", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CanalPlusAfriqueTests(unittest.TestCase):
    def test_day_listing_uses_start_and_end_without_detail_pages(self):
        grab = load_module()
        rows = grab.programmes_from_day(DAY, "sn#180076")
        self.assertEqual(
            [(row["title"], row["start"], row["stop"]) for row in rows],
            [
                ("RTS 1 Sénégal", "20261121060000 +0000", "20261121070000 +0000"),
                ("Journal", "20261121070000 +0000", "20261121080000 +0000"),
            ],
        )

    def test_html_challenge_is_not_copied_into_the_error(self):
        grab = load_module()
        body = b"<!DOCTYPE html><html><body>" + b"secret-page " * 500
        message = grab.short_http_error(403, body)
        self.assertEqual(message, f"HTTP 403 HTML challenge ({len(body)} bytes)")
        self.assertNotIn(b"secret-page".decode(), message)
        self.assertNotIn("DOCTYPE", message)

    def test_retries_a_blocked_day_then_keeps_only_schedule_urls(self):
        grab = load_module()
        calls: list[str] = []
        sleeps: list[float] = []

        def get(url: str) -> bytes:
            calls.append(url)
            if "authenticate.json" in url:
                return json.dumps({"token": "token-1"}).encode()
            if calls.count(url) < 3:
                raise grab.GrabError("HTTP 403 HTML challenge (1800 bytes)")
            return json.dumps(DAY).encode()

        root, failures = grab.grab_days(
            [{"site_id": "sn#180076", "region": "sn", "channel_id": "180076", "name": "RTS"}],
            days=1,
            delay=0.2,
            get=get,
            sleep=sleeps.append,
        )
        self.assertEqual(failures, [])
        self.assertEqual([node.text for node in root.findall("programme/title")], ["RTS 1 Sénégal", "Journal"])
        self.assertTrue(all("detail" not in url and "URLPage" not in url for url in calls))
        self.assertGreaterEqual(sleeps.count(3), 1)
        self.assertGreaterEqual(sleeps.count(6), 1)


if __name__ == "__main__":
    unittest.main()
