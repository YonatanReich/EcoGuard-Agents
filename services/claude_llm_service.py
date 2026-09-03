"""
Claude LLM Service

Responsible for the one thing the agents cannot do offline: running a structured
Claude call and returning a schema-validated result. It knows nothing about
fires — it takes system blocks, a user message and a Pydantic model, and returns
an instance of that model or raises a sanitized error.

Failure handling follows the newer house convention (see
agents/firms_data_agent.py): this is a leaf provider client, so it RAISES a typed
error whose message comes from a closed vocabulary, and the orchestrating agents
catch it and translate it into a "failed" status. It never invents a result.

Credential safety:
    Every raise uses ``from None``. The Anthropic key travels in a header rather
    than a URL, so the leak vector is weaker than the FIRMS one — but a
    BadRequestError body can echo the prompt back, and the prompt contains event
    data and retrieved protocol text. The SDK's exception ``__str__`` includes
    response bodies. Suppressing the cause chain bounds what can escape to
    exactly one word from CLAUDE_ERROR_KINDS.

Testability:
    ``client`` is injectable, following the pattern in
    services/nominatim_geocoding_service.py. Tests pass a fake exposing
    ``.messages.parse(**kwargs)``; ``anthropic.Anthropic`` is never constructed
    in the test suite.

Consumed by: agents.risk_analysis_agent, agents.response_planning_agent
"""

from __future__ import annotations

import json
import logging
import os

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

load_dotenv()

# Exact model id, no date suffix. Sonnet 5 is an explicit project choice; if
# grounding quality disappoints, raise `effort` before changing model.
DEFAULT_MODEL = "claude-sonnet-5"

DEFAULT_MAX_TOKENS = 4096
DEFAULT_EFFORT = "medium"
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_RETRIES = 1

# Closed vocabulary, extending the set already used by the FIRMS and weather
# agents. Anything outside this set must never reach a caller.
CLAUDE_ERROR_KINDS = frozenset(
    {
        "authentication error",
        "rate limited",
        "invalid request",
        "HTTP error",
        "timeout",
        "network error",
        "malformed response",
        "missing credentials",
        "provider error",
    }
)


class ClaudeProviderError(RuntimeError):
    """Credential-safe Claude failure carrying a provider-level error category."""


