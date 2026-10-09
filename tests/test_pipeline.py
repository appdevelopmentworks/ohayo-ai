from datetime import UTC, datetime, timedelta

import pytest

from ai_news import article, fixtures, llm, pipeline, select
from ai_news.models import Item
from ai_news.schemas import Article
from ai_news.summarize import weather_for

NOW = datetime(2026, 10, 9, 21, 17, tzinfo=UTC)


def _item(source, title, hours_old=1.0, points=None, also_in=None) -> Item:
    return Item(
        source=source,
        title=title,
        url=f"https://example.com/{source}/{title.replace(' ', '-')}",
        published=NOW - timedelta(hours=hours_old),
        points=points,
        also_in=also_in or {},
    )


def _replay_run(**kwargs) -> pipeline.RunResult:
    defaults = {
        "now": fixtures.recorded_at(),
        "fetch": fixtures.fixture_fetch,
        "seen": {},
        "health": {},
        "llm": llm.LLM([llm.ReplayClient()]),
        "body_fetch": article.feed_text_body,
    }
    return pipeline.run(**{**defaults, **kwargs})


# Rule filter


def test_prefilter_prefers_official_and_widely_covered_items():
    items = [
        _item("producthunt", "tool"),
        _item("openai", "launch"),
        _item("anthropic", "model", also_in={"hn": 1000, "simonwillison": None}),
        _item("hn", "thread", points=10),
    ]
    assert [i.title for i in select.prefilter(items, NOW)] == ["model", "launch", "thread", "tool"]


def test_prefilter_caps_each_source_and_the_total(monkeypatch):
    monkeypatch.setattr(select, "PREFILTER_LIMIT", 5)
    items = [_item("producthunt", f"tool {n}") for n in range(20)] + [_item("openai", f"post {n}") for n in range(3)]
    kept = select.prefilter(items, NOW)
    assert len(kept) == 5
    assert [i.source for i in kept[:3]] == ["openai"] * 3


def test_ranking_prompt_lists_every_candidate_with_signals():
    items = [_item("anthropic", "Claude", also_in={"hn": 1034}), _item("hn", "Whistle", points=549)]
    user = select.ranking_call(items).user
    assert "[0] Anthropic News | Claude (also: Hacker News 1034 points)" in user
    assert "[1] Hacker News 549 points | Whistle" in user


# Weather


def _article(score: int) -> Article:
    return Article(
        id=str(score), title_ja="t", what="w", new="", impact="", term=None, category="新モデル",
        score=score, url="https://example.com", source="openai", source_name="OpenAI News",
        title_en="t", published=NOW, summary_only=False,
    )  # fmt: skip


@pytest.mark.parametrize(
    ("scores", "weather"),
    [
        ([5, 4, 4, 3], "thunder"),
        ([5, 3, 3], "cloudy"),  # one big story alone is not a stormy day
        ([4, 4, 3], "cloudy"),
        ([4, 3, 3, 3], "sunny"),
        ([], "sunny"),
    ],
)
def test_weather(scores, weather):
    assert weather_for([_article(s) for s in scores]) == weather


# The whole pipeline on recorded sources and answers


def test_dry_run_edition():
    result = _replay_run()
    edition = result.edition
    assert result.error is None
    assert 0 < len(edition.articles) <= select.MAX_ARTICLES
    assert edition.stats.llm_calls == len(edition.articles) + 2  # rank + summaries + daily
    assert edition.stats.llm_calls <= 22
    scores = [a.score for a in edition.articles]
    assert scores == sorted(scores, reverse=True)
    assert min(scores) >= select.MIN_SCORE
    assert len(edition.digest) == 3
    assert len({a.id for a in edition.articles}) == len(edition.articles)
    assert set(result.seen.values()) == {result.today.isoformat()}


def test_ranking_failure_makes_no_edition_and_keeps_seen(tmp_path):
    result = _replay_run(llm=llm.LLM([llm.ReplayClient(tmp_path)]), seen={"https://old": "2026-10-08"})
    assert result.edition is None
    assert result.error.startswith("ranking failed")
    assert result.seen == {"https://old": "2026-10-08"}
    assert result.health  # source health is still recorded


def test_daily_failure_falls_back_to_titles(tmp_path):
    for path in llm.LLM_FIXTURES.glob("*.json"):
        if path.name != "daily.json":
            (tmp_path / path.name).write_bytes(path.read_bytes())
    edition = _replay_run(llm=llm.LLM([llm.ReplayClient(tmp_path)])).edition
    assert edition.digest == [a.title_ja for a in edition.articles[:3]]
    assert edition.mascot_line == pipeline.FALLBACK_LINES[edition.weather]


def test_failed_summary_drops_only_that_article(tmp_path):
    fixtures_dir = llm.LLM_FIXTURES
    for path in fixtures_dir.glob("*.json"):
        (tmp_path / path.name).write_bytes(path.read_bytes())
    full = _replay_run().edition
    dropped = full.articles[-1]
    (tmp_path / f"summary-{dropped.id}.json").unlink()
    edition = _replay_run(llm=llm.LLM([llm.ReplayClient(tmp_path)])).edition
    assert [a.id for a in edition.articles] == [a.id for a in full.articles[:-1]]


def test_rank_caps_product_hunt():
    items = [_item("producthunt", f"tool {n}") for n in range(6)] + [_item("openai", "launch")]

    class Answer:
        name = "fake"

        def request(self, call):
            return {"items": [{"id": i, "score": 3, "category": "便利なツール"} for i in range(len(items))]}

    picked = select.rank(items, llm.LLM([Answer()]))
    sources = [r.item.source for r in picked]
    assert sources.count("producthunt") == select.SELECT_PER_SOURCE["producthunt"]
    assert "openai" in sources


def test_ranking_prompt_rules_out_developer_tools_and_case_studies():
    system = select.ranking_call([_item("openai", "x")]).system
    assert "開発者だけが使う道具" in system and "企業の導入事例" in system
    assert "category は次の5つ" in system


def test_summary_prompt_without_any_text_says_to_use_the_title():
    from ai_news.summarize import summary_call

    ranked = select.Ranked(_item("hn", "GPT-6 for everyone"), None)
    user = summary_call(ranked, body=None).user
    assert user.endswith("本文: なし（タイトルから分かることだけで書く）")
    with_feed = summary_call(select.Ranked(_item("openai", "x").model_copy(update={"summary": "feed"}), None), None)
    assert "本文（概要のみ）:\nfeed" in with_feed.user
