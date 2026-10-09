"""Product Hunt AI category (Atom). The feed mixes in old posts; the 48h window drops them."""

from urllib.parse import urlsplit, urlunsplit

import lxml.html

from ai_news.models import Item
from ai_news.sources.rss import entry_time, parse_entries
from ai_news.text import shorten


def tagline(body: str) -> str:
    """The first paragraph of the entry is the product tagline."""
    if not body.strip():
        return ""
    root = lxml.html.fragment_fromstring(body, create_parent="div")
    paragraphs = root.findall(".//p")
    return shorten(" ".join(paragraphs[0].text_content().split())) if paragraphs else ""


def parse(content: bytes, source_id: str) -> list[Item]:
    items = []
    for entry in parse_entries(content):
        published = entry_time(entry)
        title = " ".join(entry.get("title", "").split())
        link = entry.get("link")
        if not (published and title and link):
            continue
        parts = urlsplit(link)
        items.append(
            Item(
                source=source_id,
                title=title,
                url=urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")),
                published=published,
                summary=tagline(entry.get("summary", "")),
            )
        )
    return items
