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
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from ecoguard import retention
from ecoguard.collectors.flood.hydrometric_observations import (
    SOURCE as HYDROMETRIC_OBSERVATIONS_SOURCE,
    HydrometricObservationCollector,
)
from ecoguard.collectors.earthquake.gsi import GsiEarthquakeCollector
from ecoguard.collectors.pollution.collector import AirPollutionCollector
from ecoguard.collectors.fire.effis.collector import FireWeatherCollector
from ecoguard.collectors.fire.firms.collector import FirmsCollector
from ecoguard.collectors.fire.fwi.collector import FireWeatherIndexCollector
from ecoguard.collectors.fire.gibs.collector import VegetationCollector
from ecoguard.collectors.shared.telegram.collector import TelegramCollector
from ecoguard.collectors.text.rss import RssCollector
from ecoguard.collectors.water_level.kinneret import KinneretLevelCollector
from ecoguard.collectors.shared.open_meteo.forecast import WeatherForecastCollector
from ecoguard.collectors.shared.open_meteo.observations import WeatherCollector
from ecoguard.database.locks import single_flight
from ecoguard.resource_allocator.allocation_agent import ResourceAllocationAgent
from ecoguard.resource_allocator.allocation_agent import (
    EARTHQUAKE_MINIMUM_RESPONSE_POLICY,
)

logger = logging.getLogger(__name__)

# The allocator exists for the lifetime of the scheduler process, so its static
# station catalog is loaded once. Availability is not cached here: atomic DB
# claims keep concurrent scheduler processes in sync.
resource_allocator = ResourceAllocationAgent()


def allocate_resources(processing_results):
    """Delegate hazard-specific preparation and shared station allocation."""

    return resource_allocator.allocate_processing_results(processing_results)

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
#   hydrometric   The Water Authority publishes ten-minute readings through a
#                 rolling window. Polling on that same cadence avoids duplicate
#                 upstream requests without delaying newly published data.
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
    # News feeds republish within a minute or two of an editor pressing
    # publish, and conditional requests make an unchanged feed nearly free, so
    # this is set by how fast a breaking item matters rather than by provider
    # cost. Three minutes across eight outlets is a few hundred requests a day.
    "rss": 3,
    HYDROMETRIC_OBSERVATIONS_SOURCE: 10,
    "gsi_earthquake": 5,
    # One survey a day, published to an open dataset with no key and no rate
    # limit worth respecting. Six hours is four requests a day, which catches
    # the new reading within a morning without asking repeatedly for a number
    # that changes by centimetres. The lake itself moves on a scale of months.
    "kinneret_level": 360,
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
    "rss": RssCollector,
    HYDROMETRIC_OBSERVATIONS_SOURCE: HydrometricObservationCollector,
    "gsi_earthquake": GsiEarthquakeCollector,
    "kinneret_level": KinneretLevelCollector,
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

# An interval job first fires one interval after the scheduler starts, so a
# six-hour collector on a container that is redeployed every couple of hours
# never runs at all: collector_runs showed 12- and 22-hour holes in the hourly
# weather and twelve-hour vegetation feeds. Every collector therefore also runs
# once at boot, staggered thirty seconds apart so a deploy does not open twelve
# provider connections at once. Cheap by design: each collector fetches only
# what it is missing and the unique constraints discard the rest.
#
# misfire_grace_time=None because that boot-time slot is computed at import and
# the scheduler starts minutes later, after the heavy imports; with the default
# one-second grace the boot run would be silently dropped as a misfire.
BOOT = datetime.now(timezone.utc)
BOOT_STAGGER = timedelta(seconds=30)

for position, (name, collector_class) in enumerate(COLLECTORS.items()):
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
        next_run_time=BOOT + BOOT_STAGGER * position,
        misfire_grace_time=None,
    )


