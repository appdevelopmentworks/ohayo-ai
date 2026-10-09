"""Render the static site into public/ from the editions in data/daily/ and the glossary."""

import hashlib
import json
import logging
import shutil
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ai_news.mascot import MOODS, WEATHER_MOODS
from ai_news.ogp import render_ogp
from ai_news.paths import PUBLIC_DIR, TEMPLATES_DIR
from ai_news.schemas import Article, Edition
from ai_news.state import JST

log = logging.getLogger(__name__)

SITE_NAME = "おはようAI"
TAGLINE = "毎朝7時、AIのニュースをやさしく"
# TODO(owner): the AILEAP contact URL is not decided yet. Until it is set, the call to action
# shows "準備中" instead of a button. Never fill in a guessed URL.
AILEAP_CONTACT_URL: str | None = None

ASSETS = ("style.css", "app.js", "nyusuke.svg")
WEEKDAYS = "月火水木金土日"

WEATHER = {
    "thunder": {"name": "かみなり", "sub": "大ニュースの日", "mood": WEATHER_MOODS["thunder"],
                "greet": "おはよう！今日は大きなニュースの日。まずはこの3つを押さえよう"},
    "cloudy": {"name": "くもり", "sub": "ちょっと動きあり", "mood": WEATHER_MOODS["cloudy"],
               "greet": "おはよう！今日はちょっと動きあり。この3つをチェックしよう"},
    "sunny": {"name": "はれ", "sub": "おだやかな一日", "mood": WEATHER_MOODS["sunny"],
              "greet": "おはよう！今日はおだやかな日。この3つだけ読めば大丈夫"},
}  # fmt: skip

CATEGORY_KEYS = {
    "注目トピック": "topic",
    "画像・動画": "image",
    "便利なツール": "tool",
    "新モデル": "model",
    "研究・論文": "research",
}
RANK_LABELS = {5: "今日いちばん", 4: "要チェック", 3: "知っておくと得"}
TABS = (
    ("all", "すべて"),
    ("hot", "注目"),
    ("image", "画像・動画"),
    ("tool", "ツール"),
    ("model", "新モデル"),
    ("research", "研究"),
)

CONFETTI = [
    {"left": left, "color": color, "delay": delay}
    for left, color, delay in [
        (8, "#FFB547", 0), (18, "#7FD9C2", .15), (27, "#FF8FA8", .05), (36, "#8FB8FF", .25),
        (45, "#FFB547", .1), (55, "#7FD9C2", .3), (64, "#FF8FA8", .2), (73, "#8FB8FF", .05),
        (82, "#FFB547", .35), (91, "#7FD9C2", .15),
    ]
]  # fmt: skip

STEPS = [
    {"icon": "collect", "name": "あつめる", "text": "公式ブログや論文サイトなど10か所から、過去36時間の新しい情報を集めます"},
    {"icon": "filter", "name": "えらぶ", "text": "重なった話題をまとめ、AIが世の中への影響で順位をつけて、最大20本を選びます"},
    {"icon": "summary", "name": "まとめる", "text": "1本ずつ記事を読み、やさしい日本語の3行と用語メモにまとめます"},
    {"icon": "build", "name": "つくる", "text": "数字が元の記事にあるかなどを機械でチェックしてから、ページを作ります"},
    {"icon": "send", "name": "とどける", "text": "毎朝7時までに、このサイトを自動で作り直して公開します"},
]

# Source pages and their role, for /behind/ (same order as the collectors).
SOURCE_INFO = [
    ("OpenAI News", "https://openai.com/news/", "OpenAIの公式ニュース"),
    ("Anthropic News", "https://www.anthropic.com/news", "Anthropicの公式ニュース"),
    ("Google AI（The Keyword）", "https://blog.google/innovation-and-ai/technology/ai/", "GoogleのAI公式ブログ"),
    ("Google DeepMind", "https://deepmind.google/blog/", "Google DeepMindの公式ブログ"),
    ("Hugging Face Blog", "https://huggingface.co/blog", "AIモデル共有サイトの公式ブログ"),
    ("HF Daily Papers", "https://huggingface.co/papers", "その日に話題の論文"),
    ("Hugging Face トレンドモデル", "https://huggingface.co/models", "人気が上がっているAIモデル"),
    ("Product Hunt", "https://www.producthunt.com/", "新しく出たAIツール"),
    ("Hacker News", "https://news.ycombinator.com/", "技術者コミュニティで話題の記事"),
    ("Simon Willison's Weblog", "https://simonwillison.net/", "見落とし防止。リンク先は一次ソースにします"),
]

SITE_LABELS = {
    "openai.com": "OpenAI",
    "anthropic.com": "Anthropic",
    "blog.google": "Google",
    "deepmind.google": "Google DeepMind",
    "huggingface.co": "Hugging Face",
    "arxiv.org": "arXiv",
    "producthunt.com": "Product Hunt",
    "github.com": "GitHub",
}


def site_label(url: str) -> str:
    """Who published the page a card links to: the primary source, not the feed we found it in."""
    host = (urlsplit(url).hostname or "").removeprefix("www.")
    for domain, label in SITE_LABELS.items():
        if host == domain or host.endswith("." + domain):
            return label
    return host


