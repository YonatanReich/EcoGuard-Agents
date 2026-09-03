"""
Offline tests for the Claude LLM service.

Nothing here reaches the network and ``anthropic.Anthropic`` is never
constructed — a fake client is injected instead, following the dependency
injection pattern in tests/test_nominatim_geocoding_service.py.

Two things are worth the effort of testing here:

1. The request kwargs. Sonnet 5 rejects sampling parameters and thinking
   budgets with a 400, so asserting they are absent is a genuine regression
   guard rather than a tautology.
2. The error ladder's ordering. Every 4xx SDK exception subclasses
   APIStatusError and APITimeoutError subclasses APIConnectionError, so a
   reordered isinstance chain silently collapses distinct failures into one
   category. The parametrized table below would catch that.

Run with: pytest
"""

from __future__ import annotations

import json

import anthropic
import httpx2
import pytest
from pydantic import BaseModel, Field, ValidationError

from services.claude_llm_service import (
    CLAUDE_ERROR_KINDS,
    DEFAULT_MODEL,
    ClaudeLLMService,
    ClaudeProviderError,
    build_system_blocks,
)


class Answer(BaseModel):
    """Minimal schema used as output_format in these tests."""

    value: int = Field(ge=0, le=100)


class FakeUsage:
    def __init__(self, cache_read: int = 0) -> None:
        self.input_tokens = 1200
        self.output_tokens = 340
        self.cache_creation_input_tokens = 0
        self.cache_read_input_tokens = cache_read


class FakeResponse:
    def __init__(self, parsed_output, cache_read: int = 0) -> None:
        self.parsed_output = parsed_output
        self.usage = FakeUsage(cache_read)


class FakeMessages:
    """Records the kwargs it was called with, then returns or raises."""

    def __init__(self, result) -> None:
        self.result = result
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)

        if isinstance(self.result, Exception):
            raise self.result

        return self.result


class FakeClaudeClient:
    def __init__(self, result) -> None:
        self.messages = FakeMessages(result)


def build_service(result, **kwargs) -> ClaudeLLMService:
    """Construct a service backed by a fake client."""
    return ClaudeLLMService(
        api_key="test-key-not-real",
        client=FakeClaudeClient(result),
        **kwargs,
    )


def make_status_error(cls, status_code: int):
    """
    Build a real SDK exception offline.

    The SDK's status errors need an httpx2 response; httpx2 arrives with
    anthropic 1.x so this needs no network and no extra dependency.
    """
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(status_code, request=request)
    return cls("boom", response=response, body=None)


# --------------------------------------------------------------------------
# Happy path and request shape
# --------------------------------------------------------------------------


def test_parse_structured_returns_validated_model():
    service = build_service(FakeResponse(Answer(value=42)))

    result = service.parse_structured(
        system_blocks=build_system_blocks("stable prompt"),
        user_text="question",
        output_format=Answer,
    )

    assert isinstance(result, Answer)
    assert result.value == 42


def test_usage_is_recorded_for_cache_verification():
    """last_usage is how we confirm prompt caching actually engaged."""
    service = build_service(FakeResponse(Answer(value=1), cache_read=980))

    service.parse_structured(
        system_blocks=build_system_blocks("stable prompt"),
        user_text="question",
        output_format=Answer,
    )

    assert service.last_usage["cache_read_input_tokens"] == 980


def test_request_uses_the_configured_model():
    service = build_service(FakeResponse(Answer(value=1)))

    service.parse_structured(
        system_blocks=build_system_blocks("p"), user_text="q", output_format=Answer
    )

    assert service.client.messages.calls[0]["model"] == DEFAULT_MODEL
    assert DEFAULT_MODEL == "claude-sonnet-5"


@pytest.mark.parametrize("forbidden", ["temperature", "top_p", "top_k"])
def test_sampling_parameters_are_never_sent(forbidden):
    """
    Sonnet 5 rejects these with a 400, and the SDK removed them in 1.x.

    If someone reintroduces one, this fails before it reaches the API.
    """
    service = build_service(FakeResponse(Answer(value=1)))

    service.parse_structured(
        system_blocks=build_system_blocks("p"), user_text="q", output_format=Answer
    )

    assert forbidden not in service.client.messages.calls[0]


