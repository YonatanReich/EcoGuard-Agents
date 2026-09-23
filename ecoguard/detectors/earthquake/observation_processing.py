"""Convert newly persisted GSI events into shared earthquake signals."""

from __future__ import annotations

from ecoguard.shared.activity import live_actor

from datetime import datetime, timezone

from ecoguard.collectors.earthquake.gsi import SOURCE
from ecoguard.database.repositories.collector_runs import last_success_at, log_finish, log_start
from ecoguard.database.repositories.observations import read_observations_batch
from ecoguard.shared.signals import EARTHQUAKE, HIGH, CellLocation, CellSignal

RUN_SOURCE = "earthquake_detection"
MIN_DASHBOARD_MAGNITUDE = 3.5


def signals_from_observations(rows: list[dict]) -> list[CellSignal]:
    """Adapt persisted GSI events, suppressing only sub-threshold dashboard signals."""

    signals = []
    for row in rows:
        payload = row["payload"]
        magnitude = float(payload["magnitude"])
        if magnitude < MIN_DASHBOARD_MAGNITUDE:
            continue
        signals.append(CellSignal(
            cell_id=row["cell_id"],
            observed_at=row["observed_at"],
            hazard=EARTHQUAKE,
            variable="magnitude",
            value=magnitude,
            unit="magnitude",
            source=SOURCE,
            rarity=1.0,
            direction=HIGH,
            location=CellLocation(
                latitude=float(payload["latitude"]),
                longitude=float(payload["longitude"]),
                precision_m=1000.0,
                method="gsi_hypocenter",
            ),
            evidence={"earthquake": payload},
        ))
    return signals


@live_actor("detector.earthquake")
def detect_new(*, at: datetime | None = None) -> list[CellSignal]:
    """Turn newly collected earthquakes into signals.

    Reads from the last successful run onwards, so each event is reported
    once however often this runs.
    """
    through = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    since = last_success_at(RUN_SOURCE)
    run_id = log_start(RUN_SOURCE)
    try:
        rows = read_observations_batch(
            SOURCE,
            ingested_after=since,
            ingested_through=through,
            limit=5000,
        )
        signals = signals_from_observations(rows)
        log_finish(run_id, status="ok", rows_written=len(signals))
        return signals
    except Exception as error:
        log_finish(run_id, status="failed", error=f"{type(error).__name__}: {error}")
        raise
