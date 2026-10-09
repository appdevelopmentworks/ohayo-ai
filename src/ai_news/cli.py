"""Command-line entry point for the daily pipeline."""

import argparse
import logging
import os

log = logging.getLogger("ai_news")

PROVIDERS = ("gemini", "groq")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-news",
        description="Collect, rank, summarize and render today's AI news.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="run the whole pipeline on recorded fixtures (no network, no LLM calls)",
    )
    parser.add_argument(
        "--provider",
        choices=PROVIDERS,
        default=os.environ.get("LLM_PROVIDER", "gemini"),
        help="primary LLM provider (default: $LLM_PROVIDER or gemini)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    mode = "dry-run" if args.dry_run else "live"
    log.info("pipeline start (mode=%s, provider=%s)", mode, args.provider)
    # TODO(phase 2-4): collect -> dedupe -> rank -> summarize -> render
    log.info("pipeline steps are not implemented yet; nothing to do")
    return 0
