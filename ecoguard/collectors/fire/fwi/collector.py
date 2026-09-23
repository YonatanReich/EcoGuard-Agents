"""Our own Fire Weather Index system, stepped forward one day at a time.

Unlike every other collector this one calls no provider. Its input is the
weather already in `observations` and its own previous output, which is what
makes it different in kind: the three moisture codes are *accumulators*, and an
accumulator that is recomputed from a fixed window instead of carried forward
is not the same quantity. DC in particular integrates months of drying, so a
DC derived from seven days of history is not a shallow DC — it is a different
number that happens to share the name.

That is also why this writes even on days nothing much happened. A missing day
is not a gap in a series, it is a broken chain: every day after it inherits the
error. The collector therefore walks from wherever it left off up to the most
recent complete noon, writing each day, rather than only computing today.

Honest limitation on the first season: the chain starts at the standard spring
values and only what has been observed since can inform it. FFMC settles within
days and DMC within weeks, but DC will be understated for months — it is
accumulating from a cold start, not measuring a real drought history. Read it
as relative to its own record until a full season has passed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from ecoguard.collectors.base import BaseCollector, service_area_cells
from ecoguard.database.engine import Session
from ecoguard.database.repositories.weather_history import HISTORY_HOURS, hourly_for_cells
from ecoguard.collectors.fire.fwi.index import FireWeatherState, advance

logger = logging.getLogger(__name__)

SOURCE = "fwi"

# The index is defined on noon *local standard* time, which for Israel is
# UTC+2 all year. Standard time, not local time — the definition does not
# follow daylight saving, so this stays 10:00 UTC in summer too.
NOON_LOCAL_STANDARD_UTC_HOUR = 10

# How far back to try to rebuild if the chain is empty or stale. Bounded by
# what the weather collector retains, since nothing can be computed for a day
# whose noon was never stored.
MAX_CATCHUP_DAYS = HISTORY_HOURS // 24

# Consecutive days of carried state before DC is worth believing. FFMC settles
# in days and DMC in weeks, but DC integrates months, so a young chain reports
# a drought far milder than the real one — and mild is the dangerous direction
# to be wrong in. Every row carries its own chain_days and a spun_up flag so a
# consumer can refuse the slow codes instead of quietly trusting them.
SPIN_UP_DAYS = 60


def _noon(day: datetime) -> datetime:
    return day.replace(
        hour=NOON_LOCAL_STANDARD_UTC_HOUR, minute=0, second=0, microsecond=0
    )


def latest_states(cell_ids: list[str]) -> dict[str, tuple[datetime, FireWeatherState, int]]:
    """Each cell's most recent stored state — the input to its next day.

    DISTINCT ON rather than a max()/join: one index scan over
    (source, cell_id, observed_at) returns the newest row per cell directly.
    """
    if not cell_ids:
        return {}
    rows = Session().execute(
        text(
            """
            SELECT DISTINCT ON (cell_id) cell_id, observed_at, payload
            FROM observations
            WHERE source = :source AND cell_id = ANY(:cell_ids)
            ORDER BY cell_id, observed_at DESC
            """
        ),
        {"source": SOURCE, "cell_ids": cell_ids},
    ).mappings().all()

    states = {}
    for row in rows:
        payload = row["payload"]
        try:
            states[row["cell_id"]] = (
                row["observed_at"],
                FireWeatherState(
                    ffmc=float(payload["ffmc"]), dmc=float(payload["dmc"]),
                    dc=float(payload["dc"]), isi=float(payload["isi"]),
                    bui=float(payload["bui"]), fwi=float(payload["fwi"]),
                ),
                int(payload.get("chain_days", 0)),
            )
        except (KeyError, TypeError, ValueError):
            # A row we cannot read is worse than no row: it would silently seed
            # the chain with nonsense. Restart this cell from the defaults.
            logger.warning("fwi: unreadable state for %s, restarting chain", row["cell_id"])
    return states


def _noon_inputs(series: dict[str, Any], noon: datetime) -> dict[str, float] | None:
    """Noon temperature, humidity and wind, plus the preceding 24 hours of rain.

    Returns None when the noon hour itself is absent. The rain total tolerates
    gaps — a missing hour there understates the accumulation slightly, where a
    missing noon would mean inventing the day's conditions outright.
    """
    hourly = series.get("hourly") or {}
    stamps = hourly.get("time") or []
    if not stamps:
        return None

    index = {}
    for position, stamp in enumerate(stamps):
        moment = datetime.fromisoformat(str(stamp))
        index[moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)] = position

    position = index.get(noon)
    if position is None:
        return None

    def at(variable: str) -> float | None:
        values = hourly.get(variable) or []
        value = values[position] if position < len(values) else None
        return None if value is None else float(value)

    temperature, humidity, wind = at("temperature_2m"), at("relative_humidity_2m"), at("wind_speed_10m")
    if temperature is None or humidity is None or wind is None:
        return None

    rain = 0.0
    precipitation = hourly.get("precipitation") or []
    for hour in range(1, 25):
        offset = index.get(noon - timedelta(hours=hour))
        if offset is not None and offset < len(precipitation):
            value = precipitation[offset]
            if value is not None:
                rain += float(value)

    return {
        "temperature_c": temperature,
        "humidity_percent": humidity,
        "wind_speed_kmh": wind,
        "rain_24h_mm": rain,
    }


class FireWeatherIndexCollector(BaseCollector):
    source = SOURCE

    def __init__(self, now: Any = None):
        self._now = now or (lambda: datetime.now(timezone.utc))

    def fetch(self) -> list[dict[str, Any]]:
        cells = service_area_cells()
        if not cells:
            return []

        now = self._now()
        # Only noons that have fully passed, and whose following 24 hours of
        # rain are therefore also complete.
        latest_noon = _noon(now)
        if now < latest_noon:
            latest_noon -= timedelta(days=1)

        states = latest_states([cell.cell_id for cell in cells])
        earliest = latest_noon - timedelta(days=MAX_CATCHUP_DAYS - 1)

        series = hourly_for_cells(
            [cell.cell_id for cell in cells],
            earliest - timedelta(hours=24),
            latest_noon,
        )

        records: list[dict[str, Any]] = []
        for cell in cells:
            stored = states.get(cell.cell_id)
            state = stored[1] if stored else None
            chain_days = stored[2] if stored else 0
            # Resume the day after the last one written, or as far back as the
            # weather reaches when there is nothing to resume from.
            day = max(stored[0] + timedelta(days=1), earliest) if stored else earliest

            while day <= latest_noon:
                inputs = _noon_inputs(series.get(cell.cell_id, {}), day)
                if inputs is None:
                    # No noon weather for this day. Skipping keeps yesterday's
                    # state as the base for tomorrow, which is the mildest
                    # available assumption: one day of drying goes unrecorded
                    # rather than the chain resetting.
                    day += timedelta(days=1)
                    continue
                state = advance(state, month=day.month, **inputs)
                chain_days += 1
                records.append({
                    "cell_id": cell.cell_id,
                    "latitude": cell.latitude,
                    "longitude": cell.longitude,
                    "observed_at": day,
                    "payload": {
                        "system": "CFFDRS",
                        "noon_local_standard": True,
                        # How much history stands behind the slow codes, and
                        # whether it is enough. ffmc and isi are usable from
                        # the first day; dc, bui and fwi are not.
                        "chain_days": chain_days,
                        "spun_up": chain_days >= SPIN_UP_DAYS,
                        **state.as_payload(),
                        **{key: round(value, 2) for key, value in inputs.items()},
                    },
                })
                day += timedelta(days=1)

        return records
