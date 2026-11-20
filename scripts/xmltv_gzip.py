#!/usr/bin/env python3
"""Deterministic gzip packaging for the published global XMLTV guide.

National guides stay plain XML. The orchestrator writes the merged global guide
to a temporary XML file, validates that file, then packs ``guide.xml.gz`` at
compression level 9 with ``mtime=0``. The decompressed payload must match the
validated XML byte for byte.
"""

from __future__ import annotations

import argparse
import gzip
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

GZIP_LEVEL = 9
GZIP_MAGIC = b"\x1f\x8b"
PUBLISHED_NAME = "guide.xml.gz"
LEGACY_NAME = "guide.xml"
GLOBAL_GUIDE_NAMES = frozenset({PUBLISHED_NAME, LEGACY_NAME})


def is_global_guide(path: Path) -> bool:
    return path.name.casefold() in GLOBAL_GUIDE_NAMES


def published_global_guide(root: Path) -> Path:
    """Prefer the published gzip, then a local uncompressed global guide."""
    compressed = root / PUBLISHED_NAME
    if compressed.is_file():
        return compressed
    return root / LEGACY_NAME


def assert_gzip_header(payload: bytes) -> None:
    if len(payload) < 10 or payload[:3] != b"\x1f\x8b\x08" or payload[3] != 0:
        raise ValueError("gzip header must be a bare gzip member")
    if payload[4:8] != b"\x00\x00\x00\x00":
        raise ValueError("gzip mtime must be 0")
    if payload[8] != 2:
        raise ValueError("gzip compression level must be 9")


def compress_xmltv(xml_bytes: bytes) -> bytes:
    if not xml_bytes:
        raise ValueError("refusing to compress empty XMLTV")
    payload = gzip.compress(xml_bytes, compresslevel=GZIP_LEVEL, mtime=0)
    assert_gzip_header(payload)
    if gzip.decompress(payload) != xml_bytes:
        raise ValueError("decompressed guide does not match validated XML")
    return payload


def read_xmltv_bytes(path: Path) -> bytes:
    """Return XML bytes, decompressing when the file is gzip."""
    data = path.read_bytes()
    if not data:
        raise ValueError(f"{path}: empty guide")
    if not data.startswith(GZIP_MAGIC):
        return data
    try:
        return gzip.decompress(data)
    except gzip.BadGzipFile as exc:
        raise ValueError(f"{path}: invalid gzip payload") from exc


def parse_xmltv(path: Path) -> ET.Element:
    """Parse an XMLTV file. Gzip members are decompressed first."""
    try:
        return ET.fromstring(read_xmltv_bytes(path))
    except ET.ParseError as exc:
        raise ValueError(f"{path}: malformed XMLTV ({exc})") from exc


def validate_global_xml(path: Path) -> tuple[int, int]:
    """Checks applied to the temporary plain-XML global guide before packing."""
    root = ET.parse(path).getroot()
    programmes = root.findall("programme")
    if not programmes:
        raise ValueError("Global guide has no programmes")
    return len(root.findall("channel")), len(programmes)


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def pack_verified(xml_path: Path, gzip_path: Path) -> tuple[int, int]:
    """Compress a validated XML guide and require a byte-identical round-trip."""
    xml_bytes = xml_path.read_bytes()
    payload = compress_xmltv(xml_bytes)
    _atomic_write(gzip_path, payload)
    stored = gzip_path.read_bytes()
    if stored != payload or gzip.decompress(stored) != xml_bytes:
        raise ValueError("decompressed guide does not match validated XML")
    return len(xml_bytes), len(stored)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="Validate the temporary plain XML global guide")
    validate.add_argument("xml", type=Path)
    pack = sub.add_parser("pack", help="Write guide.xml.gz and verify the round-trip")
    pack.add_argument("xml", type=Path)
    pack.add_argument("gzip_path", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "validate":
            channels, programmes = validate_global_xml(args.xml)
            print(f"Validated global guide: {channels} channels, {programmes} programmes")
            return 0
        xml_bytes, gzip_bytes = pack_verified(args.xml, args.gzip_path)
        print(f"Packed {args.gzip_path.name}: {xml_bytes} XML bytes -> {gzip_bytes} gzip bytes")
    except (OSError, ET.ParseError, ValueError, gzip.BadGzipFile) as exc:
        print(f"Global guide gzip failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
