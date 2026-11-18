import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "xtream_publish_warnings", ROOT / "scripts" / "xtream_publish_warnings.py"
)
warnings = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(warnings)


class XtreamPublishWarningTests(unittest.TestCase):
    def test_missing_configured_ids_are_reported_with_counts_and_names(self):
        messages = []
        missing_display, missing_clones = warnings.warn_missing_configured_channels(
            "Arabic",
            {"present.id"},
            {"present.id": ["Alias"], "missing.display": ["Alias"]},
            {"missing.clone": "present.id", "present.id": "present.id"},
            emit=messages.append,
        )

        self.assertEqual(missing_display, ["missing.display"])
        self.assertEqual(missing_clones, ["missing.clone"])
        self.assertEqual(len(messages), 2)
        self.assertIn("1 configured display-alias", messages[0])
        self.assertIn("missing.display", messages[0])
        self.assertIn("1 configured Xtream clone", messages[1])
        self.assertIn("missing.clone", messages[1])

    def test_complete_configuration_emits_no_warning(self):
        messages = []
        missing = warnings.warn_missing_configured_channels(
            "French",
            {"display.id", "clone.id"},
            {"display.id": ["Alias"]},
            {"clone.id": "display.id"},
            emit=messages.append,
        )

        self.assertEqual(missing, ([], []))
        self.assertEqual(messages, [])


if __name__ == "__main__":
    unittest.main()
