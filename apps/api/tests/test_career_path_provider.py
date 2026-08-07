from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import AsyncOpenAI as RealAsyncOpenAI
from pydantic import SecretStr

import career_agent_api.services.career_path as career_path
from career_agent_api.core.config import Settings
from career_agent_api.schemas.api import CareerPathGeneratedReply
from career_agent_api.services.career_path import (
    MISTRAL_API_BASE_URL,
    CareerPathContextMessage,
    CareerPathFactContext,
    CareerPathProviderContext,
    CareerPathProviderError,
    DisabledCareerPathProvider,
    MistralCareerPathProvider,
    OpenAICareerPathProvider,
    build_safety_identifier,
    get_career_path_provider,
)


@dataclass
class _OpenAICapture:
    output_parsed: CareerPathGeneratedReply | None = field(
        default_factory=lambda: CareerPathGeneratedReply(
            message="Which kind of work gives you the most energy?",
            suggestions=[],
        )
    )
    provider_error: Exception | None = None
    client_kwargs: dict[str, Any] = field(default_factory=dict)
    parse_calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class _MistralCapture:
    content: str | None = field(
        default_factory=lambda: CareerPathGeneratedReply(
            message="Which kind of work gives you the most energy?",
            suggestions=[],
        ).model_dump_json()
    )
    finish_reason: str | None = "stop"
    provider_error: Exception | None = None
    client_kwargs: dict[str, Any] = field(default_factory=dict)
    create_calls: list[dict[str, Any]] = field(default_factory=list)


def _install_fake_openai(
    monkeypatch: pytest.MonkeyPatch,
    capture: _OpenAICapture,
) -> None:
    class _FakeResponses:
        async def parse(self, **kwargs: Any) -> SimpleNamespace:
            capture.parse_calls.append(kwargs)
            if capture.provider_error is not None:
                raise capture.provider_error
            return SimpleNamespace(output_parsed=capture.output_parsed)

    class _FakeAsyncOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            capture.client_kwargs = kwargs
            self.responses = _FakeResponses()

        async def __aenter__(self) -> _FakeAsyncOpenAI:
            return self

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: object | None,
        ) -> bool:
            del exc_type, exc, traceback
            return False

    monkeypatch.setattr(career_path, "AsyncOpenAI", _FakeAsyncOpenAI)


def _install_fake_mistral(
    monkeypatch: pytest.MonkeyPatch,
    capture: _MistralCapture,
) -> None:
    class _FakeCompletions:
        async def create(self, **kwargs: Any) -> SimpleNamespace:
            capture.create_calls.append(kwargs)
            if capture.provider_error is not None:
                raise capture.provider_error
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason=capture.finish_reason,
                        message=SimpleNamespace(content=capture.content),
                    )
                ]
            )

    class _FakeAsyncOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            capture.client_kwargs = kwargs
            self.chat = SimpleNamespace(completions=_FakeCompletions())

        async def __aenter__(self) -> _FakeAsyncOpenAI:
            return self

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: object | None,
        ) -> bool:
            del exc_type, exc, traceback
            return False

    monkeypatch.setattr(career_path, "AsyncOpenAI", _FakeAsyncOpenAI)


def _context(*, message_count: int = 1) -> CareerPathProviderContext:
    owner_id = "clerk-owner-must-not-leave-the-server"
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url="sqlite+aiosqlite://",
        ai_provider="deterministic",
        ai_safety_salt=SecretStr("test-only-safety-pepper"),
    )
    safety_identifier = build_safety_identifier(owner_id, settings)
    assert safety_identifier != owner_id

    return CareerPathProviderContext(
        locale="en",
        confirmed_facts=(
            CareerPathFactContext(
                handle="fact_1",
                category="skill",
                label="Python",
                detail="Built internal automation",
            ),
        ),
        messages=tuple(
            CareerPathContextMessage(
                role="user" if index % 2 == 0 else "assistant",
                content=f"context-message-{index:02d}",
            )
            for index in range(message_count)
        ),
        safety_identifier=safety_identifier,
    )


