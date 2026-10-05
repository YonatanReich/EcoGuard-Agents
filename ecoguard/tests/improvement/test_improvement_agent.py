"""The improvement agent's loop, its tool sandbox, and its counted numbers.

Touches no database and no model: the loop runs against a scripted fake client,
and the only tool it is scripted to call reads the in-memory window.
"""

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from ecoguard.improvement import agent
from ecoguard.improvement.agent import ImprovementReport, investigate, tally
from ecoguard.improvement.feedback import OperatorFeedback
from ecoguard.improvement.tools import Toolbox, ToolError
from ecoguard.shared.llm import ClaudeLLMService

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)

REPORT = {
    "summary": "One false fire report from an unofficial channel.",
    "problems": [{
        "title": "Unofficial Telegram report opened a fire incident",
        "detail": "The only evidence was one text report.",
        "feedback_ids": [1],
        "code_refs": ["ecoguard/detectors/text/run.py:40"],
    }],
    "strengths": [],
    "trends": [],
    "suggestions": [],
    "follow_up": [],
}


def row(feedback_id, hazard, feedback):
    """One operator_feedback row as the repository returns it."""
    return {
        "id": feedback_id,
        "kind": "handled",
        "incident_id": f"INC-20261005-{feedback_id:04d}",
        "submitted_at": NOW,
        "submitted_by": "operator",
        "code_version": "abc1234",
        "feedback": feedback,
        "snapshot": {
            "incident": {
                "primary_hazard": hazard,
                "first_seen_at": "2026-10-05 08:30:00+00:00",
                "signal_count": 1,
                "confirmed_at": None,
                "signals": [],
            },
            "event": {"title": f"{hazard} near Haifa"},
            "processing": {"planner_status": "success"},
        },
    }


WINDOW = [
    row(1, "fire", {"verdict": "false_report", "plan_rating": 2, "details_rating": 1}),
    row(2, "flood", {"verdict": "real", "plan_rating": 4, "details_rating": None}),
    row(3, "fire", None),
    {
        "id": 4,
        "kind": "general",
        "incident_id": None,
        "submitted_at": NOW,
        "submitted_by": "operator",
        "code_version": "abc1234",
        "feedback": {"text": "Cards are too crowded to scan during an emergency."},
        "snapshot": None,
    },
]


def tool_call(name, arguments, call_id="call-1"):
    return SimpleNamespace(type="tool_use", id=call_id, name=name, input=arguments)


def reply(stop_reason, *content):
    return SimpleNamespace(stop_reason=stop_reason, content=list(content), usage=None)


class ScriptedClient:
    """Answers each create() with the next scripted reply, and records the requests."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        self.messages = self

    def create(self, **request):
        self.requests.append({**request, "messages": list(request["messages"])})
        return self.replies.pop(0)


def service(client):
    return ClaudeLLMService(api_key="test", client=client)


def test_agent_investigates_with_tools_then_answers_with_the_report():
    client = ScriptedClient([
        reply("tool_use", tool_call("list_feedback", {})),
        reply("end_turn", SimpleNamespace(type="text", text=json.dumps(REPORT))),
    ])

    report = investigate(WINDOW, window_start=None, window_end=NOW, service=service(client))

    assert report == ImprovementReport.model_validate(REPORT)
    # The tool's result went back to the model, built from the window.
    tool_results = client.requests[1]["messages"][-1]["content"]
    assert tool_results[0]["is_error"] is False
    listed = json.loads(tool_results[0]["content"])
    assert [item["feedback_id"] for item in listed] == [1, 2, 3, 4]
    assert listed[0]["minutes_open"] == 30
    assert listed[2]["survey"] == "skipped"
    assert listed[3] == {
        "feedback_id": 4,
        "kind": "general",
        "submitted_at": str(NOW),
        "code_version": "abc1234",
        "text": "Cards are too crowded to scan during an emergency.",
    }


def test_last_turn_turns_tools_off_so_the_report_always_arrives(monkeypatch):
    monkeypatch.setattr(agent, "MAX_TURNS", 3)
    client = ScriptedClient([
        reply("tool_use", tool_call("list_feedback", {})),
        reply("tool_use", tool_call("list_feedback", {})),
        reply("end_turn", SimpleNamespace(type="text", text=json.dumps(REPORT))),
    ])

    investigate(WINDOW, window_start=None, window_end=NOW, service=service(client))

    assert [request["tool_choice"] for request in client.requests] == [
        {"type": "auto"}, {"type": "auto"}, {"type": "none"},
    ]


def test_a_bad_tool_call_goes_back_to_the_model_as_an_error():
    client = ScriptedClient([
        reply("tool_use", tool_call("read_file", {"path": ".env"})),
        reply("end_turn", SimpleNamespace(type="text", text=json.dumps(REPORT))),
    ])

    investigate(WINDOW, window_start=None, window_end=NOW, service=service(client))

    result = client.requests[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True


@pytest.mark.parametrize("path", [".env", "../outside.py", "venv/pyvenv.cfg", ".git/config"])
def test_code_tools_cannot_reach_secrets_or_leave_the_repository(path):
    with pytest.raises(ToolError):
        Toolbox([]).read_file(path)


def test_code_tools_read_source():
    text = Toolbox([]).read_file("ecoguard/improvement/README.md", 1, 1)
    assert text.splitlines()[1] == "1: # Improvement"


def test_report_schema_is_strict_everywhere_structured_outputs_requires_it():
    schema = ImprovementReport.model_json_schema()
    objects = [schema, *schema["$defs"].values()]
    assert all(entry["additionalProperties"] is False for entry in objects)


def test_tally_counts_rather_than_trusting_the_model():
    assert tally(WINDOW) == {
        "handled": 3,
        "surveys_answered": 2,
        "general_feedback": 1,
        "verdicts": {"false_report": 1, "real": 1},
        "by_hazard": {"fire": 2, "flood": 1},
        "average_plan_rating": 3.0,
        "average_details_rating": 1.0,
    }


def test_survey_ratings_are_one_to_five():
    with pytest.raises(ValueError):
        OperatorFeedback(verdict="real", plan_rating=6)
