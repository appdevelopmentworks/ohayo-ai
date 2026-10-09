"""Generic RSS / Atom feeds (OpenAI, Google AI, DeepMind, Hugging Face Blog)."""

from datetime import UTC, datetime

import feedparser

from ai_news.models import Item
from ai_news.text import html_to_text, shorten


def parse_entries(content: bytes) -> list[feedparser.FeedParserDict]:
    feed = feedparser.parse(content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"unreadable feed: {feed.get('bozo_exception')}")
    return feed.entries


def entry_time(entry) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    return datetime(*parsed[:6], tzinfo=UTC) if parsed else None


def entry_text(entry) -> str:
    """The longest of summary/content, as plain text."""
    bodies = [entry.get("summary", "")] + [c.get("value", "") for c in entry.get("content", [])]
    return shorten(html_to_text(max(bodies, key=len)))


def parse(content: bytes, source_id: str) -> list[Item]:
    items = []
    for entry in parse_entries(content):
        published = entry_time(entry)
        title = " ".join(entry.get("title", "").split())
        url = entry.get("link")
        if not (published and title and url):
            continue
        items.append(
            Item(
                source=source_id,
                title=title,
                url=url,
                published=published,
                summary=entry_text(entry),
            )
        )
    return items
