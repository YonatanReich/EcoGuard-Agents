"""Historical fires: the Carmel (2010) and Jerusalem hills (2025) wildfires, replayed.

Every observation is real. Satellite pixels come from the NASA FIRMS archive,
hourly weather from the Open-Meteo archive, and the news items from the
outlets' own archives (URLs in `historical_fires_news.json`). Nothing is
authored except the choice of when to stop the clock.

That moment is the honest one: the first time a satellite detection of the
fire would have reached the live collector. A pixel only counts once its
product's measured publication lag has passed, and news only counts once it
was published. The pipeline is then asked what it would have told an operator
at that moment, and the answer is graded against what the fire went on to do
in the next three hours - the horizon the spread forecast covers.

As in the flood demo, the historical clock is rebased so the checkpoint lands
just before the demo starts. Intervals between readings are untouched.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from ecoguard.collectors.fire.firms.collector import group_hotspots
from ecoguard.database.engine import Session

HERE = Path(__file__).parent
DATA = json.loads((HERE / "historical_fires_data.json").read_text(encoding="utf-8"))
NEWS = json.loads((HERE / "historical_fires_news.json").read_text(encoding="utf-8"))

# Median minutes from overpass to a stored row, measured on the live
# `observations` table over the 30 days to 2026-10-04 (ingested_at minus
# observed_at, backfills excluded). It includes the collector's own 30-minute
# poll, which is the point: this is when the system would actually have had it.
PRODUCT_LAG_MINUTES = {
    "GOES_NRT": 43,
    "MODIS_NRT": 106,
    "VIIRS_NOAA20_NRT": 156,
    "VIIRS_NOAA21_NRT": 132,
    "VIIRS_SNPP_NRT": 157,
}

# One detection wave after the first pixel lands, so it has been processed.
WAVE = timedelta(minutes=10)

# How much weather history to seed before the checkpoint. The analyser reads
# the newest reading within six hours; more is padding.
WEATHER_HISTORY = timedelta(hours=8)

# The feeds on the live allowlist, by outlet. A text candidate must reference a
# configured source, so an article from an outlet not on the list (Haipo,
# Calcalist, AP) is kept in the news file for the record but not seeded.
RSS_SOURCES = {
    "ynet": ("https://www.ynet.co.il/Integration/StoryRss1854.xml", "ynet", "ynet — מבזקים"),
    "walla": ("https://rss.walla.co.il/feed/1?type=main", "walla", "Walla — חדשות"),
    "maariv": ("https://www.maariv.co.il/Rss/RssFeedsMivzakiChadashot", "maariv", "מעריב — מבזקי חדשות"),
    "haaretz": ("https://www.haaretz.co.il/srv/rss---feedly", "haaretz", "הארץ"),
    "timesofisrael": ("https://www.timesofisrael.com/feed/", "timesofisrael", "The Times of Israel"),
    "jpost": ("https://www.jpost.com/rss/rssfeedsisraelnews.aspx", "jpost", "The Jerusalem Post — Israel News"),
}

FIRES: dict[str, dict[str, Any]] = {
    "carmel_2010": {
        # State Comptroller 2012, minute log: western Isfiya, 11:00 local.
        "ignition": datetime(2010, 12, 2, 9, 0, tzinfo=timezone.utc),
        # Checkpoint offset from the demo start; keeps the two fires apart in
        # the seeded clock without changing anything within either.
        "lands_before_start": timedelta(minutes=5),
    },
    "jerusalem_2025": {
        "ignition": datetime(2025, 4, 30, 6, 30, tzinfo=timezone.utc),
        "lands_before_start": timedelta(minutes=5),
    },
}


def _utc(value: str) -> datetime:
    """An ISO timestamp from the data files, as an aware UTC datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _pixel_time(pixel: dict[str, Any]) -> datetime:
    """When FIRMS says the satellite saw this pixel."""
    stamp = str(pixel["acquisition_time"]).zfill(4)
    return datetime.strptime(
        f"{pixel['acquisition_date']} {stamp}", "%Y-%m-%d %H%M"
    ).replace(tzinfo=timezone.utc)


def _available_at(pixel: dict[str, Any]) -> datetime:
    """When the live collector would first have stored this pixel."""
    return _pixel_time(pixel) + timedelta(minutes=PRODUCT_LAG_MINUTES[pixel["firms_source"]])


def checkpoint(name: str) -> datetime:
    """The first moment the system could have known about this fire from space."""
    fire = FIRES[name]
    after_ignition = [
        p for p in DATA["fires"][name]["firms_pixels"] if _pixel_time(p) >= fire["ignition"]
    ]
    return min(_available_at(p) for p in after_ignition) + WAVE


