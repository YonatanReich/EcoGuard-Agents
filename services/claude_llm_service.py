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
from urllib.parse import urlparse

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

# How many times a server-tool turn paused at the API's 10-iteration ceiling may
# be resumed before we give up. Three is generous: a bounded lookup that has not
# finished after four attempts is not going to.
DEFAULT_MAX_CONTINUATIONS = 3

# Web search, used by the risk agent to fill gaps the collection layer could not.
#
# The allowlist is a safety control, not an optimisation. This system produces
# emergency response plans, and a population figure taken from a forum post would
# carry exactly the same visual weight in the output as one from the Central
# Bureau of Statistics. Restricting at the API means the model cannot read an
# unlisted source in the first place.
WEB_SEARCH_ALLOWED_DOMAINS = [
    "cbs.gov.il",          # Central Bureau of Statistics — settlement populations
    "gov.il",              # government portals
    "oref.org.il",         # Home Front Command — civil defence guidance
    "openstreetmap.org",   # mapping, consistent with our own geospatial source
    "wikipedia.org",       # settlement basics where nothing official exists
]

DEFAULT_MAX_SEARCHES = 3

# The dynamic-filtering variant, supported on Sonnet 5. It runs its own code
# execution internally to filter results before they reach the context window,
# which is why the standalone code_execution tool must NOT also be declared —
# a second execution environment confuses the model.
WEB_SEARCH_TOOL_TYPE = "web_search_20260209"

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

        # What the most recent request actually did, counted from the response
        # blocks rather than taken from the model's account of itself.
        # last_web_searches is the number to report to a user; the other
        # includes the code execution that dynamic filtering runs internally.
        self.last_server_tool_uses: int = 0
        self.last_web_searches: int = 0

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
        tools: list[dict] | None = None,
        max_continuations: int = DEFAULT_MAX_CONTINUATIONS,
    ) -> BaseModel:
        """
        Run one structured Claude call and return the validated result.

        Sonnet 5 constraints honoured here: ``thinking`` is adaptive (the only
        on-mode; ``budget_tokens`` is rejected with a 400), and no sampling
        parameters are sent — ``temperature``/``top_p``/``top_k`` were removed
        from the SDK in 1.x and are rejected by the model besides.

        Server-side tools (see build_web_search_tool) run inside the API's own
        sampling loop, so there is no client-side tool loop to write. That loop
        does have a ceiling, though: at 10 iterations the API returns
        ``stop_reason: "pause_turn"`` with the work unfinished. Resuming means
        re-sending with the assistant turn appended and NO extra user message —
        the server sees the trailing server_tool_use block and picks up where it
        left off. Without that, a paused turn would surface here as a missing
        parsed output and be misreported as a malformed response.

        Args:
            system_blocks (list[dict]): System content blocks. The stable prefix
                should carry ``cache_control`` — see build_system_blocks.
            user_text (str): The per-request message. Retrieved protocol
                excerpts and event evidence belong here, AFTER the cached
                prefix, so caching is not invalidated on every call.
            output_format (type[BaseModel]): Schema the response must satisfy.
            tools (list[dict] | None): Tool definitions. Omitted from the
                request entirely when None, so a call without tools is byte
                identical to one made before tools existed and the prompt cache
                is unaffected.
            max_continuations (int): How many times a paused turn may be
                resumed before giving up.

        Returns:
            BaseModel: A validated instance of output_format.

        Raises:
            ClaudeProviderError: With a message drawn from CLAUDE_ERROR_KINDS.
                The cause chain is suppressed, so no prompt content or
                credential material reaches the caller.
        """
        if self.client is None:
            raise ClaudeProviderError("missing credentials") from None

        messages: list[dict] = [{"role": "user", "content": user_text}]

        # Only present when tools were supplied, so the legacy call shape is
        # preserved exactly.
        extra: dict = {"tools": tools} if tools else {}

        response = None

        for _ in range(max_continuations + 1):
            try:
                response = self.client.messages.parse(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    system=system_blocks,
                    messages=messages,
                    thinking={"type": "adaptive"},
                    output_config={"effort": self.effort},
                    output_format=output_format,
                    **extra,
                )
            except Exception as error:
                raise ClaudeProviderError(self.sanitize_error(error)) from None

            if getattr(response, "stop_reason", None) != "pause_turn":
                break

            # Append the paused assistant turn and go round again. Adding a
            # "continue" user message here would break the server's resume
            # detection, so deliberately do not.
            messages = messages + [
                {"role": "assistant", "content": response.content}
            ]
        else:
            # Ran out of continuations with the turn still paused.
            raise ClaudeProviderError("provider error") from None

        # A safety refusal returns HTTP 200 with no usable output. Report it as
        # malformed rather than letting a None reach a caller expecting a model.
        if getattr(response, "stop_reason", None) == "refusal":
            raise ClaudeProviderError("malformed response") from None

        parsed = response.parsed_output

        # A truncated response can also yield no parsed output at all.
        if not isinstance(parsed, output_format):
            raise ClaudeProviderError("malformed response") from None

        self.last_usage = self.read_usage(response)
        self.last_server_tool_uses = count_server_tool_uses(response)
        self.last_web_searches = count_server_tool_uses(response, name="web_search")

        logging.info(
            "Claude call complete: model=%s effort=%s cache_read=%s searches=%s",
            self.model,
            self.effort,
            (self.last_usage or {}).get("cache_read_input_tokens"),
            self.last_web_searches,
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


def build_web_search_tool(
    *,
    max_uses: int = DEFAULT_MAX_SEARCHES,
    allowed_domains: list[str] | None = None,
) -> dict:
    """
    Build the server-side web search tool definition.

    Args:
        max_uses (int): Hard ceiling on searches per request. Bounds both cost
            and latency on a pipeline that is already slow.
        allowed_domains (list[str] | None): Hosts the model may read. Defaults
            to WEB_SEARCH_ALLOWED_DOMAINS.

    Returns:
        dict: A tool definition for the ``tools`` list.
    """
    return {
        "type": WEB_SEARCH_TOOL_TYPE,
        "name": "web_search",
        "max_uses": max_uses,
        "allowed_domains": list(
            WEB_SEARCH_ALLOWED_DOMAINS if allowed_domains is None else allowed_domains
        ),
    }


def count_server_tool_uses(response: object, *, name: str | None = None) -> int:
    """
    Count server-side tool calls in a response, optionally for one tool.

    Read from the response blocks rather than asked of the model, for the same
    reason citations are verified rather than trusted: a self-report of what a
    model did is not evidence of what it did.

    **Pass a name if you are reporting a search count.** The
    ``web_search_20260209`` variant performs dynamic filtering by running code
    execution internally, and those calls appear as ``server_tool_use`` blocks
    too. One observed lookup produced one ``web_search`` block alongside three
    ``code_execution`` blocks, so an unfiltered count reported four searches
    where one had happened.

    Args:
        response (object): The SDK response object.
        name (str | None): Tool name to count, e.g. ``"web_search"``. None
            counts every server tool call.

    Returns:
        int: Matching block count. Zero when the response has no readable
            content.
    """
    content = getattr(response, "content", None)

    if not isinstance(content, (list, tuple)):
        return 0

    return sum(
        1
        for block in content
        if getattr(block, "type", None) == "server_tool_use"
        and (name is None or getattr(block, "name", None) == name)
    )


def host_is_allowed(url: str, allowed_domains: list[str]) -> bool:
    """
    Whether a URL's host is the allowlist or a subdomain of it.

    Args:
        url (str): URL to check.
        allowed_domains (list[str]): Permitted registrable domains.

    Returns:
        bool: True when the host matches or is a subdomain of an entry.
    """
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False

    if not host:
        return False

    # Suffix match on a dot boundary, so "cbs.gov.il" admits "www.cbs.gov.il"
    # but "evil-gov.il" does not match "gov.il".
    return any(
        host == domain or host.endswith(f".{domain}")
        for domain in (d.lower() for d in allowed_domains)
    )


def verify_web_findings(
    findings: list[dict], allowed_domains: list[str] | None = None
) -> tuple[list[dict], int]:
    """
    Drop any web finding whose source is not on the allowlist.

    The API already restricts which hosts can be *read*, but the model is the
    one that reports what it found, and a fabricated or misattributed URL must
    not reach an operator. Same shape and same reasoning as verify_citations:
    check the claim rather than trusting it.

    Args:
        findings (list[dict]): Model-reported findings, each with a source_url.
        allowed_domains (list[str] | None): Defaults to the module allowlist.

    Returns:
        tuple[list[dict], int]: Surviving findings, and the number dropped.
    """
    domains = WEB_SEARCH_ALLOWED_DOMAINS if allowed_domains is None else allowed_domains

    verified: list[dict] = []
    dropped = 0

    for finding in findings or []:
        if not isinstance(finding, dict):
            dropped += 1
            continue

        if host_is_allowed(finding.get("source_url", ""), domains):
            verified.append(finding)
        else:
            dropped += 1

    return verified, dropped


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
