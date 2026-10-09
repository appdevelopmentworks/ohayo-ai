"""Per-article summaries (one call each) and the daily summary (one call)."""

import logging

from ai_news.llm import LLM, Call, LLMError
from ai_news.schemas import (
    DAILY_SCHEMA,
    DIGEST_LINE_MAX,
    LINE_MAX,
    MASCOT_LINE_MAX,
    SUMMARY_SCHEMA,
    TERM_NOTE_MAX,
    TERM_WORD_MAX,
    TITLE_MAX,
    Article,
    Daily,
    Summary,
    Weather,
)
from ai_news.select import SOURCE_NAMES, Ranked, item_id
from ai_news.validate import check_daily, check_summary

log = logging.getLogger(__name__)

SUMMARY_SYSTEM = f"""\
あなたは、AIに詳しくない日本の社会人・個人事業主に向けて、海外のAIニュースをやさしい日本語で紹介する編集者です。
渡された記事を読み、次の項目を日本語で書いてください。

- title_ja: 何が起きたかがひと目でわかる見出し（{TITLE_MAX}字以内）。例「Googleが動画も読める軽量AIを無料公開」
- what: 何があったか（1文、{LINE_MAX}字以内）
- new: 何が新しいのか（1文、{LINE_MAX}字以内）
- impact: 読者の仕事や生活がどう変わるか（1文、{LINE_MAX}字以内）
- term: 読者がつまずきそうな用語を1つ選び、word（{TERM_WORD_MAX}字以内）と note（やさしい説明、{TERM_NOTE_MAX}字以内）。不要なら null
- category: 注目トピック / 画像・動画 / 便利なツール / 新モデル / 研究・論文 のどれか
- score: 読者にとっての影響度 1〜5（5 = 多くの人に関わる大ニュース、3 = 知っておくと得）

守ること:
- 記事に書かれていることだけを書く。記事にない数字・日付・固有名詞・推測を足さない
- 全文の翻訳はしない。自分の言葉で短くまとめる
- 文末は「〜した」「〜できる」などの常体。専門用語はできるだけ言い換える
- 日本語の漢字だけを使い、中国語の簡体字を使わない
- 会社名・製品名は記事の表記（英語）のままでよい"""

DAILY_SYSTEM = f"""\
あなたは、AIニュースサイト「おはようAI」のマスコット「ニュー助」です。ミント色の丸いロボットで、毎朝やさしくニュースを案内します。
今日選ばれた記事の一覧をもとに、次の2つを日本語で書いてください。

- digest: 今日のニュースを3行でまとめる（ちょうど3つ、各{DIGEST_LINE_MAX}字以内）。大事な順に、似た話題はまとめる
- mascot_line: ニュー助のひとこと（{MASCOT_LINE_MAX}字以内）。今日のAI天気に合った、明るく親しみやすい一言

守ること:
- 一覧に書かれていることだけを使う。数字は一覧にあるものだけ
- 日本語の漢字だけを使い、中国語の簡体字を使わない"""

WEATHER_NAMES = {"thunder": "かみなり（大ニュースの日）", "cloudy": "くもり（ちょっと動きあり）", "sunny": "はれ（おだやかな一日）"}
THUNDER_POINTS = 4  # 5 -> 2 points, 4 -> 1 point, 3 -> 0 points
CLOUDY_POINTS = 2


def summary_call(ranked: Ranked, body: str | None) -> Call:
    item = ranked.item
    text = body or item.summary
    user = "\n".join(
        [
            f"出典: {SOURCE_NAMES.get(item.source, item.source)}",
            f"タイトル: {item.title}",
            f"URL: {item.url}",
            f"本文{'（概要のみ）' if body is None else ''}:",
            text,
        ]
    )
    return Call(name=f"summary-{item_id(item)}", system=SUMMARY_SYSTEM, user=user, schema=SUMMARY_SCHEMA)


def summarize(ranked: Ranked, body: str | None, llm: LLM) -> Article | None:
    """Summarize one article; None if no provider produced a valid summary."""
    item = ranked.item
    source_text = "\n".join([item.title, item.summary, body or ""])
    call = summary_call(ranked, body)
    try:
        summary = llm.ask(call, lambda data: check_summary(Summary.model_validate(data), source_text))
    except LLMError as exc:
        log.error("dropping %s: %s", item.url, exc)
        return None
    return Article(
        id=item_id(item),
        title_ja=summary.title_ja,
        what=summary.what,
        new=summary.new,
        impact=summary.impact,
        term=summary.term,
        category=summary.category,
        score=summary.score,
        url=item.url,
        source=item.source,
        source_name=SOURCE_NAMES.get(item.source, item.source),
        title_en=item.title,
        published=item.published,
        summary_only=body is None,
        also_in=list(item.also_in),
    )


def weather_for(articles: list[Article]) -> Weather:
    """AI weather from the day's impact scores: a 5 counts 2 points, a 4 counts 1."""
    points = sum(max(a.score - 3, 0) for a in articles)
    has_top = any(a.score == 5 for a in articles)
    if has_top and points >= THUNDER_POINTS:
        return "thunder"
    if points >= CLOUDY_POINTS:
        return "cloudy"
    return "sunny"


def article_digest_text(articles: list[Article]) -> str:
    lines = []
    for a in articles:
        lines.append(f"- [{a.category} / 影響度{a.score}] {a.title_ja}: {a.what} {a.new}")
    return "\n".join(lines)


def daily_call(articles: list[Article], weather: Weather) -> Call:
    user = f"今日のAI天気: {WEATHER_NAMES[weather]}\n\n今日の記事（{len(articles)}本、大事な順）:\n"
    return Call(
        name="daily",
        system=DAILY_SYSTEM,
        user=user + article_digest_text(articles),
        schema=DAILY_SCHEMA,
        max_tokens=1024,
    )


def daily_summary(articles: list[Article], weather: Weather, llm: LLM) -> Daily:
    source_text = article_digest_text(articles)

    def parse(data: dict) -> Daily:
        return check_daily(Daily.model_validate(data), source_text)

    return llm.ask(daily_call(articles, weather), parse)
