"""What an operator says about an incident they handled.

Each open question is paired with a 1-5 rating. The text says why; the rating
is what lets a report say "plan accuracy for floods fell this week", which free
text alone cannot.
"""

from __future__ import annotations

import functools
import os
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[2]

Rating = Field(default=None, ge=1, le=5)
Comment = Field(default=None, max_length=4000)


class OperatorFeedback(BaseModel):
    """The handled-event survey.

    `verdict` is the ground truth the rest of the system never otherwise gets:
    whether the incident was real, a false report, or a second incident for
    something already being handled (a deduplication miss, which is a different
    bug from a false report).
    """

    verdict: Literal["real", "false_report", "duplicate"]
    plan_rating: int | None = Rating
    plan_comment: str | None = Comment
    details_rating: int | None = Rating
    details_comment: str | None = Comment
    missing_information: str | None = Comment


@functools.cache
def code_version() -> str | None:
    """The commit this backend is running, or None when it cannot be told.

    ECOGUARD_CODE_VERSION first, because the container image has no .git; set it
    at build or deploy time. Falls back to asking git, which works for a backend
    run from a checkout.
    """
    if version := os.getenv("ECOGUARD_CODE_VERSION"):
        return version.strip()
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None