def test_thinking_is_adaptive_without_a_token_budget():
    """budget_tokens is rejected with a 400 on Sonnet 5."""
    service = build_service(FakeResponse(Answer(value=1)))

    service.parse_structured(
        system_blocks=build_system_blocks("p"), user_text="q", output_format=Answer
    )

    thinking = service.client.messages.calls[0]["thinking"]

    assert thinking == {"type": "adaptive"}
    assert "budget_tokens" not in thinking


def test_effort_is_passed_inside_output_config():
    """effort belongs in output_config, not at the top level."""
    service = build_service(FakeResponse(Answer(value=1)), effort="low")

    service.parse_structured(
        system_blocks=build_system_blocks("p"), user_text="q", output_format=Answer
    )

    assert service.client.messages.calls[0]["output_config"] == {"effort": "low"}


def test_system_prefix_is_marked_for_caching():
    """
    The stable prefix carries cache_control; the variable text does not.

    Retrieved chunks must stay in the user message or the cached prefix is
    invalidated on every request.
    """
    service = build_service(FakeResponse(Answer(value=1)))

    service.parse_structured(
        system_blocks=build_system_blocks("stable prompt"),
        user_text="retrieved chunks go here",
        output_format=Answer,
    )

    call = service.client.messages.calls[0]

    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert call["messages"] == [
        {"role": "user", "content": "retrieved chunks go here"}
    ]


def test_output_format_is_forwarded():
    service = build_service(FakeResponse(Answer(value=1)))

    service.parse_structured(
        system_blocks=build_system_blocks("p"), user_text="q", output_format=Answer
    )

    assert service.client.messages.calls[0]["output_format"] is Answer


# --------------------------------------------------------------------------
# Credentials
# --------------------------------------------------------------------------


