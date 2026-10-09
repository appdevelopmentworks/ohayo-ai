"""Recorded source responses for tests and --dry-run."""

import logging
from datetime import UTC, datetime

from lxml import etree

from ai_news.paths import FIXTURES_DIR
from ai_news.sources import SOURCES, Fetch, Source, source_url

log = logging.getLogger(__name__)

SOURCE_FIXTURES = FIXTURES_DIR / "sources"
RECORDED_AT = SOURCE_FIXTURES / "recorded_at.txt"
FEED_KEEP = 40  # trim long feeds; only recent entries matter
ATOM_ENTRY = "{http://www.w3.org/2005/Atom}entry"


def fixture_path(source: Source):
    return SOURCE_FIXTURES / f"{source.id}.{source.ext}"


def recorded_at() -> datetime:
    return datetime.fromisoformat(RECORDED_AT.read_text(encoding="utf-8").strip())


def fixture_fetch(source: Source, url: str) -> bytes:
    return fixture_path(source).read_bytes()


def trim_feed(content: bytes, keep: int = FEED_KEEP) -> bytes:
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    root = etree.fromstring(content, parser)
    entries = root.findall("./channel/item") or root.findall(ATOM_ENTRY)
    if len(entries) <= keep:
        return content
    for entry in entries[keep:]:
        entry.getparent().remove(entry)
    return etree.tostring(root, xml_declaration=True, encoding="utf-8")


def record(fetch: Fetch, now: datetime | None = None) -> None:
    """Fetch every source live and overwrite the fixtures."""
    now = now or datetime.now(UTC).replace(microsecond=0)
    SOURCE_FIXTURES.mkdir(parents=True, exist_ok=True)
    for source in SOURCES:
        content = fetch(source, source_url(source, now))
        if source.ext == "xml":
            content = trim_feed(content)
        fixture_path(source).write_bytes(content)
        log.info("%s: recorded %d bytes", source.id, len(content))
    RECORDED_AT.write_text(now.isoformat() + "\n", encoding="utf-8", newline="\n")
