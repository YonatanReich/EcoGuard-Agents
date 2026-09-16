"""The timers.

Each collector wakes on its own interval, does its work, and writes rows. No
collector calls another, and none of them return anything to a caller. This is
the only place in the system that reaches out to an upstream provider —
everything else reads what these wrote.

One job is not a collector: detection. It reads what the collectors stored and
hands the result to the coordinator, and it is here because that is where the
clocks live, not because it fetches anything.
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


def detect_and_coordinate() -> None:
    """Sweep stored observations for Fire and Fire-weather signals.

    The two detectors intentionally emit separate hazard streams. Satellite
    hotspots emit ``fire`` signals for emergency routing; weather anomalies
    emit ``fire_weather`` signals for separate non-emergency advisories. The
    Coordinator currently has no FIRE-to-FIRE_WEATHER corroboration or
    association rule, so batching them does not merge one into the other.

    The satellite comes first in the list for readability only — the
    Coordinator sorts by observation time. FIRMS *sees* fires; the weather
    sweep sees conditions under which a fire could spread and cannot detect a
    fire, because the feed is a numerical model with no knowledge that one
    exists.

    A detector that raises must not take the others down with it, so each is
    called separately. Losing the satellite for a tick is a detection outage;
    losing the whole run because the weather sweep hit a bad row would be a
    worse one.

    Each detector reads what has arrived since its own last successful run
    rather than what falls inside a fixed window, so a tick that never happened
    — a hang, a restart, a deploy — costs latency and nothing else. A window
    would have dropped everything older than itself and said nothing about it,
    which for a fire detector is the one unacceptable failure.

    Imported inside the function so a failure to import the coordinator cannot
    take the collection timers down with it — the collectors are useful on
    their own, and were running before any of this existed.
    """
    from ecoguard.coordinator.agent import run as coordinate
    from ecoguard.detectors.fire import satellite, weather

    signals = []
    for detector in (satellite, weather):
        try:
            signals.extend(detector.detect_new())
        except Exception:
            logger.exception("detector %s failed; continuing without it",
                             detector.__name__)

    coordinate(signals)


# Every thirty minutes, set by the satellite rather than the weather.
#
# The weather half only changes hourly and a second look at the same stored
# hour finds the same anomaly. But FIRMS is the half that detects fires, its
# overpasses arrive irregularly, and the collector already polls at thirty
# minutes — so an hourly detector would sit on a fresh hotspot for up to an
# hour after it landed. That is the one delay in this pipeline that costs
# something real.
#
# The cost of the extra tick is re-reporting detections already attached to an
# open incident, which the coordinator absorbs by design.
scheduler.add_job(
    detect_and_coordinate,
    "interval",
    minutes=30,
    id="detect_and_coordinate",
    max_instances=1,
    coalesce=True,
)


def run_once(source: str) -> None:
    """Run one collector immediately. Used by the dev endpoint."""
    if source not in COLLECTORS:
        raise KeyError(source)
    COLLECTORS[source]().run()
