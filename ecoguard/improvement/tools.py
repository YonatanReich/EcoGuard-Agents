"""The improvement agent's tools: read the feedback, read the code, read its past.

Every tool is read-only. The agent investigates and reports; it never changes
the system it is reporting on.

Code access is confined to the repository and to source and documentation file
types, which keeps `.env`, Telegram session files and the virtualenv out of
reach whatever path the model asks for. Every result is capped, because each
one is re-sent on every later turn of the conversation.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from ecoguard.database.repositories import operator_feedback as store
from ecoguard.improvement.feedback import REPO_ROOT

MAX_RESULT_CHARS = 8000
MAX_FILE_LINES = 250
MAX_SEARCH_HITS = 60
MAX_SEARCH_FILE_BYTES = 300_000

READABLE_SUFFIXES = frozenset({
    ".py", ".ts", ".tsx", ".md", ".css", ".sql", ".json",
    ".ini", ".toml", ".txt", ".yml", ".yaml", ".html",
})
SKIPPED_DIRS = frozenset({
    ".git", "venv", ".venv", "node_modules", "dist", "__pycache__", ".vite",
})


class ToolError(Exception):
    """A bad request from the model. Sent back to it as an error result."""


# ===== Feedback =============================================================

def _overview(row: dict[str, Any]) -> dict[str, Any]:
    """One feedback row in the few fields needed to decide whether to dig in."""
    if row["kind"] == "general":
        return {
            "feedback_id": row["id"],
            "kind": "general",
            "submitted_at": row["submitted_at"],
            "code_version": row["code_version"],
            "text": (row["feedback"] or {}).get("text"),
        }
    snapshot = row["snapshot"]
    incident = snapshot.get("incident") or {}
    event = snapshot.get("event") or {}
    processing = snapshot.get("processing") or {}
    first_seen = incident.get("first_seen_at")
    minutes_open = None
    if first_seen:
        minutes_open = round(
            (row["submitted_at"] - datetime.fromisoformat(first_seen)).total_seconds() / 60
        )
    return {
        "feedback_id": row["id"],
        "kind": "handled",
        "incident_id": row["incident_id"],
        "hazard": incident.get("primary_hazard"),
        "title": event.get("title"),
        "handled_at": row["submitted_at"],
        "minutes_open": minutes_open,
        "signal_count": incident.get("signal_count"),
        "operator_confirmed": incident.get("confirmed_at") is not None,
        "planner_status": processing.get("planner_status"),
        "code_version": row["code_version"],
        "survey": row["feedback"] or "skipped",
    }


SECTIONS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "event": lambda snapshot: snapshot.get("event"),
    "evidence": lambda snapshot: (snapshot.get("incident") or {}).get("signals"),
    "incident": lambda snapshot: {
        key: value
        for key, value in (snapshot.get("incident") or {}).items()
        if key != "signals"
    },
    "processing": lambda snapshot: snapshot.get("processing"),
}


class Toolbox:
    """The tools for one agent run, bound to that run's feedback window."""

    def __init__(self, window: list[dict[str, Any]]) -> None:
        self.window = window

    def list_feedback(self) -> list[dict[str, Any]]:
        return [_overview(row) for row in self.window]

    def get_feedback(self, feedback_id: int, section: str) -> Any:
        if section not in SECTIONS:
            raise ToolError(f"section must be one of {sorted(SECTIONS)}")
        row = store.feedback_by_id(int(feedback_id))
        if row is None:
            raise ToolError(f"no feedback row {feedback_id}")
        if row["kind"] == "general":
            raise ToolError("general feedback has no snapshot; list_feedback shows its text")
        return SECTIONS[section](row["snapshot"])

    def feedback_trends(self, days: int = 30) -> list[dict[str, Any]]:
        return store.feedback_trends(max(1, min(int(days), 90)))

    def previous_reports(self, limit: int = 3) -> list[dict[str, Any]]:
        return [
            {
                "report_id": report["id"],
                "created_at": report["created_at"],
                "window_end": report["window_end"],
                "feedback_count": report["feedback_count"],
                "report": report["report"],
            }
            for report in store.recent_reports(max(1, min(int(limit), 5)))
        ]

    # ===== Code =============================================================

    def list_files(self, directory: str = ".") -> list[str]:
        base = _resolve(directory, must_be_file=False)
        entries = []
        for child in sorted(base.iterdir()):
            if child.is_dir() and child.name not in SKIPPED_DIRS:
                entries.append(f"{_relative(child)}/")
            elif child.is_file() and child.suffix in READABLE_SUFFIXES:
                entries.append(_relative(child))
        return entries[:200]

    def read_file(self, path: str, start_line: int = 1, end_line: int | None = None) -> str:
        file = _resolve(path, must_be_file=True)
        lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, int(start_line))
        end = min(len(lines), int(end_line) if end_line else start + MAX_FILE_LINES - 1)
        end = min(end, start + MAX_FILE_LINES - 1)
        body = "\n".join(f"{number}: {lines[number - 1]}" for number in range(start, end + 1))
        return f"{_relative(file)} lines {start}-{end} of {len(lines)}\n{body}"

    def search_code(self, pattern: str, directory: str = "ecoguard") -> list[str]:
        try:
            regex = re.compile(pattern)
        except re.error as error:
            raise ToolError(f"invalid regex: {error}") from None
        hits = []
        for file in _walk(_resolve(directory, must_be_file=False)):
            if file.stat().st_size > MAX_SEARCH_FILE_BYTES:
                continue
            text = file.read_text(encoding="utf-8", errors="replace")
            for number, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    hits.append(f"{_relative(file)}:{number}: {line.strip()[:200]}")
                    if len(hits) >= MAX_SEARCH_HITS:
                        return hits + ["[more matches not shown; narrow the pattern]"]
        return hits

    def git_log(self, days: int = 14, path: str | None = None) -> str:
        command = [
            "git", "log", f"--since={max(1, min(int(days), 90))} days ago",
            "--date=short", "--format=%h %ad %an %s",
        ]
        if path:
            command += ["--", _relative(_resolve(path, must_be_file=False))]
        try:
            result = subprocess.run(
                command, cwd=REPO_ROOT, capture_output=True, text=True, timeout=15, check=True,
            )
        except (OSError, subprocess.SubprocessError):
            raise ToolError("git history is not available on this host") from None
        lines = result.stdout.splitlines()
        return "\n".join(lines[:100]) or "no commits in that period"

    def run(self, name: str, arguments: dict[str, Any]) -> str:
        """Execute one tool call and render its result as text for the model."""
        method = getattr(self, name, None) if name in TOOL_NAMES else None
        if method is None:
            raise ToolError(f"unknown tool {name}")
        try:
            result = method(**arguments)
        except TypeError as error:
            raise ToolError(f"bad arguments: {error}") from None
        rendered = result if isinstance(result, str) else json.dumps(
            result, default=str, ensure_ascii=False
        )
        if len(rendered) > MAX_RESULT_CHARS:
            cut = len(rendered) - MAX_RESULT_CHARS
            rendered = rendered[:MAX_RESULT_CHARS] + f"\n[truncated {cut} characters]"
        return rendered


