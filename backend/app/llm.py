"""Minimal LLM provider layer for the optional llm-v1 brief generator.

Deliberately small: env-driven config, one provider interface
(`complete_json(system, user) -> str`), one HTTP implementation for
OpenAI-compatible `/chat/completions` endpoints (OpenAI, Hermes, or any
gateway exposing that interface — an Anthropic-native provider is a later
phase), and a mock provider for keyless tests and demos. No retries, no
streaming, no routing. Secrets come from environment variables only and
are never stored or logged.
"""

import json
import os
from dataclasses import dataclass

import httpx

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_TIMEOUT_SECONDS = 30.0
MOCK_DEFAULT_MODEL = "mock-echo-1"


class LLMProviderError(RuntimeError):
    """Raised when the provider is unavailable, misconfigured, or the call fails."""


def _env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


@dataclass(frozen=True)
class LLMConfig:
    provider: str | None
    model: str | None
    api_key: str | None
    base_url: str
    timeout_seconds: float

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """Read config at call time (not import time) so tests can monkeypatch env."""
        provider = _env("ADVISORLENS_LLM_PROVIDER")
        model = _env("ADVISORLENS_LLM_MODEL")
        if provider == "mock" and model is None:
            model = MOCK_DEFAULT_MODEL
        try:
            timeout = float(_env("ADVISORLENS_LLM_TIMEOUT_SECONDS") or DEFAULT_TIMEOUT_SECONDS)
        except ValueError:
            timeout = DEFAULT_TIMEOUT_SECONDS
        return cls(
            provider=provider,
            model=model,
            api_key=_env("ADVISORLENS_LLM_API_KEY"),
            base_url=_env("ADVISORLENS_LLM_BASE_URL") or DEFAULT_BASE_URL,
            timeout_seconds=timeout,
        )

    @property
    def is_configured(self) -> bool:
        if self.provider == "mock":
            return True
        return bool(self.provider and self.model and self.api_key)


class OpenAICompatibleProvider:
    """Calls an OpenAI-compatible POST {base_url}/chat/completions endpoint.

    This covers OpenAI, Hermes, and gateways that expose the same interface.
    It does not support Anthropic-native APIs; that would be a separate
    provider in a later phase.
    """

    name = "openai-compatible"

    def __init__(self, config: LLMConfig):
        self._config = config

    def complete_json(self, system: str, user: str) -> str:
        url = self._config.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        }
        try:
            response = httpx.post(
                url,
                json=payload,
                timeout=self._config.timeout_seconds,
                headers={"Authorization": f"Bearer {self._config.api_key}"},
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001 - any transport/shape failure means fallback
            raise LLMProviderError(f"LLM request failed: {type(exc).__name__}: {exc}") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMProviderError("LLM returned an empty response.")
        return content


class MockEchoProvider:
    """Test/demo provider: builds a valid narrative response mechanically
    from the input packet. Requires no API key. Not for real use — it exists
    so the llm-v1 pipeline (including validation and fallback) can be
    exercised end to end without external calls.
    """

    name = "mock"

    def __init__(self, config: LLMConfig):
        self._config = config

    def complete_json(self, system: str, user: str) -> str:
        packet = json.loads(user)
        flags = packet["flags"]
        payload = {
            "executive_summary": [
                "This advisor-support brief was drafted by the mock language provider "
                "for demonstration purposes.",
                (
                    f"It reviews the uploaded file '{packet['source_name']}' "
                    f"(analysis #{packet['analysis_id']}) using only the deterministic "
                    "analysis results provided."
                ),
            ],
            "key_review_items": [
                {"rule_id": f["rule_id"], "narrative": f["message"]} for f in flags
            ],
            "advisor_talking_points": (
                [f["message"] for f in flags]
                or ["Review the portfolio snapshot with the client and confirm it still reflects their goals."]
            ),
            "client_discussion_questions": [
                "Have your goals or time horizon changed since our last review?"
            ],
            "follow_up_items": [
                "Document today's discussion and any decisions in the client file."
            ],
        }
        return json.dumps(payload)


_PROVIDERS = {
    OpenAICompatibleProvider.name: OpenAICompatibleProvider,
    MockEchoProvider.name: MockEchoProvider,
}


def get_provider(config: LLMConfig):
    if not config.provider:
        raise LLMProviderError("No LLM provider is configured (ADVISORLENS_LLM_PROVIDER unset).")
    provider_cls = _PROVIDERS.get(config.provider)
    if provider_cls is None:
        raise LLMProviderError(f"Unknown LLM provider '{config.provider}'.")
    if not config.is_configured:
        raise LLMProviderError(
            f"LLM provider '{config.provider}' is not fully configured "
            "(model and API key are required)."
        )
    return provider_cls(config)
