"""LLM output schemas and the daily edition written to data/daily/.

LLM outputs are validated twice: Pydantic for shape and length limits here,
then validate.py for simplified Chinese and unsupported numbers.
"""

from datetime import date
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, Field

CATEGORIES = ("注目トピック", "画像・動画", "便利なツール", "新モデル", "研究・論文")
Category = Literal["注目トピック", "画像・動画", "便利なツール", "新モデル", "研究・論文"]
Weather = Literal["thunder", "cloudy", "sunny"]

TITLE_MAX = 40
LINE_MAX = 60
TERM_WORD_MAX = 20
TERM_NOTE_MAX = 80
DIGEST_LINE_MAX = 30
MASCOT_LINE_MAX = 50


# Ranking: one call for all candidates (titles and the first 200 characters).


class RankEntry(BaseModel):
    id: int
    score: int = Field(ge=1, le=5)
    category: Category


class Ranking(BaseModel):
    items: list[RankEntry]


# Per-article summary: one call per selected article.


class Term(BaseModel):
    word: str = Field(min_length=1, max_length=TERM_WORD_MAX)
    note: str = Field(min_length=1, max_length=TERM_NOTE_MAX)


class Summary(BaseModel):
    title_ja: str = Field(min_length=1, max_length=TITLE_MAX)
    what: str = Field(max_length=LINE_MAX)  # what happened
    new: str = Field(max_length=LINE_MAX)  # what is new about it
    impact: str = Field(max_length=LINE_MAX)  # what changes for the reader
    term: Term | None
    category: Category
    score: int = Field(ge=1, le=5)


# Daily summary: one call for the whole edition.


DigestLine = Annotated[str, Field(min_length=1, max_length=DIGEST_LINE_MAX)]


class Daily(BaseModel):
    digest: list[DigestLine] = Field(min_length=3, max_length=3)
    mascot_line: str = Field(min_length=1, max_length=MASCOT_LINE_MAX)


# The edition: everything the renderer needs for one day.


class Article(BaseModel):
    id: str  # stable key derived from the normalized URL
    title_ja: str
    what: str
    new: str
    impact: str
    term: Term | None
    category: Category
    score: int
    url: str
    source: str
    source_name: str
    title_en: str
    published: AwareDatetime
    summary_only: bool  # the article body could not be fetched; summarized from the feed text
    also_in: list[str] = Field(default_factory=list)


class Stats(BaseModel):
    collected: int  # items inside each source's window
    candidates: int  # after dedupe
    ranked: int  # sent to the ranking call
    selected: int  # articles in the edition
    llm_calls: int
    providers: list[str]  # providers that produced at least one answer
    seconds: float


class Edition(BaseModel):
    date: date
    generated_at: AwareDatetime
    weather: Weather
    digest: list[str]
    mascot_line: str
    articles: list[Article]
    stats: Stats


# Strict JSON schemas sent to the providers (all fields required, closed objects).

_CATEGORY = {"type": "string", "enum": list(CATEGORIES)}
_SCORE = {"type": "integer", "minimum": 1, "maximum": 5}

RANKING_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "score": _SCORE, "category": _CATEGORY},
                "required": ["id", "score", "category"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "title_ja": {"type": "string"},
        "what": {"type": "string"},
        "new": {"type": "string"},
        "impact": {"type": "string"},
        "term": {
            "anyOf": [
                {
                    "type": "object",
                    "properties": {"word": {"type": "string"}, "note": {"type": "string"}},
                    "required": ["word", "note"],
                    "additionalProperties": False,
                },
                {"type": "null"},
            ]
        },
        "category": _CATEGORY,
        "score": _SCORE,
    },
    "required": ["title_ja", "what", "new", "impact", "term", "category", "score"],
    "additionalProperties": False,
}

DAILY_SCHEMA = {
    "type": "object",
    "properties": {
        "digest": {"type": "array", "items": {"type": "string"}},
        "mascot_line": {"type": "string"},
    },
    "required": ["digest", "mascot_line"],
    "additionalProperties": False,
}