def process_text_events(*, coordinate=None) -> dict[str, object]:
    """Classify stored Telegram/RSS text, then triage it, without escaping.

    Failure is contained but not isolated from the wave: a model, database or
    gazetteer failure here is caught and logged, and the structured detectors
    carry on, but the signals this produces are handed back to the caller
    rather than coordinated separately.

    Args:
        coordinate: Where triage should send its signals. The wave passes a
            collector so that text signals join the same coordination batch as
            the structured ones; passing None makes triage coordinate on its
            own, which is only correct when nothing else is about to.
    """
    result: dict[str, object] = {"classification": None, "triage": None}
    try:
        from ecoguard.detectors.text.classifier import classify_new_text

        result["classification"] = classify_new_text()
    except Exception:
        # Triage still runs: candidates successfully stored on an earlier tick
        # must not be stranded by today's model outage.
        logger.exception("text classification failed; continuing to triage")

    try:
        from ecoguard.detectors.text.run import run_text_triage

        result["triage"] = run_text_triage(coordinate=coordinate)
    except Exception:
        logger.exception("text triage failed; collectors and detectors continue")
    return result


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
    # Same boot-time run as the collectors: a daily job on a container that
    # rarely lives a day would otherwise never prune.
    next_run_time=BOOT + BOOT_STAGGER * len(COLLECTORS),
    misfire_grace_time=None,
)


def publish(results):
    """Project finished results to the frontend. Never raises."""
    if not results:
        return
    try:
        from ecoguard.coordinator.event_projection import project_processing_results

        project_processing_results(results)
    except Exception:
        # Projection is delivery state. It must not erase completed processing
        # or affect the authoritative persisted Coordinator incident.
        logger.exception(
            "incident event projection failed; processing results are unaffected"
        )


def detect_and_coordinate():
    """One wave: every detector, one coordinator, the analysers, then publish.

    Detectors and the media lane all run first and their candidates are
    coordinated together in a single batch, so corroboration and deduplication
    see the whole tick at once rather than one lane at a time. The coordinator
    routes what it touched to the hazard analysers, and planning leaves by two
    lines: advisory plans to the frontend, emergency plans through the resource
    allocator and then to the frontend.

    The detectors intentionally emit separate hazard streams. Satellite
    hotspots emit ``fire`` signals for emergency routing, weather anomalies
    emit ``fire_weather`` signals for separate non-emergency advisories, and
    hydrometric observations emit ``flood`` signals. Batching them does not
    merge one hazard into another.

    The satellite comes first in the list for readability only — the
    Coordinator sorts by observation time. FIRMS *sees* fires; the weather
    sweep sees conditions under which a fire could spread and cannot detect a
    fire, because the feed is a numerical model with no knowledge that one
    exists.

    A detector that raises must not take the others down with it, so each is
    called separately. Losing the satellite for a tick is a detection outage;
    losing the whole run because the weather sweep hit a bad row would be a
    worse one.

    Each detector reads what has arrived since its own last successful run.
    Flood additionally loads a bounded hydrometric history to verify that a
    new reading has the required consecutive predecessor.

    Imported inside the function so a failure to import the coordinator cannot
    take the collection timers down with it — the collectors are useful on
    their own, and were running before any of this existed.
    """
    from ecoguard.coordinator.agent import run as coordinate
    from ecoguard.detectors.air_pollution import observation_processing
    from ecoguard.detectors.fire import satellite, weather
    from ecoguard.detectors.flood import observation_processing as flood_processing
    from ecoguard.detectors.earthquake import observation_processing as earthquake_processing

    # max_instances=1 above only guards this process. Two processes pointed at
    # the same database — a local backend alongside the hosted one, or two
    # replicas — each run their own copy of this wave, and because they read
    # the same incidents and the same projections they both decide the same
    # plans need rebuilding. Every model call in the pipeline is then paid
    # twice. The collectors have had this lock since they were written; this
    # job is the expensive one and did not.
    with single_flight("detect_and_coordinate") as acquired:
        if not acquired:
            logger.info(
                "detect_and_coordinate: another process holds the wave lock, skipping"
            )
            return []
        return _detect_and_coordinate()


