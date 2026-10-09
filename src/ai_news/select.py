"""Candidate selection: dedupe -> rule filter (~60) -> one LLM ranking call -> top 20."""

import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ai_news.llm import LLM, Call
from ai_news.models import Item
from ai_news.schemas import RANKING_SCHEMA, RankEntry, Ranking
from ai_news.sources import SOURCES
from ai_news.state import is_seen
from ai_news.validate import ValidationFailed

TRACKING_PARAM = re.compile(r"^(utm_\w+|ref|ref_src|fbclid|gclid|mc_cid|mc_eid|app_id)$")
TITLE_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "for", "in", "on", "with", "by", "at", "from",
    "is", "are", "our", "your", "new", "introducing", "announcing",
}
TITLE_TOKEN = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*")
TITLE_JACCARD = 0.6
SOURCE_PRIORITY = {source.id: rank for rank, source in enumerate(SOURCES)}
SOURCE_NAMES = {source.id: source.name for source in SOURCES}

PREFILTER_LIMIT = 60
PREFILTER_PER_SOURCE = 15  # keep one busy source (Product Hunt) from crowding out the rest
SOURCE_WEIGHT = {
    "openai": 3.0, "anthropic": 3.0, "google_ai": 3.0, "deepmind": 3.0,
    "hf_blog": 2.0, "hn": 2.0, "simonwillison": 2.0,
    "hf_papers": 1.5, "hf_models": 1.5, "producthunt": 1.0,
}  # fmt: skip
EXCERPT_CHARS = 200
MIN_SCORE = 3  # scores 1-2 never make the page
MAX_ARTICLES = 20
# Product Hunt lists many launches a day; without a cap they crowd out the news.
SELECT_PER_SOURCE = {"producthunt": 4}


def normalize_url(url: str) -> str:
    """Canonical form for comparing URLs: https, no www, no tracking params or fragment."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").removeprefix("www.")
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"
    query = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not TRACKING_PARAM.match(k.lower())
    )
    return urlunsplit(("https", host, parts.path.rstrip("/"), urlencode(query), ""))


def title_tokens(title: str) -> frozenset[str]:
    text = unicodedata.normalize("NFKC", title).lower()
    text = re.sub(r"[‐-―]", "-", text)
    return frozenset(t for t in TITLE_TOKEN.findall(text) if t not in TITLE_STOPWORDS)


def similar_titles(a: frozenset[str], b: frozenset[str]) -> bool:
    if not a or not b:
        return False
    small, large = sorted((a, b), key=len)
    if len(small) >= 3 and small <= large:
        return True
    return len(a & b) / len(a | b) >= TITLE_JACCARD


@dataclass
class DedupeResult:
    items: list[Item]
    keys: set[str] = field(default_factory=set)  # every normalized URL looked at, to mark as seen
    skipped_seen: int = 0
    merged: int = 0


def dedupe(items: list[Item], seen: dict[str, str], today: date) -> DedupeResult:
    """Drop items seen on earlier days and merge same-story items across sources.

    Items are visited in source priority order, so the official post wins and
    the others are recorded in `also_in`.
    """
    ordered = sorted(
        items,
        key=lambda i: (SOURCE_PRIORITY.get(i.source, len(SOURCE_PRIORITY)), -(i.points or 0)),
    )
    result = DedupeResult(items=[])
    by_url: dict[str, Item] = {}
    kept_tokens: list[tuple[frozenset[str], Item]] = []
    for item in ordered:
        key = normalize_url(item.url)
        if is_seen(seen, key, today):
            result.skipped_seen += 1
            continue
        result.keys.add(key)
        tokens = title_tokens(item.title)
        match = by_url.get(key) or next((kept for t, kept in kept_tokens if similar_titles(t, tokens)), None)
        if match is not None:
            if item.source != match.source:
                match.also_in.setdefault(item.source, item.points)
            if len(item.summary) > len(match.summary):
                # An HN link has no text of its own; another source's description gives the LLM more to go on.
                match.summary = item.summary
            result.merged += 1
            continue
        kept = item.model_copy(deep=True)
        by_url[key] = kept
        kept_tokens.append((tokens, kept))
        result.items.append(kept)
    return result


def item_id(item: Item) -> str:
    """Stable short id for an item, used for LLM fixture names and page anchors."""
    return hashlib.sha1(normalize_url(item.url).encode()).hexdigest()[:10]


# Rule filter


def prefilter_score(item: Item, now: datetime) -> float:
    score = SOURCE_WEIGHT.get(item.source, 1.0)
    score += len(item.also_in)  # picked up by several sources
    hn_points = item.points if item.source == "hn" else item.also_in.get("hn")
    if hn_points:
        score += min(math.log10(hn_points), 3.0)
    hours_old = (now - item.published).total_seconds() / 3600
    score += max(0.0, 1.0 - hours_old / 36)
    return score


def prefilter(items: list[Item], now: datetime) -> list[Item]:
    """Cut the candidates to about 60 before the ranking call, best first."""
    ordered = sorted(items, key=lambda i: prefilter_score(i, now), reverse=True)
    per_source: dict[str, int] = {}
    kept = []
    for item in ordered:
        per_source[item.source] = per_source.get(item.source, 0) + 1
        if per_source[item.source] <= PREFILTER_PER_SOURCE:
            kept.append(item)
    return kept[:PREFILTER_LIMIT]


# LLM ranking


RANK_SYSTEM = """\
あなたは、AIに詳しくない日本の社会人・個人事業主に向けて、毎朝AIニュースを選ぶ編集者です。
渡されたニュース候補それぞれについて、読者にとっての影響度（score）とカテゴリ（category）を決めてください。

