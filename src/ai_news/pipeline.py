"""The daily pipeline, free of file IO so it runs the same on fixtures.

collect -> dedupe -> rule filter -> rank (1 call) -> bodies -> summaries (up to 20 calls)
-> daily summary (1 call) -> edition
"""

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime

from ai_news import select, state
from ai_news.article import BodyFetch
from ai_news.llm import LLM, LLMError
from ai_news.schemas import Article, Daily, Edition, Stats
from ai_news.sources import Fetch, SourceResult, collect
from ai_news.summarize import daily_summary, summarize, weather_for

log = logging.getLogger(__name__)

FALLBACK_LINES = {
    "thunder": "今日は大きなニュースの日。まずは上から読んでみよう",
    "cloudy": "今日はちょっと動きあり。気になるものからどうぞ",
    "sunny": "今日はおだやかな日。ゆっくり読んでいこう",
}


@dataclass
class RunResult:
    today: date
    sources: list[SourceResult]
    dedupe: select.DedupeResult
    ranked: int  # candidates sent to the ranking call
    edition: Edition | None  # None when the run could not produce a page
    error: str | None
    seen: dict[str, str]  # updated state to save
    health: dict[str, dict[str, int]]  # updated state to save
    failing: list[str]  # sources with zero items on consecutive days


def run(
    now: datetime,
    fetch: Fetch,
    seen: dict[str, str],
    health: dict[str, dict[str, int]],
    llm: LLM,
    body_fetch: BodyFetch,
) -> RunResult:
    started = time.monotonic()
    today = state.run_date(now)
    results = collect(now, fetch)
    health = state.update_health(health, {r.source.id: r.parsed for r in results}, today)
    dedupe = select.dedupe([item for r in results for item in r.items], seen, today)
    candidates = select.prefilter(dedupe.items, now)

    def finish(edition: Edition | None, error: str | None) -> RunResult:
        return RunResult(
            today=today,
            sources=results,
            dedupe=dedupe,
            ranked=len(candidates),
            edition=edition,
            error=error,
            # Mark items seen only when a page was made, so a failed morning can be re-run.
            seen=state.update_seen(seen, dedupe.keys, today) if edition else seen,
            health=health,
            failing=state.failing_sources(health, today),
        )

    try:
        picked = select.rank(candidates, llm)
    except LLMError as exc:
        return finish(None, f"ranking failed: {exc}")
    log.info("ranking: %d of %d candidates scored %d or more", len(picked), len(candidates), select.MIN_SCORE)

    articles: list[Article] = []
    for ranked in picked:
        body = body_fetch(ranked.item)
        if article := summarize(ranked, body, llm):
            articles.append(article)
    if not articles:
        return finish(None, "no article could be summarized")
    for article in articles:
        article.score = max(article.score, select.MIN_SCORE)  # it passed the ranking cut
    order = {a.id: n for n, a in enumerate(articles)}
    articles.sort(key=lambda a: (-a.score, order[a.id]))

    weather = weather_for(articles)
    try:
        daily = daily_summary(articles, weather, llm)
    except LLMError as exc:
        log.error("daily summary failed, using fallback text: %s", exc)
        daily = Daily.model_construct(
            digest=[a.title_ja for a in articles[:3]], mascot_line=FALLBACK_LINES[weather]
        )

    edition = Edition(
        date=today,
        generated_at=now,
        weather=weather,
        digest=daily.digest,
        mascot_line=daily.mascot_line,
        articles=articles,
        stats=Stats(
            collected=sum(len(r.items) for r in results),
            candidates=len(dedupe.items),
            ranked=len(candidates),
            selected=len(articles),
            llm_calls=llm.calls,
            providers=llm.used,
            seconds=round(time.monotonic() - started, 1),
        ),
    )
    return finish(edition, None)
