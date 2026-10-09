from datetime import timedelta

import pytest

from ai_news import cli, fixtures, paths, pipeline, select, state


@pytest.fixture
def no_state_writes(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("state must not be written")

    monkeypatch.setattr(state, "save_json", fail)


def test_dry_run_exits_cleanly_without_saving_state(no_state_writes):
    assert cli.main(["--dry-run"]) == 0


def test_dry_run_pipeline_on_fixtures():
    now = fixtures.recorded_at()
    result = pipeline.run(now, fixtures.fixture_fetch, seen={}, health={})
    assert result.dedupe.items
    keys = [select.normalize_url(i.url) for i in result.dedupe.items]
    assert len(keys) == len(set(keys))
    assert result.failing == []
    assert set(result.seen.values()) == {result.today.isoformat()}


def test_live_run_saves_state_and_fails_on_broken_source(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "SEEN_PATH", tmp_path / "seen.json")
    monkeypatch.setattr(state, "HEALTH_PATH", tmp_path / "health.json")
    now = fixtures.recorded_at()
    today = state.run_date(now)
    yesterday = (today - timedelta(days=1)).isoformat()
    state.save_json(state.HEALTH_PATH, {"openai": {yesterday: 0}})
    monkeypatch.setattr(cli, "utc_now", lambda: now)

    def fetch(source, url):
        if source.id == "openai":
            raise OSError("down")
        return fixtures.fixture_fetch(source, url)

    monkeypatch.setattr(cli, "http_fetch", fetch)
    assert cli.main([]) == 1
    assert state.load_json(state.SEEN_PATH)
    assert state.load_json(state.HEALTH_PATH)["openai"] == {yesterday: 0, today.isoformat(): 0}


def test_provider_defaults_to_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    assert cli.build_parser().parse_args([]).provider == "groq"


def test_unknown_provider_is_rejected():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--provider", "openai"])


def test_dry_run_and_record_are_exclusive():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--dry-run", "--record-fixtures"])


def test_paths_point_at_repo_root():
    assert (paths.ROOT / "pyproject.toml").is_file()
    assert paths.PUBLIC_DIR == paths.ROOT / "public"