def test_missing_key_reports_unavailable_without_constructing_a_client(monkeypatch):
    """
    No key must not crash at construction.

    The API needs to boot and report per request, not fail at import.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    service = ClaudeLLMService(api_key="")

    assert service.available is False
    assert service.client is None


def test_missing_key_raises_the_credential_category(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    service = ClaudeLLMService(api_key="")

    with pytest.raises(ClaudeProviderError) as excinfo:
        service.parse_structured(
            system_blocks=build_system_blocks("p"), user_text="q", output_format=Answer
        )

    assert str(excinfo.value) == "missing credentials"


def test_injected_client_makes_the_service_available():
    service = build_service(FakeResponse(Answer(value=1)))

    assert service.available is True


# --------------------------------------------------------------------------
# Error mapping
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error,expected",
    [
        (make_status_error(anthropic.AuthenticationError, 401), "authentication error"),
        (make_status_error(anthropic.PermissionDeniedError, 403), "authentication error"),
        (make_status_error(anthropic.RateLimitError, 429), "rate limited"),
        (make_status_error(anthropic.BadRequestError, 400), "invalid request"),
        (make_status_error(anthropic.NotFoundError, 404), "invalid request"),
        (make_status_error(anthropic.InternalServerError, 500), "HTTP error"),
        (
            anthropic.APITimeoutError(
                request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
            ),
            "timeout",
        ),
        (
            anthropic.APIConnectionError(
                request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
            ),
            "network error",
        ),
        (json.JSONDecodeError("bad", "doc", 0), "malformed response"),
        (ValueError("nonsense"), "malformed response"),
        (KeyError("missing"), "malformed response"),
        (RuntimeError("something unexpected"), "provider error"),
    ],
)
def test_errors_map_to_the_closed_vocabulary(error, expected):
    service = build_service(error)

    with pytest.raises(ClaudeProviderError) as excinfo:
        service.parse_structured(
            system_blocks=build_system_blocks("p"), user_text="q", output_format=Answer
        )

    assert str(excinfo.value) == expected
    assert expected in CLAUDE_ERROR_KINDS


def test_subclass_ordering_is_not_collapsed():
    """
    The specific regression the isinstance ladder exists to prevent.

    RateLimitError subclasses APIStatusError. If APIStatusError were checked
    first, this would return "HTTP error" and the caller would lose the ability
    to distinguish a throttle from a server fault.
    """
    service = build_service(make_status_error(anthropic.RateLimitError, 429))

    with pytest.raises(ClaudeProviderError) as excinfo:
        service.parse_structured(
            system_blocks=build_system_blocks("p"), user_text="q", output_format=Answer
        )

    assert str(excinfo.value) == "rate limited"
    assert str(excinfo.value) != "HTTP error"


def test_timeout_is_not_reported_as_a_generic_network_error():
    """APITimeoutError subclasses APIConnectionError; ordering must preserve it."""
    service = build_service(
        anthropic.APITimeoutError(
            request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        )
    )

    with pytest.raises(ClaudeProviderError) as excinfo:
        service.parse_structured(
            system_blocks=build_system_blocks("p"), user_text="q", output_format=Answer
        )

    assert str(excinfo.value) == "timeout"


def test_schema_validation_failure_is_a_malformed_response():
    """
    An uncited or out-of-range answer surfaces as malformed.

    This is the path an ungrounded model answer takes: the schema rejects it and
    the agent reports failure rather than passing it on.
    """
    service = build_service(
        ValidationError.from_exception_data("Answer", [])
        if hasattr(ValidationError, "from_exception_data")
        else ValueError("invalid")
    )

    with pytest.raises(ClaudeProviderError) as excinfo:
        service.parse_structured(
            system_blocks=build_system_blocks("p"), user_text="q", output_format=Answer
        )

    assert str(excinfo.value) == "malformed response"


def test_wrong_parsed_type_is_malformed():
    """A refusal or truncation can yield no parsed output; never return None."""
    service = build_service(FakeResponse(parsed_output=None))

    with pytest.raises(ClaudeProviderError) as excinfo:
        service.parse_structured(
            system_blocks=build_system_blocks("p"), user_text="q", output_format=Answer
        )

    assert str(excinfo.value) == "malformed response"


# --------------------------------------------------------------------------
# Credential safety
# --------------------------------------------------------------------------


def test_cause_chain_is_suppressed():
    """
    ``from None`` keeps the SDK exception — and any echoed prompt — out of the
    traceback that reaches a caller or a log.
    """
    service = build_service(make_status_error(anthropic.BadRequestError, 400))

    with pytest.raises(ClaudeProviderError) as excinfo:
        service.parse_structured(
            system_blocks=build_system_blocks("p"), user_text="q", output_format=Answer
        )

    assert excinfo.value.__cause__ is None


def test_api_key_never_appears_in_a_raised_error():
    """
    Mirrors the FIRMS redaction test in tests/test_fire_detection_agent.py.

    Even when the provider echoes the key back in an error message, nothing but
    the error category may escape.
    """
    api_key = "sk-ant-secret-value-do-not-leak"
    service = ClaudeLLMService(
        api_key=api_key,
        client=FakeClaudeClient(RuntimeError(f"request failed for key {api_key}")),
    )

    with pytest.raises(ClaudeProviderError) as excinfo:
        service.parse_structured(
            system_blocks=build_system_blocks("p"), user_text="q", output_format=Answer
        )

    assert api_key not in str(excinfo.value)
    assert str(excinfo.value) == "provider error"


def test_prompt_content_never_appears_in_a_raised_error():
    """Event data and retrieved protocol text live in the prompt; keep them in."""
    secret_prompt = "hotspot at 31.9,34.8 with FRP 88"
    service = build_service(RuntimeError(f"400 error, echoed input: {secret_prompt}"))

    with pytest.raises(ClaudeProviderError) as excinfo:
        service.parse_structured(
            system_blocks=build_system_blocks("p"),
            user_text=secret_prompt,
            output_format=Answer,
        )

    assert secret_prompt not in str(excinfo.value)


def test_every_mapped_category_is_in_the_closed_vocabulary():
    """No sanitizer branch may invent a category outside the agreed set."""
    service = build_service(FakeResponse(Answer(value=1)))

    errors = [
        make_status_error(anthropic.AuthenticationError, 401),
        make_status_error(anthropic.RateLimitError, 429),
        make_status_error(anthropic.InternalServerError, 500),
        ValueError("x"),
        RuntimeError("x"),
    ]

    for error in errors:
        assert service.sanitize_error(error) in CLAUDE_ERROR_KINDS
