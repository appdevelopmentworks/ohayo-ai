import json
from datetime import UTC, date, datetime, timedelta

import pytest
from PIL import Image

from ai_news import ogp, render, state
from ai_news.schemas import Term


@pytest.fixture
def site(tmp_path, edition):
    """Two days of editions rendered without a public URL."""
    yesterday = edition.model_copy(update={"date": edition.date - timedelta(days=1), "weather": "sunny"})
    glossary = state.update_glossary({}, edition)
    render.render_site([edition, yesterday], glossary, tmp_path)
    return tmp_path


def _read(path) -> str:
    return path.read_text(encoding="utf-8")


def test_every_page_is_written(site, edition):
    for path in [
        "index.html", "404.html", "news.json", "archive/index.html", "glossary/index.html",
        "behind/index.html", "assets/style.css", "assets/app.js", "assets/nyusuke.svg",
        f"archive/{edition.date}/index.html", f"archive/{edition.date - timedelta(days=1)}/index.html",
        f"ogp/{edition.date}.png",
    ]:  # fmt: skip
        assert (site / path).is_file(), path


def test_index_shows_the_latest_edition(site, edition):
    html = _read(site / "index.html")
    assert html.count('<article class="card') == len(edition.articles)
    assert f'data-edition-date="{edition.date}"' in html
    assert "かみなり" in html
    for line in edition.digest:
        assert line in html
    assert html.count('class="card card--top"') == sum(a.score == 5 for a in edition.articles)


def test_page_works_without_js(site):
    html = _read(site / "index.html")
    assert '<nav class="tabs" aria-label="カテゴリで絞り込む" hidden>' in html  # tabs need JS
    assert '<details class="term"' in html  # glossary memo opens in place without JS
    assert 'class="term-note"' in html


def test_archive_lists_days_newest_first(site, edition):
    html = _read(site / "archive/index.html")
    today, yesterday = str(edition.date), str(edition.date - timedelta(days=1))
    assert html.index(f"/archive/{today}/") < html.index(f"/archive/{yesterday}/")
    day = _read(site / f"archive/{yesterday}/index.html")
    assert "のニュース</h1>" in day
    assert "data-edition-date" not in day  # no reading streak on old days


def test_glossary_and_behind(site, edition):
    glossary = _read(site / "glossary/index.html")
    words = {a.term.word for a in edition.articles if a.term}
    assert glossary.count('class="glossary-item"') == len(words)
    behind = _read(site / "behind/index.html")
    assert f"<strong>{edition.stats.collected}</strong> 件から <strong>{edition.stats.selected}</strong> 本" in behind
    assert "お問い合わせ窓口は準備中です" in behind  # no AILEAP URL yet


def test_news_json_matches_edition(site, edition):
    data = json.loads(_read(site / "news.json"))
    assert data["date"] == str(edition.date)
    assert len(data["articles"]) == len(edition.articles)


def test_og_tags_need_a_site_url(site, tmp_path, edition):
    assert "og:image" not in _read(site / "index.html")
    out = tmp_path / "with-url"
    render.render_site([edition], {}, out, site_url="https://ohayo-ai.example.workers.dev/")
    html = _read(out / "index.html")
    assert f'<meta property="og:image" content="https://ohayo-ai.example.workers.dev/ogp/{edition.date}.png">' in html
    assert '<link rel="canonical" href="https://ohayo-ai.example.workers.dev/">' in html


def test_text_is_escaped(tmp_path, edition):
    article = edition.articles[0].model_copy(
        update={"title_ja": "<script>alert(1)</script>", "term": Term(word='"x"', note="a & b")}
    )
    render.render_site([edition.model_copy(update={"articles": [article]})], {}, tmp_path)
    html = _read(tmp_path / "index.html")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert 'data-word="&#34;x&#34;"' in html


def test_render_needs_an_edition(tmp_path):
    with pytest.raises(ValueError):
        render.render_site([], {}, tmp_path)


def test_old_ogp_images_are_kept(tmp_path, edition):
    old = edition.model_copy(update={"date": edition.date - timedelta(days=1)})
    image = tmp_path / "ogp" / f"{old.date}.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"keep")
    render.render_site([old, edition], {}, tmp_path)
    assert image.read_bytes() == b"keep"


# Labels


@pytest.mark.parametrize(
    ("url", "label"),
    [
        ("https://www.anthropic.com/news/x", "Anthropic"),
        ("https://arxiv.org/abs/2610.1", "arXiv"),
        ("https://www.producthunt.com/products/x", "Product Hunt"),
        ("https://cactuscompute.com/blog/whistle", "cactuscompute.com"),
    ],
)
def test_site_label(url, label):
    assert render.site_label(url) == label


def test_date_and_time_labels():
    assert render.date_label(date(2026, 10, 9)) == "10月9日（金）"
    assert render.updated_label(datetime(2026, 10, 8, 21, 24, tzinfo=UTC)) == "今朝 6:24 更新"
    assert render.updated_label(datetime(2026, 10, 9, 5, 0, tzinfo=UTC)) == "14:00 更新"
    assert render.duration_label(552) == "9分12秒"
    assert render.duration_label(42.4) == "42秒"


def test_article_tabs(edition):
    by_score = {a.score: render.article_view(a) for a in edition.articles}
    assert "hot" in by_score[5]["tabs"]
    topic = next(render.article_view(a) for a in edition.articles if a.category == "注目トピック")
    assert topic["tabs"][:2] == ["all", "hot"]


def test_update_glossary_keeps_the_first_note(edition):
    first = state.update_glossary({}, edition)
    changed = edition.articles[0].model_copy(update={"term": Term(word=edition.articles[0].term.word, note="別の説明")})
    again = state.update_glossary(first, edition.model_copy(update={"articles": [changed]}))
    assert again == first


# OGP image


def test_ogp_image(tmp_path, edition):
    path = tmp_path / "ogp.png"
    ogp.render_ogp(edition, path)
    with Image.open(path) as img:
        assert img.size == (ogp.WIDTH, ogp.HEIGHT)
    assert path.stat().st_size < 150_000


def test_wrap_keeps_latin_words_whole():
    font = ogp._font(46)
    lines = ogp.wrap("Anthropicが小型AI「Claude Haiku 5.5」を発表", font, 650, 3)
    assert "".join(lines).replace(" ", "") == "Anthropicが小型AI「ClaudeHaiku5.5」を発表"
    assert all("Haik" not in line or "Haiku" in line for line in lines)


def test_wrap_truncates_with_ellipsis():
    lines = ogp.wrap("あ" * 200, ogp._font(46), 300, 2)
    assert len(lines) == 2 and lines[-1].endswith("…")


def test_wrap_keeps_punctuation_off_line_starts():
    font = ogp._font(46)
    for line in ogp.wrap("あいうえおかきくけこ、さしすせそ。たちつてと" * 3, font, 470, 6):
        assert line[0] not in ogp.NO_LINE_START


def test_path_points():
    points, closed = ogp._path_points("M70 84 Q80 97 90 84 Z", steps=4)
    assert closed and points[0] == (70, 84) and points[-1] == (90, 84)
    assert ogp._path_points("M74 89 L87 86") == ([(74, 89), (87, 86)], False)
