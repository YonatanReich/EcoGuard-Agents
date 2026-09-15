"""The collection layer's timers.

Each collector wakes on its own interval, does its work, and writes rows. No
collector calls another, and none of them return anything to a caller. This is
the only place in the system that reaches out to an upstream provider —
everything else reads what these wrote.
"""

from __future__ import annotations

import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler

from ecoguard import retention
from ecoguard.collection.pollution.collector import AirPollutionCollector
from ecoguard.collection.fire.effis.collector import FireWeatherCollector
from ecoguard.collection.fire.firms.collector import FirmsCollector
from ecoguard.collection.fire.fwi.collector import FireWeatherIndexCollector
from ecoguard.collection.fire.gibs.collector import VegetationCollector
from ecoguard.collection.fire.telegram.collector import TelegramCollector
from ecoguard.collection.shared.open_meteo.forecast import WeatherForecastCollector
from ecoguard.collection.shared.open_meteo.observations import WeatherCollector

logger = logging.getLogger(__name__)

# Each interval is set by what its source actually publishes, not by a shared
# default:
#
#   weather       Open-Meteo publishes hourly, so nothing new exists sooner.
#                 This ran every 30 minutes, which meant half of all ticks did
#                 six minutes of provider work to write zero rows. The
#                 collector now fetches only the hours it is missing, so a tick
#                 with nothing to do makes no requests at all — but there is
#                 still no reason to wake twice an hour.
#   firms         Satellite overpasses are about three hours apart for a given
#                 point and arrive irregularly; 30 minutes keeps latency low
#                 without polling data we already have.
#   fire_weather  EFFIS publishes the Fire Weather Index once a day. Every tick
#                 within a day writes the same identities and the unique
#                 constraint discards them, so 30 minutes was 48 raster
#                 downloads to store one day's values. Six hours still catches
#                 the new raster promptly whenever it lands.
#   telegram      The only low-latency source, and the only one where a message
#                 can be minutes old and still matter.
#
#   weather_forecast
#                 Open-Meteo refreshes its runs a few times a day, and a
#                 forecast that has not been re-issued is the same rows again.
#                 Six hours keeps every run without re-storing any of them.
#                 Note this writes far more rows per tick than the observation
#                 collector — 48 hours of lead time for every cell it samples —
#                 which is why it samples a coarser grid.
#
#   fwi           Computes rather than fetches, so the interval is not about a
#                 provider. It needs one value per day, at a noon that has
#                 fully passed; running four times a day means a tick that
#                 finds the day already written does nothing, and a tick after
#                 an outage catches up the missed days in order. Running it
#                 daily would make a single failed run a permanent hole in an
#                 accumulator that cannot be rebuilt from later data.
#
#   vegetation    An 8-day composite, republished daily as it rolls forward.
#                 Twelve hours catches the new one without asking twice for
#                 an image that has not changed.
INTERVAL_MINUTES = {
    # Preserve the previous Ministry runtime's five-minute polling interval.
    # Guest authentication is automatic; no operator credentials are required.
    "air_pollution": 5,
    "firms": 30,
    "weather": 60,
    "weather_forecast": 360,
    "fire_weather": 360,
    "fwi": 360,
    "vegetation": 720,
    "telegram": 5,
}

COLLECTORS = {
    "air_pollution": AirPollutionCollector,
    "firms": FirmsCollector,
    "weather": WeatherCollector,
    "weather_forecast": WeatherForecastCollector,
    "fire_weather": FireWeatherCollector,
    "fwi": FireWeatherIndexCollector,
    "vegetation": VegetationCollector,
    "telegram": TelegramCollector,
}

# fwi reads the hours the weather collector wrote, so on a cold start it has
# nothing to compute from. Nothing enforces the order — it simply finds no noon
# weather and writes nothing, then catches up on a later tick once weather has
# landed. Stated here because "the FWI collector wrote zero rows on a fresh
# database" is otherwise a puzzle rather than the expected first tick.
DEPENDS_ON_STORED_WEATHER = ("fwi",)

# A source with no credentials cannot be collected, and scheduling it anyway
# means a failed row every interval forever — 288 a day for Telegram alone.
# That is not resilience, it is a permanently red light that nobody can tell
# apart from a real outage. Absent credentials are a configuration state, so
# they are reported once at startup and the job is not registered.
REQUIRED_ENVIRONMENT = {
    "telegram": ("TELEGRAM_API_ID", "TELEGRAM_API_HASH"),
    "firms": ("NASA_FIRMS_API_KEY",),
}


def unconfigured(source: str) -> list[str]:
    """Which required environment variables are missing for a source."""
    return [name for name in REQUIRED_ENVIRONMENT.get(source, ()) if not os.getenv(name)]


scheduler = BackgroundScheduler()

for name, collector_class in COLLECTORS.items():
    missing = unconfigured(name)
    if missing:
        logger.warning(
            "%s collector not scheduled: %s not set", name, ", ".join(missing)
        )
        continue

    scheduler.add_job(
        collector_class().run,
        "interval",
        minutes=INTERVAL_MINUTES[name],
        id=f"collect_{name}",
        # max_instances guards within this process; the advisory lock in run()
        # guards across processes, which matters when three developers point
        # their local app at the same shared database.
        max_instances=1,
        # A tick missed while the process was down runs once, not once per
        # interval that elapsed.
        coalesce=True,
    )


# Retention is not a collector — it writes nothing and talks to no provider —
# but it belongs on the same timer board, and logging it to collector_runs means
# "is anything pruning?" is answered the same way as "is anything collecting?".
#
# Daily, and deliberately not more often: the deletes are bounded by one day of
# arrivals either way, and a job that removes nothing on most runs is cheaper to
# reason about than one that removes a handful every hour.
scheduler.add_job(
    retention.run,
    "interval",
    hours=24,
    id="prune_observations",
    max_instances=1,
    coalesce=True,
)


def run_once(source: str) -> None:
    """Run one collector immediately. Used by the dev endpoint."""
    if source not in COLLECTORS:
        raise KeyError(source)
    COLLECTORS[source]().run()
