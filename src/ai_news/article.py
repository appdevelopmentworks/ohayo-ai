"""Article body extraction with trafilatura, limited to the first 6,000 characters."""

import logging
from collections.abc import Callable

import httpx
import trafilatura

from ai_news.fetch import TIMEOUT, USER_AGENT
from ai_news.models import Item

log = logging.getLogger(__name__)

BODY_LIMIT = 6000
MIN_BODY = 200  # shorter extractions are usually cookie banners or error pages

BodyFetch = Callable[[Item], str | None]


def extract_body(html: bytes | str, url: str) -> str | None:
    text = trafilatura.extract(html, url=url, include_comments=False, include_tables=False)
    if not text or len(text) < MIN_BODY:
        return None
    return text[:BODY_LIMIT]


def fetch_body(item: Item) -> str | None:
    """The article text, or None to fall back to the feed summary ("概要のみ")."""
    try:
        response = httpx.get(
            item.url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, follow_redirects=True
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        log.info("body fetch failed for %s: %s", item.url, exc)
        return None
    return extract_body(response.content, item.url)


def feed_text_body(item: Item) -> str | None:
    """Dry-run stand-in: no network, so the feed summary plays the role of the body."""
    return item.summary or None
