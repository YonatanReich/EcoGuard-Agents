"""Pydantic transport schemas for the standalone fire-risk endpoint."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class FireRiskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    latitude: float = Field(ge=29.45, le=33.35)
    longitude: float = Field(ge=34.26, le=35.90)
    current_features: dict[str, float] | None = None


class CurrentRiskResponse(BaseModel):
    status: Literal["available", "unavailable", "error"]
    score: float | None
    level: Literal["low", "medium", "high"] | None
    semantics: Literal["estimated_fire_risk"]
    main_factors: list[dict[str, Any]]
    reason: str | None = None
    missing_runtime_inputs: list[str] = Field(default_factory=list)
    model_version: str | None = None


class FireRiskResponse(BaseModel):
    status: Literal["available", "unavailable", "error"]
    location: dict[str, float]
    current_risk: CurrentRiskResponse
    actual_fire_detection: dict[str, Any]


class NationalRiskCell(BaseModel):
    cell_id: str
    latitude: float
    longitude: float
    risk_score: float
    risk_level: Literal["low", "medium", "high"]
    evaluation_time: str


class NationalUnavailableCell(BaseModel):
    cell_id: str
    latitude: float
    longitude: float
    reason: str


class NationalRiskScanSummary(BaseModel):
    total_active_cells: int
    evaluated_cells: int
    unavailable_cells: int
    risk_level_counts: dict[str, int]
    unavailable_reason_counts: dict[str, int]
    highest_risk_cells: list[NationalRiskCell]


class NationalRiskScanResponse(BaseModel):
    status: Literal["success", "partial", "unavailable"]
    evaluation_time: str
    summary: NationalRiskScanSummary
    cells: list[NationalRiskCell]
    unavailable_cells: list[NationalUnavailableCell]
    semantics: Literal["estimated_fire_risk_not_actual_fire_detection"]
    refresh_metadata: dict[str, Any] | None = None
