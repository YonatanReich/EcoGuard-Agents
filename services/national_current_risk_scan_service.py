"""Offline nationwide Current Risk scan over active persisted grid cells."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.fire_risk_prediction_agent import FireRiskPredictionAgent
from services.current_risk_feature_builder import CurrentRiskFeatureBuilder
from services.static_feature_store import DEFAULT_DATABASE_PATH
from services.service_area import DEFAULT_SERVICE_AREA_PATH, ServiceArea


DEFAULT_OUTPUT_PATH = Path("data/generated/national_current_risk_scan.json")


class NationalRiskScanError(RuntimeError):
    pass


class NationalCurrentRiskScanService:
    def __init__(self, *, grid_path: Path | str = DEFAULT_DATABASE_PATH,
                 feature_builder: CurrentRiskFeatureBuilder | None = None,
                 prediction_agent: FireRiskPredictionAgent | None = None,
                 service_area_path: Path | str = DEFAULT_SERVICE_AREA_PATH,
                 prediction_workers: int = 4):
        self.grid_path = Path(grid_path)
        self.feature_builder = feature_builder or CurrentRiskFeatureBuilder(grid_path=self.grid_path)
        self.prediction_agent = prediction_agent or FireRiskPredictionAgent()
        self.service_area = ServiceArea(service_area_path)
        self.prediction_workers = max(1, int(prediction_workers))

    def _active_cells(self) -> list[dict[str, Any]]:
        if not self.grid_path.exists():
            raise NationalRiskScanError("risk grid is missing")
        connection = sqlite3.connect(self.grid_path); connection.row_factory = sqlite3.Row
        try:
            active = [dict(row) for row in connection.execute(
                "SELECT * FROM risk_grid_cells WHERE active=1 ORDER BY cell_id"
            )]
            return [cell for cell in active if self.service_area.includes_cell(
                float(cell["latitude"]), float(cell["longitude"])
            )]
        except sqlite3.Error:
            raise NationalRiskScanError("risk grid schema is incompatible") from None
        finally:
            connection.close()

    @staticmethod
    def _evaluation_time(value: datetime | None) -> datetime:
        selected = value or datetime.now(timezone.utc)
        if selected.tzinfo is None:
            raise NationalRiskScanError("evaluation timestamp must include a UTC offset")
        return selected.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)

    def scan(self, evaluation_time: datetime | None = None, *, highest_limit: int = 10) -> dict[str, Any]:
        evaluation = self._evaluation_time(evaluation_time)
        cells, evaluated, unavailable, ready = self._active_cells(), [], [], []
        # One query for the whole grid's weather history, held for the loop.
        # Per-cell reads would be 1,174 round trips to a hosted database, which
        # is minutes of pure latency before any prediction runs.
        source = getattr(self.feature_builder, "weather_source", None)
        window = (
            source.window([cell["cell_id"] for cell in cells], evaluation)
            if source is not None and hasattr(source, "window")
            else _null_session()
        )
        with window:
            for cell in cells:
                if hasattr(self.feature_builder, "build_for_cell_record"):
                    built = self.feature_builder.build_for_cell_record(cell, evaluation)
                else:  # Test doubles and backward-compatible injected builders.
                    built = self.feature_builder.build_for_cell(cell["cell_id"], evaluation)
                if built["status"] != "success":
                    unavailable.append({"cell_id": cell["cell_id"], "latitude": cell["latitude"],
                                        "longitude": cell["longitude"],
                                        "reason": built.get("reason", "current_risk_features_unavailable")})
                    continue
                ready.append((cell, built["features"]))
        # The existing agent remains the sole prediction implementation; independent cells are parallelized only.
        with ThreadPoolExecutor(max_workers=self.prediction_workers) as executor:
            predictions = executor.map(lambda item: self.prediction_agent.predict(item[1]), ready)
            for (cell, _), prediction in zip(ready, predictions):
                if prediction["status"] != "ok":
                    unavailable.append({"cell_id": cell["cell_id"], "latitude": cell["latitude"],
                                        "longitude": cell["longitude"],
                                        "reason": prediction.get("error", {}).get("code", "prediction_unavailable")})
                    continue
                evaluated.append({
                    "cell_id": cell["cell_id"], "latitude": cell["latitude"], "longitude": cell["longitude"],
                    "risk_score": prediction["risk_score"], "risk_level": prediction["risk_level"],
                    "evaluation_time": evaluation.isoformat().replace("+00:00", "Z"),
                })
        evaluated.sort(key=lambda row: row["cell_id"]); unavailable.sort(key=lambda row: row["cell_id"])
        levels = Counter(row["risk_level"] for row in evaluated)
        highest = sorted(evaluated, key=lambda row: (-row["risk_score"], row["cell_id"]))[:highest_limit]
        reasons = Counter(row["reason"] for row in unavailable)
        return {
            "status": "success" if not unavailable else "partial" if evaluated else "unavailable",
            "evaluation_time": evaluation.isoformat().replace("+00:00", "Z"),
            "summary": {"total_active_cells": len(cells), "evaluated_cells": len(evaluated),
                        "unavailable_cells": len(unavailable),
                        "risk_level_counts": {name: levels[name] for name in ("low", "medium", "high")},
                        "unavailable_reason_counts": dict(sorted(reasons.items())),
                        "highest_risk_cells": highest},
            "cells": evaluated, "unavailable_cells": unavailable,
            "semantics": "estimated_fire_risk_not_actual_fire_detection",
        }

    def scan_and_save(self, evaluation_time: datetime | None = None,
                      output_path: Path | str = DEFAULT_OUTPUT_PATH) -> dict[str, Any]:
        result = self.scan(evaluation_time)
        path = Path(output_path); path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        return result


class _null_session:
    def __enter__(self): return None
    def __exit__(self, exc_type, exc, traceback): return False
