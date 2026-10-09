from datetime import timedelta

import pytest

from ai_news import article, cli, fixtures, llm, paths, state


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """Point data/ and public/ at a temp dir."""
    monkeypatch.setattr(state, "SEEN_PATH", tmp_path / "seen.json")
    monkeypatch.setattr(state, "HEALTH_PATH", tmp_path / "health.json")
    monkeypatch.setattr(state, "DAILY_DIR", tmp_path / "daily")
    monkeypatch.setattr(state, "GLOSSARY_PATH", tmp_path / "glossary.json")
    monkeypatch.setattr(cli, "PUBLIC_DIR", tmp_path / "public")
    return tmp_path


def test_dry_run_renders_without_saving_state(isolated, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("state must not be written")

    monkeypatch.setattr(state, "save_json", fail)
    assert cli.main(["--dry-run"]) == 0
    assert (isolated / "public" / "index.html").is_file()
    assert not (isolated / "daily").exists()


def test_render_only_needs_data(isolated):
    assert cli.main(["--render-only"]) == 1


@pytest.fixture
def live_offline(monkeypatch, isolated):
    """A live run wired to fixtures, with state and output redirected to a temp dir."""
    tmp_path = isolated
    monkeypatch.setattr(cli, "utc_now", fixtures.recorded_at)
    monkeypatch.setattr(cli, "http_fetch", fixtures.fixture_fetch)
    monkeypatch.setattr(article, "fetch_body", article.feed_text_body)
    monkeypatch.setattr(llm, "from_env", lambda primary, record=False: llm.LLM([llm.ReplayClient()]))
    return tmp_path


def test_live_run_saves_state_and_edition(live_offline):
    assert cli.main([]) == 0
    today = state.run_date(fixtures.recorded_at()).isoformat()
    edition = state.load_json(live_offline / "daily" / f"{today}.json")
    assert edition["date"] == today and edition["articles"]
    assert state.load_json(state.SEEN_PATH)
    assert state.load_json(state.HEALTH_PATH)["openai"] == {today: 40}
    assert state.load_json(state.GLOSSARY_PATH)
    assert (live_offline / "public" / "index.html").is_file()
    assert (live_offline / "public" / f"archive/{today}/index.html").is_file()
    assert cli.main(["--render-only"]) == 0


def test_live_run_fails_on_source_broken_two_days(live_offline, monkeypatch):
    today = state.run_date(fixtures.recorded_at())
    state.save_json(state.HEALTH_PATH, {"openai": {(today - timedelta(days=1)).isoformat(): 0}})

    def fetch(source, url):
        if source.id == "openai":
            raise OSError("down")
        return fixtures.fixture_fetch(source, url)

    monkeypatch.setattr(cli, "http_fetch", fetch)
    assert cli.main([]) == 1
    assert state.load_json(state.HEALTH_PATH)["openai"][today.isoformat()] == 0


def test_live_run_fails_when_no_edition(live_offline, monkeypatch, tmp_path):
    empty = tmp_path / "no-answers"
    monkeypatch.setattr(llm, "from_env", lambda primary, record=False: llm.LLM([llm.ReplayClient(empty)]))
    assert cli.main([]) == 1
    assert state.load_json(state.SEEN_PATH) == {}
    assert not (live_offline / "daily").exists()


def test_live_run_without_api_keys_fails_cleanly(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert cli.main([]) == 1


def test_provider_defaults_to_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    assert cli.build_parser().parse_args([]).provider == "groq"


def test_unknown_provider_is_rejected():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--provider", "openai"])


def test_modes_are_exclusive():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--dry-run", "--record-llm"])


def test_paths_point_at_repo_root():
    assert (paths.ROOT / "pyproject.toml").is_file()
    assert paths.PUBLIC_DIR == paths.ROOT / "public"
