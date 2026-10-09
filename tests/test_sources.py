import json
from datetime import UTC, datetime, timedelta

import pytest

from ai_news import fixtures
from ai_news.models import Item
from ai_news.sources import SOURCES, Source, anthropic, collect_one, hn, simonwillison, source_url

NOW = datetime(2026, 10, 9, 21, 17, tzinfo=UTC)


# Recorded fixtures: every parser must read the real response shape.


@pytest.mark.parametrize("source", SOURCES, ids=lambda s: s.id)
def test_fixture_parses(source):
    items = source.parse(fixtures.fixture_path(source).read_bytes(), source.id)
    assert items, f"{source.id} parsed nothing from its fixture"
    for item in items:
        assert item.source == source.id
        assert item.title.strip()
        assert item.url.startswith("https://")
        assert item.published.tzinfo is not None


def test_fixtures_collect_without_errors():
    now = fixtures.recorded_at()
    for source in SOURCES:
        result = collect_one(source, now, fixtures.fixture_fetch)
        assert result.error is None
        assert result.parsed > 0
        if source.top_n:
            assert len(result.items) <= source.top_n


def test_simon_items_never_link_to_the_blog():
    source = next(s for s in SOURCES if s.id == "simonwillison")
    for item in source.parse(fixtures.fixture_path(source).read_bytes(), source.id):
        assert "simonwillison.net" not in item.url
        assert item.discussion_url.startswith("https://simonwillison.net/")


# Collection rules


def _source(items, **kwargs) -> Source:
    return Source("test", "Test", "https://example.com", lambda content, sid: items, **kwargs)


def _item(hours_old: float, points: int | None = None) -> Item:
    return Item(
        source="test",
        title=f"item {hours_old}",
        url=f"https://example.com/{hours_old}",
        published=NOW - timedelta(hours=hours_old),
        points=points,
    )


def test_window_and_top_n():
    items = [_item(1, 10), _item(2, 30), _item(3, 20), _item(40, 99)]
    result = collect_one(_source(items, top_n=2), NOW, lambda s, u: b"")
    assert result.parsed == 4
    assert [i.points for i in result.items] == [30, 20]


def test_no_max_age_keeps_old_items():
    result = collect_one(_source([_item(100)], max_age=None), NOW, lambda s, u: b"")
    assert len(result.items) == 1


def test_fetch_error_is_reported_not_raised():
    def broken(source, url):
        raise OSError("boom")

    result = collect_one(_source([]), NOW, broken)
    assert result.error == "OSError: boom"
    assert result.parsed == 0 and result.items == []


def test_source_url_placeholders():
    papers = next(s for s in SOURCES if s.id == "hf_papers")
    hn_source = next(s for s in SOURCES if s.id == "hn")
    assert source_url(papers, NOW).endswith("date=2026-10-09")
    early = datetime(2026, 10, 9, 2, 0, tzinfo=UTC)
    assert source_url(papers, early).endswith("date=2026-10-08")
    since = int((NOW - timedelta(hours=36)).timestamp())
    assert f"created_at_i>{since}" in source_url(hn_source, NOW)


# Anthropic listing page


ANTHROPIC_PAGE = b"""<html><body>
<a href="/claude-haiku-5-5"><h2>Introducing Claude Haiku 5.5</h2><span>Announcements</span>
  <time>Oct 7, 2026</time><p>Our fastest small model.</p></a>
<a href="/news/cyber"><time>Oct 6, 2026</time><span>Announcements</span>
  <span class="List__title">Expanding the Cyber Program</span></a>
<a href="/news/cyber"><span>Announcements</span><time>Oct 6, 2026</time><h4>Expanding the Cyber Program</h4></a>
<a href="https://example.com/elsewhere"><time>Oct 6, 2026</time><h4>Off-site</h4></a>
<a href="/careers">Careers</a>
</body></html>"""


def test_anthropic_parse():
    items = anthropic.parse(ANTHROPIC_PAGE, "anthropic")
    assert [(i.title, i.url) for i in items] == [
        ("Introducing Claude Haiku 5.5", "https://www.anthropic.com/claude-haiku-5-5"),
        ("Expanding the Cyber Program", "https://www.anthropic.com/news/cyber"),
    ]
    assert items[0].summary == "Our fastest small model."
    assert items[0].published == datetime(2026, 10, 7, 23, 59, 59, tzinfo=UTC)


def test_anthropic_date_formats():
    assert anthropic.parse_date("September 1, 2026").date().isoformat() == "2026-09-01"
    assert anthropic.parse_date("2026-10-07T10:00:00Z") == datetime(2026, 10, 7, 10, tzinfo=UTC)
    assert anthropic.parse_date("yesterday") is None


# Hacker News


def test_hn_keeps_ai_stories_only():
    payload = {
        "hits": [
            {"objectID": "1", "title": "Claude Haiku 5.5", "url": "https://www.anthropic.com/x",
             "points": 1034, "created_at_i": 1791396092},
            {"objectID": "2", "title": "Margaret Hamilton has died", "url": "https://news.mit.edu/x",
             "points": 2080, "created_at_i": 1791396000},
            {"objectID": "3", "title": "Ask HN: Which LLM do you use?", "url": None,
             "points": 50, "created_at_i": 1791396000},
        ]
    }  # fmt: skip
    items = hn.parse(json.dumps(payload).encode(), "hn")
    assert [i.title for i in items] == ["Claude Haiku 5.5", "Ask HN: Which LLM do you use?"]
    assert items[0].points == 1034
    assert items[1].url == items[1].discussion_url == "https://news.ycombinator.com/item?id=3"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("GPT‑6 and Intelligent UI for everyone", True),
        ("I gave Opus 5.5 one prompt and six hours", True),
        ("Whistle: Speech to Text in 16.9 MB", True),
        ("Why isn't the industry freaking out about DeepSeek 4.1 Flash?", True),
        ("Beauty in DVD Menus", False),
        ("Said the haiku poet", False),
        ("Maintaining a fair game", False),
    ],
)
def test_hn_ai_filter(title, expected):
    assert hn.is_ai_related(title) is expected


# Simon Willison post types


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ('<p><strong><a href="https://mistral.ai/news/large-4/">Mistral Large 4</a></strong></p><p>Notes</p>',
         "https://mistral.ai/news/large-4/"),
        ('<p>As <a href="https://simonwillison.net/2026/x/">promised</a>, here is '
         '<a href="https://www.anthropic.com/claude-haiku-5-5">Haiku</a>.</p>',
         "https://www.anthropic.com/claude-haiku-5-5"),
        ('<p><strong>Release:</strong> <a href="https://github.com/simonw/ttok/releases/tag/0.4">ttok</a></p>', None),
        ('<p><strong>TIL:</strong> <a href="https://til.simonwillison.net/x">x</a></p>', None),
        ('<blockquote cite="https://htmx.org/"><p>Quote</p></blockquote>', None),
        ('<p><a href="https://news.ycombinator.com/item?id=1#2">My comment</a> on '
         '<a href="https://news.ycombinator.com/item?id=1">Story</a></p>', None),
        ("<p>No links at all.</p>", None),
        ("", None),
    ],
)  # fmt: skip
def test_simon_primary_link(body, expected):
    assert simonwillison.primary_link(body) == expected
