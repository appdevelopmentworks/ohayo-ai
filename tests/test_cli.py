import pytest

from ai_news import cli, paths


def test_dry_run_exits_cleanly():
    assert cli.main(["--dry-run"]) == 0


def test_provider_defaults_to_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    assert cli.build_parser().parse_args([]).provider == "groq"


def test_unknown_provider_is_rejected():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--provider", "openai"])


def test_paths_point_at_repo_root():
    assert (paths.ROOT / "pyproject.toml").is_file()
    assert paths.PUBLIC_DIR == paths.ROOT / "public"
