"""Checks on LLM output beyond the schema.

- Simplified Chinese characters (common with Qwen models) reject the answer.
- Numbers that do not appear in the source text are removed: a summary line
  carrying one is dropped, and a title carrying one rejects the answer.
"""

import re
import unicodedata
from decimal import Decimal, InvalidOperation

from ai_news.schemas import Daily, Summary


class ValidationFailed(ValueError):
    """The answer is unusable; the caller should retry or fall back."""


# Simplified Chinese: CJK ideographs that Japanese text never needs are those outside
# CP932 (JIS X 0208 plus vendor extensions), minus the few Joyo kanji added in 2010.
JOYO_OUTSIDE_CP932 = set("剝塡頰𠮟")
SIMPLIFIED_IN_CP932 = set("个")


def _is_ideograph(ch: str) -> bool:
    return "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿" or "\U00020000" <= ch <= "\U0002ffff"


def simplified_chars(text: str) -> list[str]:
    found = []
    for ch in text:
        if ch in SIMPLIFIED_IN_CP932:
            found.append(ch)
        elif _is_ideograph(ch) and ch not in JOYO_OUTSIDE_CP932:
            try:
                ch.encode("cp932")
            except UnicodeEncodeError:
                found.append(ch)
    return found


# Numbers


NUMBER = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")
EN_SCALE = re.compile(
    r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(thousand|million|billion|trillion|[kmb]\b)", re.IGNORECASE
)
EN_SCALES = {"thousand": 3, "k": 3, "million": 6, "m": 6, "billion": 9, "b": 9, "trillion": 12}
JA_SCALE = re.compile(r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(千|万|億|兆)")
JA_SCALES = {"千": 3, "万": 4, "億": 8, "兆": 12}
EN_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "twice": 2, "double": 2, "doubles": 2,
    "triple": 3, "triples": 3, "half": 0.5, "dozen": 12, "hundred": 100,
    "thousand": 10**3, "million": 10**6, "billion": 10**9, "trillion": 10**12,
}  # fmt: skip
# Calendar numbers (10月7日) are dates, not claims; English sources write them as words.
DATE_SUFFIX = re.compile(r"\s*(月|日)")


def _value(token: str) -> Decimal | None:
    try:
        return Decimal(token.replace(",", ""))
    except InvalidOperation:
        return None


def source_numbers(text: str) -> set[Decimal]:
    text = unicodedata.normalize("NFKC", text)
    values = {v for v in map(_value, NUMBER.findall(text)) if v is not None}
    for number, unit in EN_SCALE.findall(text):
        if (v := _value(number)) is not None:
            values.add(v.scaleb(EN_SCALES[unit.lower()]))
    for word in re.findall(r"[a-z]+", text.lower()):
        if word in EN_WORDS:
            values.add(Decimal(str(EN_WORDS[word])))
    return values


def unverified_numbers(text: str, known: set[Decimal]) -> list[str]:
    """Numbers in `text` whose value is not among `known`."""
    text = unicodedata.normalize("NFKC", text)
    bad = []
    for match in NUMBER.finditer(text):
        if DATE_SUFFIX.match(text, match.end()):
            continue
        value = _value(match.group())
        scaled = JA_SCALE.match(text, match.start())  # 100万 may come from "1 million"
        if scaled and value.scaleb(JA_SCALES[scaled.group(2)]) in known:
            continue
        if value not in known:
            bad.append(match.group())
    return bad


# Answer checks


def _reject_simplified(*texts: str) -> None:
    found = [ch for text in texts for ch in simplified_chars(text)]
    if found:
        raise ValidationFailed(f"simplified Chinese characters: {''.join(dict.fromkeys(found))}")


# Replies about the input instead of the news, e.g. when an article body could not be fetched.
META_COMMENT = re.compile(
    r"本文|記事の内容|情報がありません|情報がない|入力されて|提供されて|記載がない|記載されていない|"
    r"内容がありません|内容が不明|詳細は不明|わかりません|分かりません"
)


def _reject_meta_comments(*texts: str) -> None:
    for text in texts:
        if match := META_COMMENT.search(text):
            raise ValidationFailed(f"comment about the input instead of news: {match.group()!r} in {text!r}")


def check_summary(summary: Summary, source_text: str) -> Summary:
    """Return a cleaned summary, or raise ValidationFailed."""
    term_texts = [summary.term.word, summary.term.note] if summary.term else []
    _reject_simplified(summary.title_ja, summary.what, summary.new, summary.impact, *term_texts)
    _reject_meta_comments(summary.title_ja, summary.what, summary.new, summary.impact)
    known = source_numbers(source_text)
    if bad := unverified_numbers(summary.title_ja, known):
        raise ValidationFailed(f"title has numbers not in the source: {bad}")
    lines = {
        field: "" if unverified_numbers(getattr(summary, field), known) else getattr(summary, field)
        for field in ("what", "new", "impact")
    }
    if not any(lines.values()):
        raise ValidationFailed("no summary line left after removing unsupported numbers")
    term = summary.term
    if term and unverified_numbers(term.note, known):
        term = None
    return summary.model_copy(update={**lines, "term": term})


def check_daily(daily: Daily, source_text: str) -> Daily:
    _reject_simplified(*daily.digest, daily.mascot_line)
    known = source_numbers(source_text)
    for line in [*daily.digest, daily.mascot_line]:
        if bad := unverified_numbers(line, known):
            raise ValidationFailed(f"daily summary has numbers not in the articles: {bad}")
    return daily
