"""Published XMLTV guides live in the guides/ directory.

National guides are ``guides/guide-XX.xml`` and ``guides/guide-arabic.xml``.
The global guide is ``guides/guide.xml.gz``. Future national guides belong in
that directory. The uncompressed working copy used by the local grabber stays
at ``guide.xml`` in the repository root.

A directory that already contains ``guide-*.xml`` directly, and has no
``guides/`` subdirectory, is scanned as given. Unit-test fixtures use that layout.
"""

from __future__ import annotations

from pathlib import Path

GUIDES_DIRNAME = "guides"
GLOBAL_GZIP_NAME = "guide.xml.gz"
LEGACY_GLOBAL_NAME = "guide.xml"


def national_guide_dir(root: Path) -> Path:
    """Return the directory that holds published national guides for ``root``."""
    nested = root / GUIDES_DIRNAME
    if nested.is_dir():
        return nested
    return root


def national_guide(root: Path, name: str) -> Path:
    return national_guide_dir(root) / name
