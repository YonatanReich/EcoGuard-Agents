"""The collection layer's timers.

Each collector wakes on its own interval, does its work, and writes rows. No
collector calls another, and none of them return anything to a caller.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from ecoguard.collection.fire_weather import FireWeatherCollector
from ecoguard.collection.firms import FirmsCollector
from ecoguard.collection.telegram import TelegramCollector
from ecoguard.collection.weather import WeatherCollector

logger = logging.getLogger(__name__)

# FIRMS is bounded by satellite overpasses — about three hours apart for a
# given point, arriving irregularly — and EFFIS publishes FWI once a day, so
# polling either faster returns data we already have. Telegram is the only
# low-latency source, so it gets the short interval.
INTERVAL_MINUTES = {
    "firms": 30,
    "weather": 30,
    "fire_weather": 30,
    "telegram": 5,
}

COLLECTORS = {
    "firms": FirmsCollector,
    "weather": WeatherCollector,
    "fire_weather": FireWeatherCollector,
    "telegram": TelegramCollector,
}

scheduler = BackgroundScheduler()

for name, collector_class in COLLECTORS.items():
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


def run_once(source: str) -> None:
    """Run one collector immediately. Used by the dev endpoint."""
    if source not in COLLECTORS:
        raise KeyError(source)
    COLLECTORS[source]().run()
