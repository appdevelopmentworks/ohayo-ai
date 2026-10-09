"""The daily pipeline, free of file and network IO so it runs the same on fixtures."""

from dataclasses import dataclass
from datetime import date, datetime

from ai_news import select, state
from ai_news.sources import Fetch, SourceResult, collect


@dataclass
class RunResult:
    today: date
    sources: list[SourceResult]
    dedupe: select.DedupeResult
    seen: dict[str, str]  # updated state to save
    health: dict[str, dict[str, int]]  # updated state to save
    failing: list[str]  # sources with zero items on consecutive days


def run(now: datetime, fetch: Fetch, seen: dict[str, str], health: dict[str, dict[str, int]]) -> RunResult:
    today = state.run_date(now)
    results = collect(now, fetch)
    dedupe = select.dedupe([item for r in results for item in r.items], seen, today)
    # TODO(phase 3): rule filter -> LLM ranking -> body fetch -> summaries -> daily summary
    # TODO(phase 4): render public/
    health = state.update_health(health, {r.source.id: r.parsed for r in results}, today)
    return RunResult(
        today=today,
        sources=results,
        dedupe=dedupe,
        seen=state.update_seen(seen, dedupe.keys, today),
        health=health,
        failing=state.failing_sources(health, today),
    )
