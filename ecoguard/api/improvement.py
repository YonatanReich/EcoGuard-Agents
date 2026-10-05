"""Operator feedback about the system, and the improvement agent's reports."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ecoguard.improvement.feedback import code_version

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/improvement", tags=["improvement"])


class GeneralFeedbackRequest(BaseModel):
    """Free text from the dashboard's Feedback button."""

    text: str = Field(min_length=1, max_length=4000)
    submitted_by: str = Field(default="operator", min_length=1, max_length=120)


@router.post("/feedback", status_code=201)
def submit_feedback(body: GeneralFeedbackRequest) -> dict[str, int]:
    """Store general feedback for the next improvement report."""
    from ecoguard.database.repositories.operator_feedback import record_general

    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Feedback is empty")
    try:
        feedback_id = record_general(
            text,
            submitted_by=body.submitted_by.strip(),
            code_version=code_version(),
            at=datetime.now(timezone.utc),
        )
    except Exception as error:
        logger.exception("Unable to store general feedback")
        raise HTTPException(status_code=503, detail="Feedback is unavailable") from error
    return {"id": feedback_id}


@router.get("/reports/latest")
def latest_report() -> dict[str, Any]:
    """The newest report, or `{"report": null}` before the first one is written."""
    from ecoguard.database.repositories.operator_feedback import recent_reports

    try:
        reports = recent_reports(1)
    except Exception as error:
        logger.exception("Unable to read improvement reports")
        raise HTTPException(status_code=503, detail="Reports are unavailable") from error
    return {"report": reports[0] if reports else None}
