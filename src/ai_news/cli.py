"""Command-line entry point for the daily pipeline."""

import argparse
import logging
import os
from datetime import UTC, datetime

from ai_news import article, fixtures, llm, pipeline, render, state
from ai_news.fetch import http_fetch
from ai_news.paths import PUBLIC_DIR

log = logging.getLogger("ai_news")


def utc_now() -> datetime:
    return datetime.now(UTC)


def site_url() -> str | None:
    """Public origin for canonical and OGP URLs, e.g. https://ohayo-ai.<account>.workers.dev"""
    return os.environ.get("SITE_URL") or None


def render_from_data() -> None:
    editions = render.load_editions(state.DAILY_DIR)
    render.render_site(editions, state.load_json(state.GLOSSARY_PATH), PUBLIC_DIR, site_url())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-news",
        description="Collect, rank, summarize and render today's AI news.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="run on recorded sources and LLM answers (no network, no API calls, no state saved)",
    )
    mode.add_argument(
        "--record-fixtures",
        action="store_true",
        help="fetch every source live and overwrite tests/fixtures/sources/",
    )
    mode.add_argument(
        "--render-only",
        action="store_true",
        help="rebuild public/ from data/ without collecting or calling any LLM",
    )
    mode.add_argument(
        "--record-llm",
        action="store_true",
        help="run the LLM steps for real on the recorded sources and save answers to tests/fixtures/llm/",
    )
    parser.add_argument(
        "--provider",
        choices=tuple(llm.PROVIDERS),
        default=os.environ.get("LLM_PROVIDER", "gemini"),
        help="primary LLM provider (default: $LLM_PROVIDER or gemini)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return parser


def report(result: pipeline.RunResult) -> None:
    for r in result.sources:
        status = f"error ({r.error})" if r.error else f"{r.parsed} returned, {len(r.items)} in window"
        log.info("source %-13s %s", r.source.id, status)
    d = result.dedupe
    log.info(
        "candidates: %d (skipped as seen: %d, merged duplicates: %d), ranked: %d",
        len(d.items),
        d.skipped_seen,
        d.merged,
        result.ranked,
    )
    if result.edition is None:
        return
    e = result.edition
    log.info(
        "edition %s: %d articles, weather=%s, %d LLM requests via %s, %.1fs",
        e.date,
        len(e.articles),
        e.weather,
        e.stats.llm_calls,
        ",".join(e.stats.providers) or "-",
        e.stats.seconds,
    )
    for line in e.digest:
        log.info("  | %s", line)
    log.info("  ニュー助: %s", e.mascot_line)
    for a in e.articles:
        note = " (概要のみ)" if a.summary_only else ""
        log.debug("  [%d %s] %s <%s>%s", a.score, a.category, a.title_ja, a.url, note)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.record_fixtures:
        fixtures.record(http_fetch)
        return 0
    if args.render_only:
        try:
            render_from_data()
        except ValueError as exc:
            log.error("%s", exc)
            return 1
        return 0

    offline = args.dry_run or args.record_llm
    try:
        if args.dry_run:
            client = llm.LLM([llm.ReplayClient()])
        else:
            client = llm.from_env(args.provider, record=args.record_llm)
    except llm.LLMError as exc:
        log.error("%s", exc)
        return 1
    if offline:
        # Same inputs for recording and replay: recorded sources, feed text as the body.
        now, fetch, body_fetch = fixtures.recorded_at(), fixtures.fixture_fetch, article.feed_text_body
        seen, health = {}, {}
    else:
        now, fetch, body_fetch = utc_now(), http_fetch, article.fetch_body
        seen, health = state.load_json(state.SEEN_PATH), state.load_json(state.HEALTH_PATH)

    mode = "dry-run" if args.dry_run else "record-llm" if args.record_llm else "live"
    log.info("pipeline start (%s, provider=%s, now=%s)", mode, args.provider, now)
    result = pipeline.run(now, fetch, seen, health, client, body_fetch)
    report(result)

    edition = result.edition
    if not offline:
        state.save_json(state.SEEN_PATH, result.seen)
        state.save_json(state.HEALTH_PATH, result.health)
        if edition:
            state.save_json(state.DAILY_DIR / f"{edition.date}.json", edition.model_dump(mode="json"))
            glossary = state.update_glossary(state.load_json(state.GLOSSARY_PATH), edition)
            state.save_json(state.GLOSSARY_PATH, glossary)
            render_from_data()
    elif args.dry_run and edition:
        # Same site as a live run would build, without touching data/.
        editions = [e for e in render.load_editions(state.DAILY_DIR) if e.date != edition.date]
        glossary = state.update_glossary(state.load_json(state.GLOSSARY_PATH), edition)
        render.render_site([*editions, edition], glossary, PUBLIC_DIR, site_url())

    status = 0
    if result.error:
        log.error("no edition made: %s", result.error)
        status = 1
    if result.failing:
        days = state.ZERO_DAYS_TO_FAIL
        log.error("no items for %d days in a row from: %s", days, ", ".join(result.failing))
        status = 1
    return status