def _news_items(name: str) -> list[dict[str, Any]]:
    """The fire's news items that a configured feed published, oldest first."""
    israel = timezone(timedelta(hours=2 if name == "carmel_2010" else 3))
    items = []
    for item in NEWS[name]:
        # An article whose archived text was updated after it first ran
        # counts from when that text was true, so a later fact cannot leak
        # backwards into the checkpoint.
        stamp = item.get("content_as_of") or item.get("published_local")
        if stamp is None or item["outlet"] not in RSS_SOURCES:
            continue
        published = datetime.strptime(stamp, "%Y-%m-%d %H:%M")
        items.append({**item, "published_at": published.replace(tzinfo=israel).astimezone(timezone.utc)})
    return sorted(items, key=lambda item: item["published_at"])


def _rss(item: dict[str, Any], observed: datetime) -> tuple[str, dict[str, Any]]:
    """One news item as the RSS collector stores it: (cell_id, payload)."""
    source_id, handle, display_name = RSS_SOURCES[item["outlet"]]
    return f"rss:{handle}:{item['url']}", {
        "source_id": source_id,
        "kind": "rss",
        "handle": handle,
        "display_name": display_name,
        "item_guid": item["url"],
        "title": item["title"],
        "summary": item["summary"],
        "raw_text": f"{item['title']}\n{item['summary']}",
        "source_url": item["url"],
        "posted_at": observed.isoformat(),
    }


def build_rows(now: datetime) -> list[tuple[str, str, datetime, dict[str, Any]]]:
    """Every observation available at each fire's checkpoint, rebased onto `now`."""
    rows: list[tuple[str, str, datetime, dict[str, Any]]] = []
    for name, fire in FIRES.items():
        stop = checkpoint(name)
        shift = (now - fire["lands_before_start"]) - stop
        data = DATA["fires"][name]

        # Satellite: what had been published by the checkpoint, grouped by
        # cell and overpass exactly as the collector groups it.
        # Copies: the acquisition stamps are rebased below, and the archive
        # pixels are shared module state that `checkpoint` reads.
        visible = [
            dict(p) for p in data["firms_pixels"]
            if _pixel_time(p) >= fire["ignition"] and _available_at(p) <= stop
        ]
        for record in group_hotspots(visible):
            observed = record["observed_at"] + shift
            for pixel in record["payload"]["hotspots"]:
                pixel["acquisition_date"] = observed.strftime("%Y-%m-%d")
                pixel["acquisition_time"] = observed.strftime("%H%M")
            rows.append(("firms", record["cell_id"], observed, record["payload"]))

        # Weather: the hours before the checkpoint, per cell.
        for cell_id, hours in data["weather"].items():
            for hour in hours:
                at = _utc(hour["observed_at"])
                if stop - WEATHER_HISTORY <= at <= stop:
                    payload = {key: value for key, value in hour.items() if key != "observed_at"}
                    rows.append(("weather", cell_id, at + shift, payload))

        # News: what the configured feeds had published by the checkpoint.
        for item in _news_items(name):
            if item["published_at"] <= stop:
                observed = item["published_at"] + shift
                cell_id, payload = _rss(item, observed)
                rows.append(("rss", cell_id, observed, payload))
    return rows


