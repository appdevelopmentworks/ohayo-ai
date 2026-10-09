"""Simon Willison's Weblog: a detector for news we would otherwise miss.

Only AI-tagged link posts and long-form entries are used, and the card links to the
primary source they point at, never to the blog itself. Quotes, project releases,
TILs and HN comments are skipped.
"""

from urllib.parse import urlsplit

import lxml.html

from ai_news.models import Item
from ai_news.sources.rss import entry_text, entry_time, parse_entries

AI_TAGS = {"ai", "generative-ai", "llms", "machine-learning"}
NOT_PRIMARY_HOSTS = ("simonwillison.net", "news.ycombinator.com", "twitter.com", "x.com")


def _is_primary(href: str) -> bool:
    parts = urlsplit(href)
    host = parts.hostname or ""
    if parts.scheme not in ("http", "https") or not host:
        return False
    if any(host == h or host.endswith("." + h) for h in NOT_PRIMARY_HOSTS):
        return False
    return not (host == "github.com" and parts.path.startswith("/simonw/"))


def primary_link(body: str) -> str | None:
    """Find the primary source a post points at, or None if it is not a news post."""
    if not body.strip():
        return None
    root = lxml.html.fragment_fromstring(body, create_parent="div")
    if not len(root) or root[0].tag != "p":
        return None  # quotations start with <blockquote>
    first = root[0]
    if (first.text or "").strip():
        links = [a.get("href", "") for a in first.iter("a")]
    elif len(first) and first[0].tag == "strong":
        strong = first[0]
        # Link post: <p><strong><a href="primary">Title</a></strong></p>
        # Labelled post: <p><strong>Release:</strong> ...</p> (TIL, Tool, Research, ...)
        if (strong.text or "").strip() or not len(strong) or strong[0].tag != "a":
            return None
        links = [strong[0].get("href", "")]
    elif len(first) and first[0].tag == "a" and first[0].text_content().strip() == "My comment":
        return None
    else:
        links = [a.get("href", "") for a in first.iter("a")]
    return next((href for href in links if _is_primary(href)), None)


def parse(content: bytes, source_id: str) -> list[Item]:
    items = []
    for entry in parse_entries(content):
        tags = {tag.get("term", "") for tag in entry.get("tags", [])}
        published = entry_time(entry)
        title = " ".join(entry.get("title", "").split())
        url = primary_link(entry.get("summary", ""))
        if not (tags & AI_TAGS and published and title and url):
            continue
        items.append(
            Item(
                source=source_id,
                title=title,
                url=url,
                published=published,
                summary=entry_text(entry),
                discussion_url=entry.get("link"),
            )
        )
    return items