def date_label(day: date) -> str:
    return f"{day.month}月{day.day}日（{WEEKDAYS[day.weekday()]}）"


def updated_label(moment: datetime) -> str:
    local = moment.astimezone(JST)
    prefix = "今朝 " if local.hour < 12 else ""
    return f"{prefix}{local.hour}:{local.minute:02d} 更新"


def duration_label(seconds: float) -> str:
    minutes, secs = divmod(round(seconds), 60)
    return f"{minutes}分{secs}秒" if minutes else f"{secs}秒"


def article_view(article: Article) -> dict:
    cat_key = CATEGORY_KEYS[article.category]
    tabs = ["all", cat_key]
    if article.score >= 4 or cat_key == "topic":
        tabs.insert(1, "hot")
    return {
        **article.model_dump(),
        "cat_key": cat_key,
        "rank_label": RANK_LABELS[article.score],
        "tabs": tabs,
        "site": site_label(article.url),
    }


def load_editions(directory: Path) -> list[Edition]:
    editions = [Edition.model_validate_json(p.read_text(encoding="utf-8")) for p in directory.glob("*.json")]
    return sorted(editions, key=lambda e: e.date)


class Site:
    def __init__(self, out: Path, site_url: str | None):
        self.out = out
        self.site_url = site_url.rstrip("/") if site_url else None
        self.env = Environment(
            loader=FileSystemLoader(TEMPLATES_DIR),
            autoescape=True,
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )
        assets = b"".join((TEMPLATES_DIR / "assets" / name).read_bytes() for name in ASSETS)
        self.env.globals.update(
            site_name=SITE_NAME,
            tagline=TAGLINE,
            moods=MOODS,
            asset_version=hashlib.sha1(assets).hexdigest()[:8],
        )
        self.written: list[Path] = []

    def url(self, path: str) -> str | None:
        return f"{self.site_url}{path}" if self.site_url else None

    def write(self, path: str, text: str) -> None:
        target = self.out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
        self.written.append(target)

    def page(self, template: str, path: str, og_image: str | None = None, **context) -> None:
        url_path = "/" + path.removesuffix("index.html")
        html = self.env.get_template(template).render(
            canonical=self.url(url_path), og_image=og_image and self.url(og_image), **context
        )
        self.write(path, html)

    def edition_page(self, edition: Edition, path: str, is_archive: bool) -> None:
        articles = [article_view(a) for a in edition.articles]
        tabs = [
            {"key": key, "label": label, "count": sum(key in a["tabs"] for a in articles)}
            for key, label in TABS
        ]
        self.page(
            "index.html",
            path,
            og_image=f"/ogp/{edition.date}.png",
            edition=edition,
            is_archive=is_archive,
            wx=WEATHER[edition.weather],
            digest=edition.digest,
            articles=articles,
            tabs=tabs,
            site_count=len({a["site"] for a in articles}),
            date_label=date_label(edition.date),
            updated_label=updated_label(edition.generated_at),
            confetti=CONFETTI,
        )


def render_site(
    editions: list[Edition],
    glossary: dict[str, dict],
    out: Path = PUBLIC_DIR,
    site_url: str | None = None,
) -> list[Path]:
    """Write every page. Returns the files written."""
    if not editions:
        raise ValueError("no edition to render")
    editions = sorted(editions, key=lambda e: e.date)
    latest = editions[-1]
    site = Site(out, site_url)

    for name in ASSETS:
        target = out / "assets" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(TEMPLATES_DIR / "assets" / name, target)
        site.written.append(target)

    site.edition_page(latest, "index.html", is_archive=False)
    for edition in editions:
        site.edition_page(edition, f"archive/{edition.date}/index.html", is_archive=True)
        image = out / "ogp" / f"{edition.date}.png"
        if edition is latest or not image.exists():
            render_ogp(edition, image)
            site.written.append(image)

    days = [
        {
            "date": e.date.isoformat(),
            "label": date_label(e.date),
            "weather": e.weather,
            "weather_name": WEATHER[e.weather]["name"],
            "count": len(e.articles),
            "digest": e.digest,
        }
        for e in reversed(editions)
    ]
    site.page("archive.html", "archive/index.html", days=days)

    terms = [
        {"word": word, **entry, "date_label": date_label(date.fromisoformat(entry["date"]))}
        for word, entry in sorted(glossary.items())
    ]
    site.page("glossary.html", "glossary/index.html", terms=terms)

    site.page(
        "behind.html",
        "behind/index.html",
        og_image=f"/ogp/{latest.date}.png",
        stats=latest.stats,
        date_label=date_label(latest.date),
        duration=duration_label(latest.stats.seconds),
        steps=STEPS,
        sources=[{"name": n, "home": h, "role": r} for n, h, r in SOURCE_INFO],
        contact_url=AILEAP_CONTACT_URL,
    )
    site.page("404.html", "404.html")
    site.write("news.json", json.dumps(latest.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n")
    log.info("rendered %d files into %s", len(site.written), out)
    return site.written
