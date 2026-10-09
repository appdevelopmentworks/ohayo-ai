"""Plain-text helpers."""

import lxml.html

SUMMARY_LIMIT = 600


def html_to_text(fragment: str) -> str:
    """Strip tags and collapse whitespace."""
    if not fragment or not fragment.strip():
        return ""
    root = lxml.html.fragment_fromstring(fragment, create_parent="div")
    return " ".join(root.text_content().split())


def shorten(text: str, limit: int = SUMMARY_LIMIT) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
