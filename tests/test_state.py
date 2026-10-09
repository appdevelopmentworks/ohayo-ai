from datetime import UTC, date, datetime

from ai_news import state

TODAY = date(2026, 10, 9)


def test_run_date_is_jst():
    assert state.run_date(datetime(2026, 10, 8, 21, 17, tzinfo=UTC)) == date(2026, 10, 9)
    assert state.run_date(datetime(2026, 10, 8, 14, 59, tzinfo=UTC)) == date(2026, 10, 8)


def test_update_seen_prunes_after_seven_days_and_keeps_first_date():
    seen = {"old": "2026-10-02", "recent": "2026-10-03", "known": "2026-10-08"}
    updated = state.update_seen(seen, {"known", "new"}, TODAY)
    assert updated == {"recent": "2026-10-03", "known": "2026-10-08", "new": "2026-10-09"}


def test_update_health_records_today_and_prunes():
    health = {"openai": {"2026-10-01": 5, "2026-10-08": 3}, "removed": {"2026-10-01": 1}}
    updated = state.update_health(health, {"openai": 4, "hn": 0}, TODAY)
    assert updated == {"openai": {"2026-10-08": 3, "2026-10-09": 4}, "hn": {"2026-10-09": 0}}


def test_failing_sources_needs_two_zero_days_in_a_row():
    health = {
        "broken": {"2026-10-08": 0, "2026-10-09": 0},
        "recovered": {"2026-10-08": 0, "2026-10-09": 2},
        "first_zero": {"2026-10-08": 4, "2026-10-09": 0},
        "no_history": {"2026-10-09": 0},
    }
    assert state.failing_sources(health, TODAY) == ["broken"]


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "nested" / "seen.json"
    state.save_json(path, {"b": "日本語", "a": 1})
    assert path.read_bytes().endswith(b"}\n")
    assert b"\r\n" not in path.read_bytes()
    assert state.load_json(path) == {"a": 1, "b": "日本語"}
    assert state.load_json(tmp_path / "missing.json") == {}
