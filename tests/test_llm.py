import json
from types import SimpleNamespace

import pytest

from ai_news import llm
from ai_news.validate import ValidationFailed

CALL = llm.Call(name="summary-abc", system="sys", user="user", schema={"type": "object"})


class FakeClient:
    def __init__(self, name, answers):
        self.name = name
        self.answers = list(answers)
        self.calls = 0

    def request(self, call):
        self.calls += 1
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _parse(data):
    if data.get("bad"):
        raise ValidationFailed("bad answer")
    return data["value"]


def test_first_answer_wins():
    primary = FakeClient("gemini", [{"value": 1}])
    model = llm.LLM([primary, FakeClient("groq", [])])
    assert model.ask(CALL, _parse) == 1
    assert model.calls == 1 and model.used == ["gemini"]


def test_retry_once_then_succeed():
    primary = FakeClient("gemini", [{"bad": True}, {"value": 2}])
    model = llm.LLM([primary])
    assert model.ask(CALL, _parse) == 2
    assert primary.calls == 2


def test_fallback_after_two_failures_and_stay_on_fallback():
    primary = FakeClient("gemini", [json.JSONDecodeError("x", "", 0), ValidationFailed("x"), {"value": 9}])
    backup = FakeClient("groq", [{"value": 3}, {"value": 4}])
    model = llm.LLM([primary, backup])
    assert model.ask(CALL, _parse) == 3
    assert model.ask(CALL, _parse) == 4  # the backup is now tried first
    assert primary.calls == 2 and backup.calls == 2
    assert model.calls == 4
    assert model.used == ["groq"]


def test_every_provider_failing_raises():
    model = llm.LLM([FakeClient("gemini", [ValidationFailed("a")] * 2), FakeClient("groq", [ValidationFailed("b")] * 2)])
    with pytest.raises(llm.LLMError, match="every provider failed"):
        model.ask(CALL, _parse)


def test_unexpected_errors_are_not_swallowed():
    model = llm.LLM([FakeClient("gemini", [KeyError("bug")])])
    with pytest.raises(KeyError):
        model.ask(CALL, _parse)


def test_replay_and_recording(tmp_path):
    inner = FakeClient("gemini", [{"value": 5}])
    recorder = llm.RecordingClient(inner, tmp_path)
    assert recorder.request(CALL) == {"value": 5}
    assert llm.ReplayClient(tmp_path).request(CALL) == {"value": 5}
    with pytest.raises(FileNotFoundError):
        llm.ReplayClient(tmp_path).request(llm.Call("daily", "s", "u", {}))


def test_openai_compat_request_shape(monkeypatch):
    client = llm.OpenAICompatClient(llm.PROVIDERS["groq"], api_key="test")
    client.provider = llm.Provider(**{**client.provider.__dict__, "min_interval": 0})
    sent = {}

    def create(**kwargs):
        sent.update(kwargs)
        message = SimpleNamespace(content='{"value": 7}')
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(client.client.chat.completions, "create", create)
    assert client.request(CALL) == {"value": 7}
    assert sent["model"] == "qwen/qwen3.8-27b"
    assert sent["reasoning_effort"] == "none"
    assert sent["response_format"]["json_schema"] == {"name": "summary", "strict": True, "schema": {"type": "object"}}
    assert [m["role"] for m in sent["messages"]] == ["system", "user"]


def test_from_env_orders_providers_and_skips_missing_keys(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("GROQ_API_KEY", "q")
    assert [c.name for c in llm.from_env("groq").clients] == ["groq", "gemini"]
    monkeypatch.delenv("GROQ_API_KEY")
    assert [c.name for c in llm.from_env("groq").clients] == ["gemini"]
    monkeypatch.delenv("GEMINI_API_KEY")
    with pytest.raises(llm.LLMError, match="no LLM API key"):
        llm.from_env("gemini")
