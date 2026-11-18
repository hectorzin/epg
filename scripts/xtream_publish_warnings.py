#!/usr/bin/env python3
"""Report configured Xtream alias IDs absent from a generated national guide."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping


def missing_configured_channels(
    channel_ids: Iterable[str],
    display_aliases: Mapping[str, object],
    xtream_aliases: Mapping[str, object],
) -> tuple[list[str], list[str]]:
    """Return absent display-alias targets and Xtream clone IDs, in stable order."""
    present = set(channel_ids)
    return (
        sorted(set(display_aliases) - present),
        sorted(set(xtream_aliases) - present),
    )


def warn_missing_configured_channels(
    region: str,
    channel_ids: Iterable[str],
    display_aliases: Mapping[str, object],
    xtream_aliases: Mapping[str, object],
    *,
    emit: Callable[[str], object] = print,
) -> tuple[list[str], list[str]]:
    """Emit GitHub Actions warnings; missing optional aliases never fail publication."""
    missing_display, missing_clones = missing_configured_channels(
        channel_ids, display_aliases, xtream_aliases
    )
    if missing_display:
        emit(
            f"::warning::{region}: {len(missing_display)} configured display-alias channel(s) "
            f"absent; aliases skipped for this run: {', '.join(missing_display)}"
        )
    if missing_clones:
        emit(
            f"::warning::{region}: {len(missing_clones)} configured Xtream clone ID(s) absent; "
            f"clones not generated: {', '.join(missing_clones)}"
        )
    return missing_display, missing_clones
