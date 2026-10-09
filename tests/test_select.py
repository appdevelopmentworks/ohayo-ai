from datetime import UTC, date, datetime

import pytest

from ai_news.models import Item
from ai_news.select import dedupe, normalize_url, similar_titles, title_tokens

TODAY = date(2026, 10, 9)


def _item(source, title, url, points=None) -> Item:
    return Item(
        source=source,
        title=title,
        url=url,
        published=datetime(2026, 10, 8, tzinfo=UTC),
        points=points,
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://www.Example.com/a/b/", "https://example.com/a/b"),
        ("https://example.com/a?utm_source=x&b=2&a=1#frag", "https://example.com/a?a=1&b=2"),
        ("https://news.ycombinator.com/item?id=42", "https://news.ycombinator.com/item?id=42"),
        ("https://example.com:8080/", "https://example.com:8080"),
        ("https://www.producthunt.com/r/p/1?app_id=339", "https://producthunt.com/r/p/1"),
    ],
)
def test_normalize_url(url, expected):
    assert normalize_url(url) == expected


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("Claude Haiku 5.5", "Introducing Claude Haiku 5.5", True),
        ("GPT‑6 and Intelligent UI for everyone", "GPT-6 and intelligent UI for everyone", True),
        ("Claude Sonnet 5.5", "Claude Haiku 5.5", False),
        ("Gemini 4 Argon", "Gemini 4 Flash", False),
        ("GPT-6", "GPT-6 jailbroken within an hour", False),
        ("", "Anything", False),
    ],
)
def test_similar_titles(a, b, expected):
    assert similar_titles(title_tokens(a), title_tokens(b)) is expected


def test_dedupe_prefers_official_source_and_records_others():
    items = [
        _item("hn", "Claude Haiku 5.5", "https://www.anthropic.com/claude-haiku-5-5?utm_source=hn", 1034),
        _item("producthunt", "Claude Haiku 5.5", "https://www.producthunt.com/products/claude-haiku-5-5"),
        _item("anthropic", "Introducing Claude Haiku 5.5", "https://www.anthropic.com/claude-haiku-5-5"),
        _item("openai", "Something else entirely", "https://openai.com/index/other"),
    ]
    result = dedupe(items, seen={}, today=TODAY)
    assert [(i.source, i.title) for i in result.items] == [
        ("openai", "Something else entirely"),
        ("anthropic", "Introducing Claude Haiku 5.5"),
    ]
    assert result.items[1].also_in == {"producthunt": None, "hn": 1034}
    assert result.merged == 2
    assert "https://producthunt.com/products/claude-haiku-5-5" in result.keys
    assert items[2].also_in == {}  # inputs are not mutated


def test_dedupe_skips_items_seen_on_earlier_days_only():
    items = [
        _item("openai", "Old news", "https://openai.com/index/old"),
        _item("openai", "Rerun today", "https://openai.com/index/today"),
    ]
    seen = {
        "https://openai.com/index/old": "2026-10-08",
        "https://openai.com/index/today": "2026-10-09",
    }
    result = dedupe(items, seen, TODAY)
    assert [i.title for i in result.items] == ["Rerun today"]
    assert result.skipped_seen == 1
