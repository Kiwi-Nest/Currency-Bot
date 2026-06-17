from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

_EMOJI_RE = re.compile(r"<a?:[^:]+:\d+>")
_ORDINAL_RE = re.compile(r"\b(\d+)(?:st|nd|rd|th)\b", re.IGNORECASE)
_MEMBERS_RE = re.compile(r"\bMembers:\s*(\d+)", re.IGNORECASE)


def _extract_count(description: str, footer_text: str) -> int | None:
    m = _ORDINAL_RE.search(description)
    if m:
        return int(m.group(1))
    m = _MEMBERS_RE.search(footer_text)
    if m:
        return int(m.group(1))
    return None


def parse_embed(title: str, description: str, footer_text: str = "") -> tuple[int, int | None] | None:
    """Return (delta, anchor_count) or None if not a member event."""
    clean = _EMOJI_RE.sub("", title).strip().lower()

    if "member left" in clean or "user left" in clean:
        count = _extract_count(description, footer_text)
        return -1, count

    if "member joined" in clean or "user joined" in clean:
        count = _extract_count(description, footer_text)
        return 1, count

    return None
