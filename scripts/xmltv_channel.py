"""Normalize <channel> child order to match the XMLTV DTD."""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET

CHANNEL_DTD_GROUPS = ("display-name", "icon", "url")


def _child_key(node: ET.Element) -> tuple[str, str, tuple[tuple[str, str], ...]]:
    return (node.tag, node.text or "", tuple(sorted(node.attrib.items())))


def channel_children_ordered(channel: ET.Element) -> bool:
    """Return True when known children follow display-name*, icon*, url*."""
    phase = 0
    for child in channel:
        tag = child.tag
        if tag == "display-name":
            if phase > 0:
                return False
            continue
        if tag == "icon":
            if phase > 1:
                return False
            phase = max(phase, 1)
            continue
        if tag == "url":
            if phase > 2:
                return False
            phase = max(phase, 2)
            continue
        # Other XMLTV elements (lcn, etc.) may follow url.
        phase = max(phase, 3)
    return True


def normalize_channel_children(channel: ET.Element) -> bool:
    """Reorder channel children to DTD order; preserve text, attrs, and relative order within each group."""
    children = list(channel)
    if not children or channel_children_ordered(channel):
        return False

    grouped: dict[str, list[ET.Element]] = {tag: [] for tag in CHANNEL_DTD_GROUPS}
    trailing: list[ET.Element] = []
    for child in children:
        tag = child.tag
        if tag in grouped:
            grouped[tag].append(child)
        else:
            trailing.append(child)

    for child in children:
        channel.remove(child)

    for tag in CHANNEL_DTD_GROUPS:
        for node in grouped[tag]:
            channel.append(node)
    for node in trailing:
        channel.append(node)
    return True


def normalize_channels_in_tree(root: ET.Element) -> bool:
    changed = False
    for channel in root.findall("channel"):
        if normalize_channel_children(channel):
            changed = True
    return changed


def channel_metadata_fingerprint(channel: ET.Element) -> tuple:
    """Stable tuple for regression checks (id + child payload, ignoring child order)."""
    channel_id = channel.get("id")
    payload = []
    for child in channel:
        payload.append(_child_key(child))
    return (channel_id, tuple(sorted(payload)))


def tree_channel_metadata(root: ET.Element) -> dict[str, tuple]:
    return {c.get("id") or "": channel_metadata_fingerprint(c) for c in root.findall("channel")}


def assert_channel_metadata_unchanged(before: ET.Element, after: ET.Element) -> None:
    """Raise AssertionError if normalization would alter channel semantics."""
    if tree_channel_metadata(before) != tree_channel_metadata(after):
        raise AssertionError("channel metadata changed during normalization")


def deep_copy_normalized(root: ET.Element) -> ET.Element:
    """Return a tree copy with DTD-ordered channels (for dry-run checks)."""
    cloned = copy.deepcopy(root)
    normalize_channels_in_tree(cloned)
    return cloned