@pytest.mark.asyncio
async def test_openai_request_is_stateless_bounded_and_privacy_preserving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = _OpenAICapture()
    _install_fake_openai(monkeypatch, capture)
    context = _context(message_count=16)
    provider = OpenAICareerPathProvider(
        api_key="test-provider-key",
        model="test-model",
        timeout_seconds=9,
        max_output_tokens=50_000,
    )

    result = await provider.generate(context)

    assert result.message == "Which kind of work gives you the most energy?"
    assert capture.client_kwargs == {
        "api_key": "test-provider-key",
        "timeout": 9,
        "max_retries": 1,
    }
    assert len(capture.parse_calls) == 1
    request = capture.parse_calls[0]
    assert request["store"] is False
    assert request["max_output_tokens"] == 1_000
    assert request["max_output_tokens"] <= 1_000
    assert request["safety_identifier"] == context.safety_identifier
    assert request["safety_identifier"] != "clerk-owner-must-not-leave-the-server"
    assert "clerk-owner-must-not-leave-the-server" not in repr(request)
    for forbidden_field in ("previous_response_id", "conversation", "tools"):
        assert forbidden_field not in request

    # The first item is the server-built confirmed-facts data block. Only the most recent
    # twelve conversation messages may follow it.
    input_items = request["input"]
    assert isinstance(input_items, list)
    assert len(input_items) == 13
    conversation_items = input_items[1:]
    assert [item["content"] for item in conversation_items] == [
        f"context-message-{index:02d}" for index in range(4, 16)
    ]
    assert "context-message-03" not in repr(request)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "empty_output",
    [
        None,
        CareerPathGeneratedReply(message="   ", suggestions=[]),
    ],
)
async def test_empty_openai_output_becomes_safe_provider_error(
    monkeypatch: pytest.MonkeyPatch,
    empty_output: CareerPathGeneratedReply | None,
) -> None:
    capture = _OpenAICapture(output_parsed=empty_output)
    _install_fake_openai(monkeypatch, capture)
    provider = OpenAICareerPathProvider(api_key="test-provider-key", model="test-model")

    with pytest.raises(CareerPathProviderError) as raised:
        await provider.generate(_context())

    assert str(raised.value) == "Career path provider returned no usable response"
    assert "test-provider-key" not in str(raised.value)


@pytest.mark.asyncio
async def test_openai_exception_becomes_safe_provider_error_without_provider_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sensitive_provider_detail = (
        "upstream body contained user@example.test and sk-provider-secret"
    )
    capture = _OpenAICapture(provider_error=RuntimeError(sensitive_provider_detail))
    _install_fake_openai(monkeypatch, capture)
    provider = OpenAICareerPathProvider(api_key="sk-provider-secret", model="test-model")

    with pytest.raises(CareerPathProviderError) as raised:
        await provider.generate(_context())

    assert str(raised.value) == "Career path provider request failed"
    assert sensitive_provider_detail not in str(raised.value)
    assert "user@example.test" not in str(raised.value)
    assert "sk-provider-secret" not in str(raised.value)


@pytest.mark.asyncio
async def test_mistral_request_is_structured_bounded_and_privacy_preserving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = _MistralCapture()
    _install_fake_mistral(monkeypatch, capture)
    context = _context(message_count=16)
    provider = MistralCareerPathProvider(
        api_key="test-mistral-key",
        model="mistral-small-2603",
        timeout_seconds=11,
        max_output_tokens=50_000,
    )

    result = await provider.generate(context)

    assert result.message == "Which kind of work gives you the most energy?"
    assert capture.client_kwargs == {
        "api_key": "test-mistral-key",
        "base_url": MISTRAL_API_BASE_URL,
        "timeout": 11,
        "max_retries": 1,
    }
    assert len(capture.create_calls) == 1
    request = capture.create_calls[0]
    assert set(request) == {
        "model",
        "messages",
        "max_tokens",
        "temperature",
        "stream",
        "response_format",
    }
    assert request["model"] == "mistral-small-2603"
    assert request["max_tokens"] == 1_000
    assert request["temperature"] == 0.2
    assert request["stream"] is False
    assert request["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "career_path_reply",
            "strict": True,
            "schema": CareerPathGeneratedReply.model_json_schema(),
        },
    }

    messages = request["messages"]
    assert isinstance(messages, list)
    assert messages[0] == {
        "role": "system",
        "content": career_path.SYSTEM_INSTRUCTIONS,
    }
    assert len(messages) == 14
    conversation_items = messages[2:]
    assert [item["content"] for item in conversation_items] == [
        f"context-message-{index:02d}" for index in range(4, 16)
    ]
    assert "context-message-03" not in repr(request)
    assert "clerk-owner-must-not-leave-the-server" not in repr(request)
    assert context.safety_identifier not in repr(request)
    assert "test-mistral-key" not in repr(request)