GROUND_TRUTH: list[dict[str, Any]] = [
    {
        "id": "HF1",
        "event": (
            "Carmel forest fire, 2 December 2010: ignites 11:00 in western Isfiya and "
            "runs west on an easterly wind toward Damon prison and Beit Oren."
        ),
        "hazard": "fire",
        # The first MODIS pixels (12:10) centre on 32.722, 35.041, beside the
        # Comptroller's ignition point on Isfiya's western edge.
        "latitude": 32.722,
        "longitude": 35.041,
        "expect_detected": True,
        "expect_route": "emergency",
        "expect_plan": True,
        "expect_marker_within_km": 3.0,
        "expect_min_signals": 2,
        "expect_min_instrument_signals": 1,
        "expect_min_text_reports": 1,
        "expect_fire_district": "חוף",
        # Inside the three-hour horizon from the 14:06 checkpoint: Isfiya was
        # the ignition site (evacuation began 11:55), Beit Oren was ordered out
        # at 12:40 and burned that afternoon. Damon prison, Givat Wolfson and
        # Yemin Orde are not settlements in the towns table, so they cannot be
        # graded as settlements.
        "expect_warned": ["עספיא", "בית אורן"],
        "expect_evacuate": ["עספיא", "בית אורן"],
        # Ordered after the horizon (18:54 onward). Reported, not graded: a
        # three-hour forecast is not wrong for leaving out the next morning.
        "later_in_reality": ["עין הוד", "עין חוד", "ניר עציון", "טירת כרמל", "החותרים", "מגדים"],
        "expect_notes": (
            "Satellite: one MODIS overpass at 12:10, available ~13:56 at MODIS's measured "
            "106-minute lag; checkpoint 14:06. 2010 predates VIIRS and the Meteosat feed. "
            "News: ynet 12:02 and 12:37 precede it and should open the incident first; the "
            "satellite detection must join that incident, not start a second one. Weather "
            "is ERA5 (the only archive for 2010), which smooths the ridge-top easterly to "
            "~10 km/h."
        ),
    },
    {
        "id": "HF2",
        "event": (
            "Jerusalem hills fire, 30 April 2025: ignites ~09:30 in Eshtaol Forest near "
            "Mesilat Zion and runs west-northwest on a sharav east wind toward Ta'oz, "
            "Neve Shalom, Latrun, Nahshon and Beko'a."
        ),
        "hazard": "fire",
        # The first Meteosat pixels (07:07 UTC) centre on 31.811, 35.005, at the
        # edge of Eshtaol Forest between Mesilat Zion and Ta'oz.
        "latitude": 31.811,
        "longitude": 35.005,
        "expect_detected": True,
        "expect_route": "emergency",
        "expect_plan": True,
        "expect_marker_within_km": 3.0,
        "expect_min_signals": 2,
        "expect_min_instrument_signals": 2,
        "expect_min_text_reports": 1,
        "expect_fire_district": "ירושלים",
        # Inside the horizon from the 11:00 checkpoint: Neve Shalom was ordered
        # out at 10:42, Nahshon at ~12:15, Beko'a and Ta'oz by 14:12; Mesilat
        # Zion was being prepared at 14:12. Latrun is a compound, not a
        # settlement in the towns table.
        "expect_warned": ["נווה שלום", "נחשון", "בקוע", "תעוז", "מסילת ציון"],
        "expect_evacuate": ["נווה שלום", "נחשון", "בקוע", "תעוז"],
        # After the horizon, mostly after the late-afternoon westerly shift.
        "later_in_reality": ["מבוא חורון", "משמר איילון", "נווה אילן", "שורש", "נטף", "יד השמונה"],
        "expect_notes": (
            "Satellite: Meteosat first sees it at 07:07 UTC (10:07 local, ~37 min after "
            "ignition), available ~07:50 at its measured 43-minute lag; checkpoint 08:00 "
            "UTC (11:00 local). News: Times of Israel at 10:42 reports the Neve Shalom "
            "evacuation and must join the satellite incident. Weather is the Open-Meteo "
            "best-match model the live collector reads: ESE 30-35 km/h, 11-14% humidity."
        ),
    },
]

# The weather detector's advisory, from the seeded weather alone. Correct, not
# noise: the Meteorological Service issued fire-danger warnings for both days
# (1 Dec 2010 17:22 and 2 Dec 06:38 per the Comptroller; the 2025 sharav).
EXPECTED_BYPRODUCTS: list[dict[str, str]] = [
    {"hazard": "fire_weather", "why": "fire-danger weather on both days, as the IMS warned"},
]
EXPECTED_SILENCE: list[dict[str, str]] = []

INSERT = text(
    'INSERT INTO "{schema}".observations '
    "(source, cell_id, location, observed_at, ingested_at, payload) "
    "VALUES (:source, :cell_id, NULL, :observed_at, :ingested_at, "
    "CAST(:payload AS jsonb))"
)


def seed(schema: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Write both fires' checkpoint evidence into the isolated demo schema."""
    moment = now or datetime.now(timezone.utc)
    rows = build_rows(moment)
    statement = text(str(INSERT).replace("{schema}", schema))
    # One executemany, not 479 round trips: row-by-row was 88 s of every run.
    with Session() as session:
        session.execute(statement, [
            {
                "source": source,
                "cell_id": cell_id,
                "observed_at": observed_at,
                "ingested_at": moment,
                "payload": json.dumps(payload, ensure_ascii=False),
            }
            for source, cell_id, observed_at, payload in rows
        ])
        session.commit()

    by_source: dict[str, int] = {}
    for source, *_ in rows:
        by_source[source] = by_source.get(source, 0) + 1
    return {
        "observations": len(rows),
        "by_source": by_source,
        "seeded_at": moment.isoformat(),
        "checkpoints": {name: checkpoint(name).isoformat() for name in FIRES},
        "expectations": {"events": GROUND_TRUTH, "silence": EXPECTED_SILENCE},
    }


__all__ = ["GROUND_TRUTH", "EXPECTED_BYPRODUCTS", "EXPECTED_SILENCE", "build_rows", "seed"]
