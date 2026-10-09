"""Command-line entry point for the daily pipeline."""

import argparse
import logging
import os
from datetime import UTC, datetime

from ai_news import fixtures, pipeline, state
from ai_news.fetch import http_fetch

log = logging.getLogger("ai_news")

PROVIDERS = ("gemini", "groq")


def utc_now() -> datetime:
    return datetime.now(UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-news",
        description="Collect, rank, summarize and render today's AI news.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="run the whole pipeline on recorded fixtures (no network, no LLM calls, no state saved)",
    )
    mode.add_argument(
        "--record-fixtures",
        action="store_true",
        help="fetch every source live and overwrite tests/fixtures/sources/",
    )
    parser.add_argument(
        "--provider",
        choices=PROVIDERS,
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
        "candidates: %d (skipped as seen: %d, merged duplicates: %d)",
        len(d.items),
        d.skipped_seen,
        d.merged,
    )
    for item in d.items:
        extra = f" +{','.join(item.also_in)}" if item.also_in else ""
        log.debug("  [%s%s] %s <%s>", item.source, extra, item.title, item.url)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.record_fixtures:
        fixtures.record(http_fetch)
        return 0

    if args.dry_run:
        now, fetch = fixtures.recorded_at(), fixtures.fixture_fetch
        seen, health = {}, {}
    else:
        now, fetch = utc_now(), http_fetch
        seen, health = state.load_json(state.SEEN_PATH), state.load_json(state.HEALTH_PATH)

    mode = "dry-run" if args.dry_run else "live"
    log.info("pipeline start (%s, provider=%s, now=%s)", mode, args.provider, now)
    result = pipeline.run(now, fetch, seen, health)
    report(result)

    if not args.dry_run:
        state.save_json(state.SEEN_PATH, result.seen)
        state.save_json(state.HEALTH_PATH, result.health)

    if result.failing:
        days = state.ZERO_DAYS_TO_FAIL
        log.error("no items for %d days in a row from: %s", days, ", ".join(result.failing))
        return 1
    return 0
