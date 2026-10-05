"""The improvement agent: reads what operators said about handled incidents,
investigates why, and writes a report for the developers.

Once a day it takes every feedback row it has not reported on, and decides for
itself what to look at: which incidents to open, which evidence and plans to
read, which code to trace a complaint into, and which commits might explain a
change. It reads its own earlier reports, so it can say whether last time's
suggestions were acted on and whether that moved the numbers.

It only reads. Its output is a report stored in `improvement_reports` and shown
on the System page; nothing it concludes changes the running system.

Cost is bounded three ways: it runs at most once a day and only when there is
new feedback, every tool result is capped (tools.MAX_RESULT_CHARS), and the
conversation has a fixed number of turns, the last of which must be the report.
The growing history is prompt-cached, so each turn pays full price only for
what is new in it.

Run one by hand with `python -m ecoguard.improvement.agent`.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from ecoguard import pipeline_switch
from ecoguard.database.locks import single_flight
from ecoguard.database.repositories import operator_feedback as store
from ecoguard.improvement.tools import TOOLS, Toolbox, ToolError
from ecoguard.shared.activity import live_actor
from ecoguard.shared.llm import (
    DEFAULT_MODEL,
    ClaudeLLMService,
    ClaudeProviderError,
    call_budget,
)

logger = logging.getLogger(__name__)

EFFORT = "high"
MAX_TOKENS = 16000
MAX_TURNS = 16
# Not 24: the job also runs at every boot, and a deploy at 07:00 after a 09:00
# report would otherwise push the next one to the following morning.
MIN_HOURS_BETWEEN_REPORTS = 20


# ===== The report ===========================================================

class _Strict(BaseModel):
    # additionalProperties: false, which structured outputs requires.
    model_config = ConfigDict(extra="forbid")


class Finding(_Strict):
    title: str
    detail: str
    feedback_ids: list[int]
    code_refs: list[str]


class Suggestion(_Strict):
    title: str
    rationale: str
    priority: Literal["high", "medium", "low"]
    code_refs: list[str]


class FollowUp(_Strict):
    earlier_suggestion: str
    status: Literal["resolved", "improving", "unchanged", "worse", "not_enough_data"]
    detail: str


class ImprovementReport(_Strict):
    summary: str
    problems: list[Finding]
    strengths: list[Finding]
    trends: list[str]
    suggestions: list[Suggestion]
    follow_up: list[FollowUp]


SYSTEM_PROMPT = """\
You are the improvement agent for EcoGuard, a system that detects environmental \
hazards in Israel (fires, floods, earthquakes, air pollution) and gives emergency \
operators an event card with an assessment and a response plan. Detectors raise \
signals, a coordinator merges them into incidents, analysers assess each incident, \
planners write a protocol-grounded plan, and an allocator dispatches units.

When an operator finishes with an incident they mark it handled and may answer a \
survey: whether the incident was real, a false report or a duplicate; a 1-5 \
rating and comment on the response plan; a 1-5 rating and comment on the event \
details; and what information was missing. A snapshot of everything they saw \
was frozen at that moment. Operators can also send general free-text feedback \
about the system at any time, not tied to an incident.

Your job is to tell the developers what is wrong with the system, where it is \
strong, how it is trending, and what to change. Work like an engineer \
investigating a bug report:

- Start with list_feedback and feedback_trends, then previous_reports.
- For anything worth explaining, open the snapshot: compare the evidence with \
the event the operator saw, and the plan with what they said about it.
- Trace each problem into the code (start from ecoguard/README.md and the \
package READMEs) and find where it comes from. Use git_log to tie a change in \
the numbers to a change in the code.
- Follow up every suggestion in your previous reports: was it acted on, and did \
the numbers move?

Rules:
- Every problem and strength cites the feedback ids it rests on. Cite code as \
path:line, and only lines you have read.
- Keep what operators said apart from what you verified. If you could not find \
the cause in the code, say so rather than guessing.
- Volumes are small. Do not call one incident a trend; say how many incidents a \
claim rests on.
- A skipped survey still counts: a hazard whose surveys are mostly skipped is a \
finding about the survey, not about the hazard.
- Suggestions are specific changes a developer could pick up today, ranked by \
how much they would improve what operators see.
- Empty lists are fine. Write nothing you cannot support.

