"""Source registry and collection.

Each source is fetched, parsed, filtered to its time window and trimmed to its top N.
A failing source never stops the run; it is reported with zero items instead.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ai_news.models import Item
from ai_news.sources import anthropic, hf, hn, producthunt, rss, simonwillison

log = logging.getLogger(__name__)

WINDOW = timedelta(hours=36)
PAPERS_DATE_LAG = timedelta(hours=12)  # today's Daily Papers list is still filling up in the morning UTC


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    url: str  # may use {date} (YYYY-MM-DD) and {since} (unix time at the window start)
    parse: Callable[[bytes, str], list[Item]]
    ext: str = "xml"  # fixture file extension
    max_age: timedelta | None = WINDOW
    top_n: int | None = None  # keep the N items with the most points


Fetch = Callable[[Source, str], bytes]

# Order is priority: when duplicates merge, the earlier source's item is kept.
SOURCES: tuple[Source, ...] = (
    Source("openai", "OpenAI News", "https://openai.com/news/rss.xml", rss.parse),
    Source("anthropic", "Anthropic News", anthropic.PAGE_URL, anthropic.parse, ext="html"),
    Source(
        "google_ai",
        "Google AI (The Keyword)",
        "https://blog.google/innovation-and-ai/technology/ai/rss/",
        rss.parse,
    ),
    Source("deepmind", "Google DeepMind", "https://deepmind.google/blog/rss.xml", rss.parse),
    Source("hf_blog", "Hugging Face Blog", "https://huggingface.co/blog/feed.xml", rss.parse),
    Source(
        "hf_papers",
        "HF Daily Papers",
        "https://huggingface.co/api/daily_papers?date={date}",
        hf.parse_papers,
        ext="json",
        max_age=None,
        top_n=3,
    ),
    Source(
        "hf_models",
        "HF Trending Models",
        "https://huggingface.co/api/models?sort=trendingScore&limit=20",
        hf.parse_models,
        ext="json",
        max_age=timedelta(days=14),  # trending lists keep old models; only recent ones are news
        top_n=5,
    ),
    Source(
        "producthunt",
        "Product Hunt (AI)",
        "https://www.producthunt.com/feed?category=artificial-intelligence",
        producthunt.parse,
        max_age=timedelta(hours=48),
    ),
    Source(
        "hn",
        "Hacker News",
        "https://hn.algolia.com/api/v1/search_by_date"
        "?tags=story&numericFilters=created_at_i>{since},points>30&hitsPerPage=200",
        hn.parse,
        ext="json",
        top_n=5,
    ),
    Source(
        "simonwillison",
        "Simon Willison's Weblog",
        "https://simonwillison.net/atom/everything/",
        simonwillison.parse,
    ),
)


@dataclass
class SourceResult:
    source: Source
    parsed: int = 0  # items the source returned before windowing; 0 means "looks broken"
    items: list[Item] = field(default_factory=list)
    error: str | None = None


def source_url(source: Source, now: datetime) -> str:
    return source.url.format(
        date=(now - PAPERS_DATE_LAG).date().isoformat(),
        since=int((now - WINDOW).timestamp()),
    )


def collect_one(source: Source, now: datetime, fetch: Fetch) -> SourceResult:
    try:
        parsed = source.parse(fetch(source, source_url(source, now)), source.id)
    except Exception as exc:  # one broken source must not stop the morning run
        log.warning("%s: failed: %s", source.id, exc, exc_info=log.isEnabledFor(logging.DEBUG))
        return SourceResult(source, error=f"{type(exc).__name__}: {exc}")
    items = [i for i in parsed if source.max_age is None or i.published >= now - source.max_age]
    if source.top_n is not None:
        items = sorted(items, key=lambda i: i.points or 0, reverse=True)[: source.top_n]
    return SourceResult(source, parsed=len(parsed), items=items)


def collect(now: datetime, fetch: Fetch, sources: tuple[Source, ...] = SOURCES) -> list[SourceResult]:
    return [collect_one(source, now, fetch) for source in sources]