@pytest.mark.asyncio
async def test_mistral_uses_the_official_chat_completions_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    reply = CareerPathGeneratedReply(
        message="Let us narrow the options.",
        suggestions=[],
    ).model_dump_json()

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "cmpl-test",
                "object": "chat.completion",
                "created": 1,
                "model": "mistral-small-2603",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": reply},
                    }
                ],
            },
        )

    def real_client_factory(**kwargs: Any) -> RealAsyncOpenAI:
        return RealAsyncOpenAI(
            **kwargs,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

    monkeypatch.setattr(career_path, "AsyncOpenAI", real_client_factory)
    provider = MistralCareerPathProvider(
        api_key="test-mistral-key",
        model="mistral-small-2603",
    )

    result = await provider.generate(_context())

    assert result.message == "Let us narrow the options."
    assert captured["url"] == f"{MISTRAL_API_BASE_URL}/chat/completions"
    assert captured["authorization"] == "Bearer test-mistral-key"
    body = captured["body"]
    assert body["model"] == "mistral-small-2603"
    assert body["response_format"]["type"] == "json_schema"
    for forbidden_field in (
        "store",
        "verbosity",
        "safety_identifier",
        "metadata",
        "tools",
    ):
        assert forbidden_field not in body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "finish_reason"),
    [
        (None, "stop"),
        ("   ", "stop"),
        ("not-json", "stop"),
        ('{"message":"ok","suggestions":[],"unexpected":true}', "stop"),
        ('{"message":"ok","suggestions":[]}', "length"),
    ],
)
async def test_unusable_mistral_output_becomes_safe_provider_error(
    monkeypatch: pytest.MonkeyPatch,
    content: str | None,
    finish_reason: str | None,
) -> None:
    capture = _MistralCapture(content=content, finish_reason=finish_reason)
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralCareerPathProvider(
        api_key="test-mistral-key",
        model="mistral-small-2603",
    )

    with pytest.raises(CareerPathProviderError) as raised:
        await provider.generate(_context())

    assert str(raised.value) == "Career path provider returned no usable response"
    assert "test-mistral-key" not in str(raised.value)


@pytest.mark.asyncio
async def test_mistral_exception_discards_sensitive_provider_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sensitive_provider_detail = (
        "upstream body contained user@example.test and mistral-secret"
    )
    capture = _MistralCapture(provider_error=RuntimeError(sensitive_provider_detail))
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralCareerPathProvider(
        api_key="mistral-secret",
        model="mistral-small-2603",
    )

    with pytest.raises(CareerPathProviderError) as raised:
        await provider.generate(_context())

    assert str(raised.value) == "Career path provider request failed"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert sensitive_provider_detail not in str(raised.value)
    assert "mistral-secret" not in str(raised.value)


def test_provider_factory_uses_only_the_selected_providers_key() -> None:
    mistral = get_career_path_provider(
        Settings(
            _env_file=None,
            environment="test",
            ai_provider="mistral",
            mistral_api_key=SecretStr("mistral-key"),
            ai_model="mistral-small-2603",
        )
    )
    assert isinstance(mistral, MistralCareerPathProvider)
    assert mistral.model == "mistral-small-2603"

    wrong_key = get_career_path_provider(
        Settings(
            _env_file=None,
            environment="test",
            ai_provider="mistral",
            openai_api_key=SecretStr("openai-key"),
            ai_model="mistral-small-2603",
        )
    )
    assert isinstance(wrong_key, DisabledCareerPathProvider)
    assert wrong_key.provider_name == "mistral"
