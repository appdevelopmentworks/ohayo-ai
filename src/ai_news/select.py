"""Candidate selection: deduplication (rule filter and LLM ranking come in phase 3)."""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ai_news.models import Item
from ai_news.sources import SOURCES
from ai_news.state import is_seen

TRACKING_PARAM = re.compile(r"^(utm_\w+|ref|ref_src|fbclid|gclid|mc_cid|mc_eid|app_id)$")
TITLE_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "for", "in", "on", "with", "by", "at", "from",
    "is", "are", "our", "your", "new", "introducing", "announcing",
}
TITLE_TOKEN = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*")
TITLE_JACCARD = 0.6
SOURCE_PRIORITY = {source.id: rank for rank, source in enumerate(SOURCES)}


def normalize_url(url: str) -> str:
    """Canonical form for comparing URLs: https, no www, no tracking params or fragment."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").removeprefix("www.")
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"
    query = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not TRACKING_PARAM.match(k.lower())
    )
    return urlunsplit(("https", host, parts.path.rstrip("/"), urlencode(query), ""))


def title_tokens(title: str) -> frozenset[str]:
    text = unicodedata.normalize("NFKC", title).lower()
    text = re.sub(r"[‐-―]", "-", text)
    return frozenset(t for t in TITLE_TOKEN.findall(text) if t not in TITLE_STOPWORDS)


def similar_titles(a: frozenset[str], b: frozenset[str]) -> bool:
    if not a or not b:
        return False
    small, large = sorted((a, b), key=len)
    if len(small) >= 3 and small <= large:
        return True
    return len(a & b) / len(a | b) >= TITLE_JACCARD


@dataclass
class DedupeResult:
    items: list[Item]
    keys: set[str] = field(default_factory=set)  # every normalized URL looked at, to mark as seen
    skipped_seen: int = 0
    merged: int = 0


def dedupe(items: list[Item], seen: dict[str, str], today: date) -> DedupeResult:
    """Drop items seen on earlier days and merge same-story items across sources.

    Items are visited in source priority order, so the official post wins and
    the others are recorded in `also_in`.
    """
    ordered = sorted(
        items,
        key=lambda i: (SOURCE_PRIORITY.get(i.source, len(SOURCE_PRIORITY)), -(i.points or 0)),
    )
    result = DedupeResult(items=[])
    by_url: dict[str, Item] = {}
    kept_tokens: list[tuple[frozenset[str], Item]] = []
    for item in ordered:
        key = normalize_url(item.url)
        if is_seen(seen, key, today):
            result.skipped_seen += 1
            continue
        result.keys.add(key)
        tokens = title_tokens(item.title)
        match = by_url.get(key) or next((kept for t, kept in kept_tokens if similar_titles(t, tokens)), None)
        if match is not None:
            if item.source != match.source:
                match.also_in.setdefault(item.source, item.points)
            result.merged += 1
            continue
        kept = item.model_copy(deep=True)
        by_url[key] = kept
        kept_tokens.append((tokens, kept))
        result.items.append(kept)
    return result
