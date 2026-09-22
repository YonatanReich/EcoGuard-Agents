"""
Claude LLM Service

Responsible for the one thing the agents cannot do offline: running a structured
Claude call and returning a schema-validated result. It knows nothing about
fires — it takes system blocks, a user message and a Pydantic model, and returns
an instance of that model or raises a sanitized error.

Failure handling follows the newer house convention (see
ecoguard/collection/fire/firms/client.py): this is a leaf provider client, so it RAISES a typed
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
    ecoguard/shared/geocoding.py. Tests pass a fake exposing
    ``.messages.parse(**kwargs)``; ``anthropic.Anthropic`` is never constructed
    in the test suite.

Consumed by: ecoguard.analyzers.emergency.fire.risk_analysis_agent, ecoguard.response_planner.fire.planning_agent
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import deque
from urllib.parse import urlparse

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

load_dotenv()

# Exact model id, no date suffix. Sonnet 5 is an explicit project choice; if
# grounding quality disappoints, raise `effort` before changing model.
DEFAULT_MODEL = "claude-sonnet-5"

# Models that reject `thinking` and `output_config.effort` outright. Listed
# rather than probed because the failure is a 400 at request time, and
# discovering it by catching one would mean every cheap call pays a round trip
# to learn what is already known.
MODELS_WITHOUT_REASONING_CONTROLS = frozenset({
    "claude-haiku-4-5-20251001",
})

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
        "insufficient credit",
        "provider error",
    }
)


class ClaudeProviderError(RuntimeError):
    """Credential-safe Claude failure carrying a provider-level error category."""


# --------------------------------------------------------------------------
# Spend guard
# --------------------------------------------------------------------------
#
# The last line of defence, and the one this system was missing.
#
# Every caller here is individually careful — the classifier batches, the
# dispatcher has a freshness gate, the planners cap their attempts — and none
# of that stopped 209 dispatch attempts against 25 incidents in a few hours,
# because no single component could see the total. A budget only works where
# every call passes, which is here.
#
# It counts calls rather than tokens deliberately: tokens are only known after
# the response, so a token budget cannot refuse the request that breaks it. A
# call ceiling refuses before spending anything, and a runaway loop is always a
# call-rate problem first.
#
# This is per process and in memory, which is the right scope: a second process
# is a second scheduler, and the fix for that is not to run one (see the
# Dockerfile). Keep the ceiling well above steady-state so it never trips in
# normal operation — it is a circuit breaker, not a throttle.
CALL_BUDGET_PER_HOUR = int(os.getenv("ECOGUARD_CLAUDE_CALLS_PER_HOUR", "120"))
CALL_BUDGET_WINDOW_SECONDS = 3600.0


class CallBudget:
    """A rolling-window ceiling on Claude calls for this process."""

    def __init__(self, limit: int, window_seconds: float) -> None:
        self._limit = limit
        self._window = window_seconds
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()
        self._blocked = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def claim(self) -> bool:
        """Take a slot, or report that the window is full. Never blocks."""
        if self._limit <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            cutoff = now - self._window
            while self._calls and self._calls[0] < cutoff:
                self._calls.popleft()
            if len(self._calls) >= self._limit:
                self._blocked += 1
                if self._blocked == 1 or self._blocked % 25 == 0:
                    logging.error(
                        "Claude call budget exhausted: %s calls in the last hour "
                        "(limit %s). %s call(s) refused. Something is looping — "
                        "check event_projections.attempt_count for retry storms. "
                        "Raise ECOGUARD_CLAUDE_CALLS_PER_HOUR only once you know why.",
                        len(self._calls), self._limit, self._blocked,
                    )
                return False
            self._calls.append(now)
            return True

    def record_usage(self, usage: dict | None) -> None:
        """Accumulate what a completed call actually cost."""
        if not usage:
            return
        with self._lock:
            # Cache reads and writes are input tokens too, billed at different
            # rates. Summed here so the running total is honest about volume;
            # the per-call log line below keeps them separable.
            for key in (
                "input_tokens",
                "cache_creation_input_tokens",
                "cache_read_input_tokens",
            ):
                value = usage.get(key)
                if isinstance(value, int):
                    self.input_tokens += value
            value = usage.get("output_tokens")
            if isinstance(value, int):
                self.output_tokens += value

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "calls_in_window": len(self._calls),
                "limit": self._limit,
                "refused": self._blocked,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
            }


call_budget = CallBudget(CALL_BUDGET_PER_HOUR, CALL_BUDGET_WINDOW_SECONDS)


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

        # Refused before the request is built, so a loop costs nothing. Reported
        # as "rate limited" because that is what it is from a caller's point of
        # view, and every caller already degrades gracefully on it.
        if not call_budget.claim():
            raise ClaudeProviderError("rate limited") from None

        messages: list[dict] = [{"role": "user", "content": user_text}]

        # Only present when tools were supplied, so the legacy call shape is
        # preserved exactly.
        extra: dict = {"tools": tools} if tools else {}

        response = None

        # Adaptive thinking and the effort control are Claude 5 family
        # features. Sending them to Haiku 4.5 is a 400, not a degradation —
        # "This model does not support the effort parameter" — so a caller who
        # reaches for the cheap model for a cheap task gets an opaque "invalid
        # request" instead of a classification. Omitted rather than translated:
        # there is no Haiku equivalent to map them onto.
        reasoning = (
            {}
            if self.model in MODELS_WITHOUT_REASONING_CONTROLS
            else {
                "thinking": {"type": "adaptive"},
                "output_config": {"effort": self.effort},
            }
        )

        for _ in range(max_continuations + 1):
            try:
                response = self.client.messages.parse(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    system=system_blocks,
                    messages=messages,
                    output_format=output_format,
                    **reasoning,
                    **extra,
                )
            except Exception as error:
                self.log_validation_detail(error)
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
        call_budget.record_usage(self.last_usage)

        # Input and output token counts belong in this line, not just the cache
        # counter. Without them a pipeline burning the quota looks exactly like
        # one doing its job, and the only place the difference shows up is the
        # invoice — which is how 19.6M input tokens accumulated before anyone
        # could say which lane produced them. `totals` is cumulative for this
        # process, so one grep over a boot's worth of logs apportions the spend.
        usage = self.last_usage or {}
        logging.info(
            "Claude call complete: model=%s effort=%s in=%s out=%s "
            "cache_write=%s cache_read=%s searches=%s totals=%s",
            self.model,
            self.effort,
            usage.get("input_tokens"),
            usage.get("output_tokens"),
            usage.get("cache_creation_input_tokens"),
            usage.get("cache_read_input_tokens"),
            self.last_web_searches,
            call_budget.snapshot(),
        )

        return parsed

    @staticmethod
    def log_validation_detail(error: Exception) -> None:
        """
        Log which schema fields a rejected response failed on.

        Schema violations are reported to callers as the single opaque category
        ``"malformed response"``, which is right for a caller but useless for
        diagnosis — a schema that intermittently rejects good answers looks
        identical to a provider fault. This logs the failing field names and
        error types so the cause is findable.

        Only field paths and pydantic's own error codes are logged, never the
        rejected values. The values came from the model's reading of the prompt
        and may carry event data, so they stay out of the log for the same
        reason the cause chain is suppressed.

        Args:
            error (Exception): The exception raised by the parse call.
        """
        if not isinstance(error, ValidationError):
            return

        failures = [
            f"{'.'.join(str(part) for part in item['loc'])}={item['type']}"
            for item in error.errors()
        ]

        logging.warning(
            "Structured output rejected by the schema on %s field(s): %s",
            len(failures),
            ", ".join(failures),
        )

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

        # An exhausted balance arrives as a 400, indistinguishable from a bad
        # request unless the body is read. It is the one failure an operator
        # can fix in a minute and the one that silently kills every model lane
        # at once, so it gets its own word. The message text carries no
        # credential material.
        if isinstance(error, anthropic.BadRequestError) and "credit balance" in str(
            getattr(error, "message", "") or error
        ):
            return "insufficient credit"

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


def probe_model_reachability(timeout_seconds: float = 20.0) -> str:
    """One four-token call, so a deploy log says outright whether the key works.

    Every model-backed lane degrades silently — the classifier falls back to
    keywords, planners report planner_status=failed with no reason projected —
    so a dead key on a new host looks exactly like a quiet day. Called once at
    startup; never raises.

    Returns:
        str: "ok", or a member of CLAUDE_ERROR_KINDS naming what failed.
    """
    service = ClaudeLLMService(
        model="claude-haiku-4-5-20251001",
        max_tokens=4,
        timeout_seconds=timeout_seconds,
        max_retries=0,
    )
    if not service.available:
        logging.warning("Claude reachable: no (missing credentials)")
        return "missing credentials"
    try:
        service.client.messages.create(
            model=service.model,
            max_tokens=4,
            messages=[{"role": "user", "content": "ping"}],
        )
    except Exception as error:
        kind = service.sanitize_error(error)
        logging.warning("Claude reachable: no (%s)", kind)
        return kind
    logging.info("Claude reachable: yes")
    return "ok"