class ClaudeLLMService:
    """
    Thin, testable wrapper around one structured Claude call.

    Attributes:
        model (str): Model id sent on every request.
        max_tokens (int): Output cap per request.
        effort (str): Thinking depth — "low" through "max".
        last_usage (dict | None): Token usage from the most recent successful
            call, including cache counters. Read this to confirm prompt caching
            actually engaged; do not assume it did.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        workspace_id: str | None = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        effort: str = DEFAULT_EFFORT,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        client: object | None = None,
    ) -> None:
        self._api_key = os.getenv("ANTHROPIC_API_KEY") if api_key is None else api_key

        # Identity-linked API keys are scoped to a workspace and the API rejects
        # them with a 400 unless every request names it. Plain organisation keys
        # ignore this header, so sending it when present is safe either way.
        self._workspace_id = (
            os.getenv("ANTHROPIC_WORKSPACE_ID") if workspace_id is None else workspace_id
        )

        self.model = model
        self.max_tokens = max_tokens
        self.effort = effort
        self.last_usage: dict | None = None

        if client is not None:
            self.client = client
        elif self._api_key:
            self.client = anthropic.Anthropic(
                api_key=self._api_key,
                timeout=timeout_seconds,
                max_retries=max_retries,
                default_headers=(
                    {"anthropic-workspace-id": self._workspace_id}
                    if self._workspace_id
                    else None
                ),
            )
        else:
            # Importable and constructible with no key present, so the API can
            # boot and report "missing credentials" per request rather than
            # crashing at startup. Mirrors NominatimGeocoder's "skipped" path.
            self.client = None

    @property
    def available(self) -> bool:
        """
        Whether a call can be attempted at all.

        Agents check this before retrieving protocol text, so a missing key
        costs nothing and reports honestly.
        """
        return self.client is not None

    def parse_structured(
        self,
        *,
        system_blocks: list[dict],
        user_text: str,
        output_format: type[BaseModel],
    ) -> BaseModel:
        """
        Run one structured Claude call and return the validated result.

        Sonnet 5 constraints honoured here: ``thinking`` is adaptive (the only
        on-mode; ``budget_tokens`` is rejected with a 400), and no sampling
        parameters are sent — ``temperature``/``top_p``/``top_k`` were removed
        from the SDK in 1.x and are rejected by the model besides.

        Args:
            system_blocks (list[dict]): System content blocks. The stable prefix
                should carry ``cache_control`` — see build_system_blocks.
            user_text (str): The per-request message. Retrieved protocol
                excerpts and event evidence belong here, AFTER the cached
                prefix, so caching is not invalidated on every call.
            output_format (type[BaseModel]): Schema the response must satisfy.

        Returns:
            BaseModel: A validated instance of output_format.

        Raises:
            ClaudeProviderError: With a message drawn from CLAUDE_ERROR_KINDS.
                The cause chain is suppressed, so no prompt content or
                credential material reaches the caller.
        """
        if self.client is None:
            raise ClaudeProviderError("missing credentials") from None

        try:
            response = self.client.messages.parse(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system_blocks,
                messages=[{"role": "user", "content": user_text}],
                thinking={"type": "adaptive"},
                output_config={"effort": self.effort},
                output_format=output_format,
            )
            parsed = response.parsed_output
        except Exception as error:
            raise ClaudeProviderError(self.sanitize_error(error)) from None

        # A refusal or a truncated response can yield no parsed output at all.
        # Treat that as malformed rather than returning None to a caller that
        # expects a model instance.
        if not isinstance(parsed, output_format):
            raise ClaudeProviderError("malformed response") from None

        self.last_usage = self.read_usage(response)

        logging.info(
            "Claude call complete: model=%s effort=%s cache_read=%s",
            self.model,
            self.effort,
            (self.last_usage or {}).get("cache_read_input_tokens"),
        )

        return parsed

    def sanitize_error(self, error: Exception) -> str:
        """
        Map any exception onto the closed error vocabulary.

        Mirrors FireDetectionAgent.sanitize_firms_error. The ordering below is
        load-bearing: AuthenticationError, PermissionDeniedError,
        RateLimitError, NotFoundError and BadRequestError all subclass
        APIStatusError, and APITimeoutError subclasses APIConnectionError. Check
        subclasses first or every failure collapses into "HTTP error".

        Args:
            error (Exception): The raised exception.

        Returns:
            str: A member of CLAUDE_ERROR_KINDS. Never includes request details,
                response bodies, or credential material.
        """
        if isinstance(error, ClaudeProviderError):
            kind = str(error)
            return kind if kind in CLAUDE_ERROR_KINDS else "provider error"

        if isinstance(error, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
            return "authentication error"

        if isinstance(error, anthropic.RateLimitError):
            return "rate limited"

        if isinstance(error, (anthropic.BadRequestError, anthropic.NotFoundError)):
            return "invalid request"

        if isinstance(error, anthropic.APITimeoutError):
            return "timeout"

        if isinstance(error, anthropic.APIConnectionError):
            return "network error"

        if isinstance(error, anthropic.APIStatusError):
            return "HTTP error"

        if isinstance(error, (ValidationError, json.JSONDecodeError)):
            return "malformed response"

        if isinstance(error, (KeyError, TypeError, ValueError, AttributeError)):
            return "malformed response"

        return "provider error"

    def read_usage(self, response: object) -> dict | None:
        """
        Extract token usage from a response, tolerating a fake in tests.

        Args:
            response (object): The SDK response object.

        Returns:
            dict | None: Usage counters, or None when the response carries none.
        """
        usage = getattr(response, "usage", None)

        if usage is None:
            return None

        return {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "cache_creation_input_tokens": getattr(
                usage, "cache_creation_input_tokens", None
            ),
            "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
        }


def build_system_blocks(prompt: str) -> list[dict]:
    """
    Wrap a stable system prompt in a cacheable content block.

    Prompt caching is a prefix match: any byte change invalidates everything
    after it. So only genuinely stable text belongs here — role, rubric,
    citation rules, field definitions. Anything varying per request (retrieved
    chunks, event evidence, timestamps) goes in the user message instead.

    Caching silently no-ops below roughly 1024 tokens. That is not an error, but
    do not claim caching works without reading
    ``ClaudeLLMService.last_usage["cache_read_input_tokens"]`` on a second call.

    Args:
        prompt (str): The stable system prompt.

    Returns:
        list[dict]: A single text block marked for ephemeral caching.
    """
    return [
        {
            "type": "text",
            "text": prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]