def _detect_and_coordinate():
    """The wave itself. Only ever called with the single-flight lock held."""
    from ecoguard.coordinator.agent import run as coordinate
    from ecoguard.detectors.air_pollution import observation_processing
    from ecoguard.detectors.fire import satellite, weather
    from ecoguard.detectors.flood import observation_processing as flood_processing
    from ecoguard.detectors.earthquake import observation_processing as earthquake_processing

    signals = []

    # The text lane runs inside the wave, and its signals join this batch
    # rather than being coordinated on their own.
    #
    # It used to be a separate three-minute job that called the coordinator
    # itself and threw the result away. Two things followed, both silent. Text
    # incidents were created and then never dispatched by anyone, so a report
    # from Telegram could never be analysed, planned or projected — the
    # uncorroborated advisory lane could not fire at all. And because the two
    # lanes coordinated on different clocks, a Telegram report and a satellite
    # hotspot describing the same fire were never in the same batch, so they
    # could not corroborate each other in the pass they both arrived in.
    #
    # Running it here fixes both, costs less (classification on a ten-minute
    # cadence rather than three), and makes a scenario run reproducible.
    # Isolation is unchanged: process_text_events catches its own failures, as
    # each detector below does.
    try:
        process_text_events(coordinate=signals.extend)
    except Exception:
        logger.exception("text lane failed; structured detection continues")

    for detector in (
        satellite,
        weather,
        observation_processing,
        flood_processing,
        earthquake_processing,
    ):
        try:
            signals.extend(detector.detect_new())
        except Exception:
            logger.exception("detector %s failed; continuing without it",
                             detector.__name__)

    coordination = coordinate(signals)
    if coordination is None:
        return []

    try:
        from ecoguard.coordinator.dispatcher import dispatch_touched

        processing_results = dispatch_touched(coordination.touched_ids)
    except Exception:
        # Incidents are already safely persisted. Analysis/planning is a
        # downstream attempt and must never turn successful coordination into
        # a failed detection tick.
        logger.exception("incident dispatch failed after coordination")
        return []

    # Planning has two exits, not one. An advisory plan is finished the moment
    # it is written — nobody is dispatched to it — so it goes straight to the
    # frontend. An emergency plan is not finished until stations are committed
    # against it, so it goes through the allocator first and is published with
    # its allocation attached. Splitting them means a Mapbox round trip for one
    # fire cannot hold up an air quality warning that is already written.
    #
    # getattr rather than .route: the allocator reads results the same way, and
    # a result that cannot say which line it is on is not an emergency one.
    emergency = [
        result for result in processing_results
        if getattr(result, "route", None) == "emergency"
    ]
    advisory = [
        result for result in processing_results
        if getattr(result, "route", None) != "emergency"
    ]

    publish(advisory)

    try:
        allocate_resources(emergency)
    except Exception:
        # Allocation is downstream of analysis and planning. A routing, DB, or
        # Mapbox failure must not discard their completed results.
        logger.exception(
            "resource allocation failed; processing results are unaffected"
        )

    publish(emergency)
    return processing_results


# Every ten minutes: one wave through the whole pipeline. Every detector and
# the media lane run, their candidates are coordinated together, the analysers
# report on what the coordinator touched, and the two planning lines publish.
#
# Ten rather than thirty because the fastest sources are the ones worth being
# fast for — Telegram polls at five minutes, RSS at three, hydrometric at ten —
# and a thirty-minute sweep left a report of a fire sitting in a table for up
# to half an hour after someone posted it. The slow collectors are unaffected:
# a tick that finds nothing new from FIRMS or EFFIS reads rows it has already
# seen and emits nothing.
#
# The cost of the extra ticks is re-reporting detections already attached to an
# open incident, which the coordinator absorbs by design.
#
# max_instances=1 makes this a wave rather than an overlap: if a run is still
# analysing when the next tick fires, that tick is dropped instead of starting
# a second pass over the same incidents.
scheduler.add_job(
    detect_and_coordinate,
    "interval",
    minutes=10,
    id="detect_and_coordinate",
    max_instances=1,
    coalesce=True,
)


def run_once(source: str) -> None:
    """Run one collector immediately. Used by the dev endpoint."""
    if source not in COLLECTORS:
        raise KeyError(source)
    COLLECTORS[source]().run()