def _resolve(path: str, *, must_be_file: bool) -> Path:
    """A repository path the agent may read, or ToolError."""
    resolved = (REPO_ROOT / path).resolve()
    if not resolved.is_relative_to(REPO_ROOT):
        raise ToolError("path is outside the repository")
    if SKIPPED_DIRS.intersection(resolved.relative_to(REPO_ROOT).parts):
        raise ToolError("that directory is not readable")
    if must_be_file:
        if not resolved.is_file():
            raise ToolError(f"no such file: {path}")
        if resolved.suffix not in READABLE_SUFFIXES:
            raise ToolError("only source and documentation files are readable")
    elif not resolved.is_dir():
        raise ToolError(f"no such directory: {path}")
    return resolved


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _walk(directory: Path):
    """Readable files under `directory`, skipping vendored and generated trees."""
    for child in sorted(directory.iterdir()):
        if child.is_dir():
            if child.name not in SKIPPED_DIRS:
                yield from _walk(child)
        elif child.suffix in READABLE_SUFFIXES:
            yield child


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


TOOLS = [
    _tool(
        "list_feedback",
        "Everything operators submitted in this report's window. 'handled' rows are "
        "incidents they finished with: hazard, title, how long it was open, whether an "
        "operator confirmed it, the planner's status, the commit the backend was running, "
        "and the survey answers ('skipped' when they closed the survey without answering). "
        "'general' rows are free-text feedback about the system as a whole. Start here.",
        {}, [],
    ),
    _tool(
        "get_feedback",
        "One section of the snapshot frozen when an incident was handled. 'event' is what "
        "the dashboard showed, including the assessment and response plan; 'evidence' is "
        "the signals the incident was built from (detections, readings, text reports); "
        "'incident' is the coordinator's record; 'processing' is pipeline status and "
        "failures. Works for any feedback id, not only this window's.",
        {
            "feedback_id": {"type": "integer"},
            "section": {"type": "string", "enum": sorted(SECTIONS)},
        },
        ["feedback_id", "section"],
    ),
    _tool(
        "feedback_trends",
        "Counted, not estimated: per day and hazard, how many incidents were handled, "
        "how many surveys were skipped, the verdict counts, average plan and details "
        "ratings, and average minutes from first detection to handling.",
        {"days": {"type": "integer", "minimum": 1, "maximum": 90}},
        [],
    ),
    _tool(
        "previous_reports",
        "Your own earlier reports, newest first. Use them to say whether earlier "
        "suggestions were acted on and whether the problems they named have changed.",
        {"limit": {"type": "integer", "minimum": 1, "maximum": 5}},
        [],
    ),
    _tool(
        "list_files",
        "The source and documentation files and subdirectories in one repository "
        "directory. Paths are relative to the repository root.",
        {"directory": {"type": "string"}},
        [],
    ),
    _tool(
        "read_file",
        f"Numbered lines from one repository file, at most {MAX_FILE_LINES} per call.",
        {
            "path": {"type": "string"},
            "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1},
        },
        ["path"],
    ),
    _tool(
        "search_code",
        "Search repository files with a Python regular expression. Returns path:line: text.",
        {"pattern": {"type": "string"}, "directory": {"type": "string"}},
        ["pattern"],
    ),
    _tool(
        "git_log",
        "Recent commits (hash, date, author, subject), optionally for one path. Use it to "
        "connect a change in the feedback to a change in the code.",
        {"days": {"type": "integer", "minimum": 1, "maximum": 90}, "path": {"type": "string"}},
        [],
    ),
]

TOOL_NAMES = frozenset(tool["name"] for tool in TOOLS)
