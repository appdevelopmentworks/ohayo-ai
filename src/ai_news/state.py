"""State committed under data/: seen URLs and per-source health.

Dates are run dates in JST (the site is a morning edition for Japan).
"""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ai_news.paths import DATA_DIR

JST = timezone(timedelta(hours=9), "JST")
SEEN_PATH = DATA_DIR / "seen.json"
HEALTH_PATH = DATA_DIR / "source_health.json"
DAILY_DIR = DATA_DIR / "daily"  # one edition per run date, the source of the archive
GLOSSARY_PATH = DATA_DIR / "glossary.json"
SEEN_DAYS = 7
HEALTH_DAYS = 7
ZERO_DAYS_TO_FAIL = 2


def run_date(now: datetime) -> date:
    return now.astimezone(JST).date()


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


# seen.json: {normalized_url: first_seen_run_date}


def is_seen(seen: dict[str, str], key: str, today: date) -> bool:
    """Seen on an earlier day. Same-day hits are not "seen", so a manual re-run rebuilds the same page."""
    first = seen.get(key)
    return first is not None and first < today.isoformat()


def update_seen(seen: dict[str, str], keys: set[str], today: date) -> dict[str, str]:
    cutoff = (today - timedelta(days=SEEN_DAYS)).isoformat()
    kept = {key: day for key, day in seen.items() if day > cutoff}
    for key in keys:
        kept.setdefault(key, today.isoformat())
    return kept


# source_health.json: {source_id: {run_date: items_returned}}


def update_health(health: dict[str, dict[str, int]], counts: dict[str, int], today: date) -> dict:
    cutoff = (today - timedelta(days=HEALTH_DAYS)).isoformat()
    updated = {}
    for source_id in sorted(set(health) | set(counts)):
        days = {day: n for day, n in health.get(source_id, {}).items() if day > cutoff}
        if source_id in counts:
            days[today.isoformat()] = counts[source_id]
        if days:
            updated[source_id] = days
    return updated


def failing_sources(health: dict[str, dict[str, int]], today: date) -> list[str]:
    """Sources that returned nothing on each of the last ZERO_DAYS_TO_FAIL run dates."""
    days = [(today - timedelta(days=n)).isoformat() for n in range(ZERO_DAYS_TO_FAIL)]
    return sorted(sid for sid, counts in health.items() if all(counts.get(d) == 0 for d in days))


# glossary.json: {word: {note, date, article_id, title}}; the first explanation of a word is kept.


def update_glossary(glossary: dict[str, dict], edition) -> dict[str, dict]:
    updated = dict(glossary)
    for article in edition.articles:
        if article.term and article.term.word not in updated:
            updated[article.term.word] = {
                "note": article.term.note,
                "date": edition.date.isoformat(),
                "article_id": article.id,
                "title": article.title_ja,
            }
    return updated
