import pytest

from ai_news.schemas import Daily, Summary
from ai_news.validate import (
    ValidationFailed,
    check_daily,
    check_summary,
    simplified_chars,
    source_numbers,
    unverified_numbers,
)

SOURCE = (
    "Introducing Claude Haiku 5.5. Priced at $0.10 per million input tokens, 30% faster, "
    "with a 1,000,000-token context. Two new tiers and 1.5B downloads."
)


def _summary(**overrides) -> Summary:
    data = {
        "title_ja": "Anthropicが小型AI「Claude Haiku 5.5」を発表",
        "what": "新しい小型モデルが出た",
        "new": "30%速くなった",
        "impact": "安く使える",
        "term": {"word": "トークン", "note": "AIが文章を数える単位"},
        "category": "新モデル",
        "score": 5,
    }
    data.update(overrides)
    return Summary.model_validate(data)


def test_simplified_chinese_is_detected():
    assert simplified_chars("这是一个很重要的模型，我们认为") == ["这", "个", "们", "认", "为"]


@pytest.mark.parametrize(
    "text",
    ["社内資料を意味で探せる検索を作りやすくなる", "画像の一部だけを指定して直す", "頰と剝がす", "会社で使う時間"],
)
def test_japanese_is_not_flagged(text):
    assert simplified_chars(text) == []


@pytest.mark.parametrize(
    ("text", "bad"),
    [
        ("料金は0.10ドルから", []),
        ("100万トークンまで扱える", []),  # 1 million
        ("15億回ダウンロード", []),  # 1.5B in the source
        ("150億回ダウンロード", ["150"]),
        ("ダウンロードは1.5Bを超えた", []),
        ("2つの新しいプラン", []),  # "Two"
        ("40%速くなった", ["40"]),
        ("10月7日に公開された", []),  # dates are exempt
        ("ＧＰＴ５．５", []),  # full-width digits are normalized
    ],
)
def test_unverified_numbers(text, bad):
    assert unverified_numbers(text, source_numbers(SOURCE)) == bad


def test_source_numbers_reads_scales_and_words():
    numbers = source_numbers("3B parameters, 20 thousand users, twice as fast")
    assert {3_000_000_000, 20_000, 2, 3, 20} <= numbers


def test_check_summary_drops_lines_with_unsupported_numbers():
    cleaned = check_summary(_summary(new="40%速くなった", term={"word": "料金", "note": "月5ドル"}), SOURCE)
    assert cleaned.new == ""
    assert cleaned.what == "新しい小型モデルが出た"
    assert cleaned.term is None


def test_check_summary_rejects_numbers_in_title():
    with pytest.raises(ValidationFailed, match="title"):
        check_summary(_summary(title_ja="Haiku 6が登場"), SOURCE)


def test_check_summary_rejects_simplified_chinese():
    with pytest.raises(ValidationFailed, match="simplified"):
        check_summary(_summary(impact="开发者更方便"), SOURCE)


def test_check_summary_rejects_when_no_line_is_left():
    with pytest.raises(ValidationFailed, match="no summary line"):
        check_summary(_summary(what="", new="40%速い", impact=""), SOURCE)


def test_summary_length_limits():
    with pytest.raises(ValueError):
        _summary(what="あ" * 61)
    with pytest.raises(ValueError):
        _summary(title_ja="あ" * 41)


def test_daily_shape_and_checks():
    with pytest.raises(ValueError):
        Daily.model_validate({"digest": ["一", "二"], "mascot_line": "おはよう"})
    with pytest.raises(ValueError):
        Daily.model_validate({"digest": ["一", "二", "あ" * 31], "mascot_line": "おはよう"})
    daily = Daily.model_validate({"digest": ["新しいAIが登場", "安くなった", "30%速い"], "mascot_line": "おはよう"})
    assert check_daily(daily, SOURCE) is daily
    bad = daily.model_copy(update={"mascot_line": "今日は5本だよ"})
    with pytest.raises(ValidationFailed):
        check_daily(bad, SOURCE)


@pytest.mark.parametrize(
    "fields",
    [
        {"title_ja": "AIニュースの内容がありません"},
        {"what": "記事の本文が入力されていないため情報がありません。"},
        {"impact": "詳細は不明です。"},
    ],
)
def test_check_summary_rejects_comments_about_the_input(fields):
    with pytest.raises(ValidationFailed, match="comment about the input"):
        check_summary(_summary(**fields), SOURCE)
