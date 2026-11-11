"""Create natural spoken text while keeping the on-screen answer unchanged.

The spoken copy strips Markdown markers, emoji glyphs and URL destinations so
Edge TTS does not announce asterisks, emoji names, or formatting punctuation.
"""
from __future__ import annotations

import html
import re

_EMOJI_RE = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"  # flags
    "\U0001F300-\U0001FAFF"  # pictographs and emoji
    "\u2600-\u27BF"          # symbols commonly rendered as emoji
    "\uFE0E-\uFE0F"          # variation selectors
    "\u200D"                  # zero-width joiner
    "\u20E3"                  # keycap combining mark
    "\U0001F3FB-\U0001F3FF"  # skin tone modifiers
    "]+",
    flags=re.UNICODE,
)


def clean_for_speech(value: object) -> str:
    """Return readable prose without Markdown decoration or emoji glyphs."""
    text = html.unescape(str(value or ""))
    if not text.strip():
        return ""

    # Code blocks remain visible in the transcript but are not read as punctuation.
    text = re.sub(r"```[\w+-]*\s*[\s\S]*?```", " Code is displayed on screen. ", text)

    # Preserve useful link labels while omitting the URL itself.
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\(https?://[^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)

    # Markdown headings, blockquotes, list bullets and numbered-list prefixes.
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*>\s?", "", text)
    text = re.sub(r"(?m)^\s*[-+*]\s+", "", text)
    text = re.sub(r"(?m)^\s*\d+[.)]\s+", "", text)

    # A star between two digits is a multiplication operator, not formatting.
    text = re.sub(r"(?<=\d)\s*\*\s*(?=\d)", " times ", text)

    # Remove all remaining emphasis/strike/italic markers and emoji.
    text = re.sub(r"[*_~]+", "", text)
    text = _EMOJI_RE.sub(" ", text)

    # Make common visual symbols readable and normalize layout whitespace.
    text = text.replace("&", " and ").replace("•", " ").replace("▪", " ")
    text = re.sub(r"[\t\r ]+", " ", text)
    text = re.sub(r"\s*\n\s*", ". ", text)
    text = re.sub(r"[:;]\s*\.", ".", text)
    text = re.sub(r"(?:\.\s*){2,}", ". ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,;:])(?=\S)", r"\1 ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip(" \t\r\n,;:-")
