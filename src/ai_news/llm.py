"""LLM access: Gemini and Groq through their OpenAI-compatible APIs.

Every call asks for strict JSON, is parsed and validated by the caller's `parse`,
retried once, and then sent to the other provider. After a provider has failed a
call completely, later calls go to the other provider first.
"""

import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, TypeVar

import openai
from pydantic import ValidationError

from ai_news.paths import FIXTURES_DIR
from ai_news.validate import ValidationFailed

log = logging.getLogger(__name__)

T = TypeVar("T")
LLM_FIXTURES = FIXTURES_DIR / "llm"
REQUEST_TIMEOUT = 90.0
ATTEMPTS_PER_PROVIDER = 2  # the first try plus one retry


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    model: str
    api_key_env: str
    min_interval: float  # seconds between requests, to stay inside the free tier
    options: dict = field(default_factory=dict)


PROVIDERS = {
    "gemini": Provider(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        model="gemini-3.5-flash-lite",
        api_key_env="GEMINI_API_KEY",
        min_interval=5.0,
        options={"reasoning_effort": "minimal"},  # thinking cannot be fully disabled on 3.x
    ),
    "groq": Provider(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        model="qwen/qwen3.8-27b",
        api_key_env="GROQ_API_KEY",
        min_interval=30.0,  # 8K tokens per minute: about two requests per minute
        options={"reasoning_effort": "none"},
    ),
}


@dataclass(frozen=True)
class Call:
    name: str  # stable id, also the fixture file name: "rank", "summary-<id>", "daily"
    system: str
    user: str
    schema: dict
    max_tokens: int = 2048


class Client(Protocol):
    name: str

    def request(self, call: Call) -> dict: ...


class LLMError(RuntimeError):
    """No provider produced a valid answer."""


class OpenAICompatClient:
    def __init__(self, provider: Provider, api_key: str):
        self.name = provider.name
        self.provider = provider
        self.client = openai.OpenAI(
            api_key=api_key, base_url=provider.base_url, timeout=REQUEST_TIMEOUT, max_retries=0
        )
        self._last_request = 0.0

    def request(self, call: Call) -> dict:
        wait = self.provider.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()
        response = self.client.chat.completions.create(
            model=self.provider.model,
            messages=[
                {"role": "system", "content": call.system},
                {"role": "user", "content": call.user},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": call.name.split("-")[0], "strict": True, "schema": call.schema},
            },
            temperature=0.3,
            max_completion_tokens=call.max_tokens,
            **self.provider.options,
        )
        content = response.choices[0].message.content or ""
        return json.loads(content)


class ReplayClient:
    """Answers from recorded responses (tests and --dry-run)."""

    name = "replay"

    def __init__(self, directory: Path = LLM_FIXTURES):
        self.directory = directory

    def request(self, call: Call) -> dict:
        path = self.directory / f"{call.name}.json"
        if not path.exists():
            raise FileNotFoundError(f"no recorded response for {call.name}")
        return json.loads(path.read_text(encoding="utf-8"))


class RecordingClient:
    """Passes calls through and saves each raw answer as a fixture."""

    def __init__(self, inner: Client, directory: Path = LLM_FIXTURES):
        self.name = inner.name
        self.inner = inner
        self.directory = directory

    def request(self, call: Call) -> dict:
        data = self.inner.request(call)
        self.directory.mkdir(parents=True, exist_ok=True)
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        (self.directory / f"{call.name}.json").write_text(text, encoding="utf-8", newline="\n")
        return data


RETRYABLE = (openai.OpenAIError, json.JSONDecodeError, ValidationError, ValidationFailed, FileNotFoundError)


class LLM:
    """Ordered providers with retry and fallback; counts every request made."""

    def __init__(self, clients: list[Client]):
        if not clients:
            raise ValueError("at least one LLM client is required")
        self.clients = list(clients)
        self.calls = 0
        self.used: list[str] = []  # providers that produced at least one valid answer

    def ask(self, call: Call, parse: Callable[[dict], T]) -> T:
        errors = []
        for client in list(self.clients):
            for attempt in range(1, ATTEMPTS_PER_PROVIDER + 1):
                self.calls += 1
                try:
                    result = parse(client.request(call))
                except RETRYABLE as exc:
                    log.warning("%s: %s attempt %d failed: %s", call.name, client.name, attempt, _short(exc))
                    errors.append(f"{client.name}: {_short(exc)}")
                    continue
                if client.name not in self.used:
                    self.used.append(client.name)
                return result
            if len(self.clients) > 1 and self.clients[0] is client:
                log.warning("%s failed twice; trying the other provider first from now on", client.name)
                self.clients.append(self.clients.pop(0))
        raise LLMError(f"{call.name}: every provider failed ({'; '.join(errors)})")


def _short(exc: Exception) -> str:
    return " ".join(f"{type(exc).__name__}: {exc}".split())[:300]


def from_env(primary: str, record: bool = False) -> LLM:
    """Clients for the primary provider and then the other one, skipping missing keys."""
    order = [primary] + [name for name in PROVIDERS if name != primary]
    clients: list[Client] = []
    for name in order:
        provider = PROVIDERS[name]
        api_key = os.environ.get(provider.api_key_env)
        if not api_key:
            log.warning("%s is not set; %s is unavailable", provider.api_key_env, name)
            continue
        client: Client = OpenAICompatClient(provider, api_key)
        clients.append(RecordingClient(client) if record else client)
    if not clients:
        raise LLMError("no LLM API key: set GEMINI_API_KEY and/or GROQ_API_KEY")
    return LLM(clients)