When you have what you need, stop calling tools and answer with the report.\
"""


# ===== Running it ===========================================================

def run(*, force: bool = False) -> int | None:
    """Write a report if one is due. The scheduler's entry point.

    Due means: the pipeline is switched on, no report was written in the last
    MIN_HOURS_BETWEEN_REPORTS hours, and some feedback has arrived since the
    last one. `force` skips the first two checks, for a person asking for a
    report now; with no new feedback there is still nothing to report on.

    Returns:
        int | None: The new report's id, or None when no report was written.
    """
    if not force and not pipeline_switch.is_enabled():
        logger.info("improvement agent: pipeline is paused, skipping")
        return None

    with single_flight("improvement_agent") as acquired:
        if not acquired:
            logger.info("improvement agent: another process is writing a report, skipping")
            return None

        now = datetime.now(timezone.utc)
        previous = store.recent_reports(1)
        last = previous[0] if previous else None
        if (
            not force
            and last is not None
            and now - last["created_at"] < timedelta(hours=MIN_HOURS_BETWEEN_REPORTS)
        ):
            return None

        window_start = last["window_end"] if last else None
        window = store.feedback_between(window_start, now)
        if not window:
            logger.info("improvement agent: no new operator feedback, no report")
            return None

        report = investigate(window, window_start=window_start, window_end=now)
        report_id = store.insert_report(
            window_start=window_start,
            window_end=now,
            feedback_count=len(window),
            model=DEFAULT_MODEL,
            report={"stats": tally(window), **report.model_dump()},
        )
        logger.info(
            "improvement agent: report %s written from %s feedback row(s)",
            report_id, len(window),
        )
        return report_id


@live_actor("improvement_agent")
def investigate(
    window: list[dict[str, Any]],
    *,
    window_start: datetime | None,
    window_end: datetime,
    service: ClaudeLLMService | None = None,
) -> ImprovementReport:
    """The agent loop: let the model call tools until it answers with a report.

    Raises:
        ClaudeProviderError: When the model cannot be reached, refuses, runs out
            of tokens, or answers with something that is not a valid report.
    """
    service = service or ClaudeLLMService(
        model=DEFAULT_MODEL, max_tokens=MAX_TOKENS, effort=EFFORT, timeout_seconds=300.0,
    )
    if not service.available:
        raise ClaudeProviderError("missing credentials")

    toolbox = Toolbox(window)
    since = window_start.isoformat() if window_start else "the first feedback ever recorded"
    messages: list[dict[str, Any]] = [{
        "role": "user",
        "content": (
            f"Report window: {since} to {window_end.isoformat()}. "
            f"{len(window)} feedback row(s) were submitted in it. "
            f"You have {MAX_TURNS} turns."
        ),
    }]

    for turn in range(MAX_TURNS):
        last_turn = turn == MAX_TURNS - 1
        if not call_budget.claim():
            raise ClaudeProviderError("rate limited")
        try:
            response = service.client.messages.create(
                model=service.model,
                max_tokens=service.max_tokens,
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=TOOLS,
                # On the last turn tools are off, so the answer must be the report.
                tool_choice={"type": "none"} if last_turn else {"type": "auto"},
                thinking={"type": "adaptive"},
                output_config={
                    "effort": service.effort,
                    "format": {
                        "type": "json_schema",
                        "schema": ImprovementReport.model_json_schema(),
                    },
                },
                # Caches the whole conversation so far; each turn re-sends it.
                cache_control={"type": "ephemeral"},
            )
        except Exception as error:
            raise ClaudeProviderError(service.sanitize_error(error)) from None
        call_budget.record_usage(service.read_usage(response))

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            results = [
                _tool_result(toolbox, block)
                for block in response.content
                if block.type == "tool_use"
            ]
            if turn + 1 == MAX_TURNS - 1:
                results.append({
                    "type": "text",
                    "text": "That was your last tool turn. Write the report now.",
                })
            messages.append({"role": "user", "content": results})
            continue

        if response.stop_reason != "end_turn":
            logger.warning("improvement agent stopped early: %s", response.stop_reason)
            raise ClaudeProviderError("malformed response")

        text = "".join(block.text for block in response.content if block.type == "text")
        try:
            report = ImprovementReport.model_validate_json(text)
        except ValidationError:
            raise ClaudeProviderError("malformed response") from None
        logger.info(
            "improvement agent finished in %s turn(s); totals=%s",
            turn + 1, call_budget.snapshot(),
        )
        return report

    raise ClaudeProviderError("malformed response")


def _tool_result(toolbox: Toolbox, block: Any) -> dict[str, Any]:
    """Run one tool call. A failure goes back to the model, not up the stack."""
    try:
        content, is_error = toolbox.run(block.name, dict(block.input or {})), False
    except ToolError as error:
        content, is_error = str(error), True
    except Exception:
        logger.exception("improvement agent tool %s failed", block.name)
        content, is_error = "the tool failed; try another approach", True
    return {
        "type": "tool_result",
        "tool_use_id": block.id,
        "content": content,
        "is_error": is_error,
    }


def tally(window: list[dict[str, Any]]) -> dict[str, Any]:
    """The report's numbers, counted here rather than written by the model."""
    handled = [row for row in window if row["kind"] == "handled"]
    surveys = [row["feedback"] for row in handled if row["feedback"]]

    def average(key: str) -> float | None:
        values = [survey[key] for survey in surveys if survey.get(key) is not None]
        return round(mean(values), 2) if values else None

    return {
        "handled": len(handled),
        "surveys_answered": len(surveys),
        "general_feedback": len(window) - len(handled),
        "verdicts": dict(Counter(survey["verdict"] for survey in surveys)),
        "by_hazard": dict(Counter(
            (row["snapshot"].get("incident") or {}).get("primary_hazard", "unknown")
            for row in handled
        )),
        "average_plan_rating": average("plan_rating"),
        "average_details_rating": average("details_rating"),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    print(run(force=True))