score の基準:
5 = 多くの人の仕事や生活に広く関わる大ニュース（主要AI企業の大型モデル発表、誰もが使うサービスの大きな変化など）
4 = 知っておくべき重要な発表
3 = 知っておくと得（エンジニアでなくても明日から試せるツール、わかりやすい注目研究など）
2 = 専門家向けで、一般の読者への影響は小さい
1 = 読者には関係が薄い（AIと関係のない話題など）

次のものは、内容がよくても 2 以下にしてください:
- 開発者だけが使う道具（コマンドライン、API、プログラミング支援、開発環境やテストの仕組み、監査・認証対応など）
- 企業の導入事例や、ある会社が製品を使った宣伝記事
- 個人の意見記事やまとめ記事で、新しい発表を含まないもの

category は次の5つから1つ選びます:
注目トピック = 業界の動き・規制・安全性・企業の発表など
画像・動画 = 画像や動画、音声を作る・扱うAI
便利なツール = すぐに試せるアプリやサービス、機能追加
新モデル = 新しいAIモデルの公開・提供開始
研究・論文 = 論文や研究成果

すべての候補の id について、1件ずつ答えてください。複数のソースに載っている話題は、注目度が高い目安です。"""


def ranking_call(items: list[Item]) -> Call:
    lines = []
    for index, item in enumerate(items):
        source = SOURCE_NAMES.get(item.source, item.source)
        if item.source == "hn" and item.points:
            source += f" {item.points} points"
        signals = []
        for other, points in item.also_in.items():
            name = SOURCE_NAMES.get(other, other)
            signals.append(f"{name} {points} points" if other == "hn" and points else name)
        also = f" (also: {', '.join(signals)})" if signals else ""
        excerpt = " ".join(item.summary.split())[:EXCERPT_CHARS]
        lines.append(f"[{index}] {source} | {item.title}{also}")
        if excerpt:
            lines.append(f"    {excerpt}")
    user = f"ニュース候補（{len(items)}件）:\n\n" + "\n".join(lines)
    return Call(name="rank", system=RANK_SYSTEM, user=user, schema=RANKING_SCHEMA, max_tokens=4096)


@dataclass
class Ranked:
    item: Item
    rank: RankEntry


def rank(items: list[Item], llm: LLM) -> list[Ranked]:
    """Score every candidate with one call; return those worth publishing, best first."""
    if not items:
        return []

    def parse(data: dict) -> Ranking:
        ranking = Ranking.model_validate(data)
        if not any(0 <= entry.id < len(items) for entry in ranking.items):
            raise ValidationFailed("ranking matched none of the candidate ids")
        return ranking

    entries: dict[int, RankEntry] = {}
    for entry in llm.ask(ranking_call(items), parse).items:
        if 0 <= entry.id < len(items):
            entries.setdefault(entry.id, entry)
    picked: list[Ranked] = []
    per_source: dict[str, int] = {}
    for i, entry in sorted(entries.items(), key=lambda pair: (-pair[1].score, pair[0])):
        source = items[i].source
        if entry.score < MIN_SCORE or per_source.get(source, 0) >= SELECT_PER_SOURCE.get(source, MAX_ARTICLES):
            continue
        per_source[source] = per_source.get(source, 0) + 1
        picked.append(Ranked(items[i], entry))
    return picked[:MAX_ARTICLES]
