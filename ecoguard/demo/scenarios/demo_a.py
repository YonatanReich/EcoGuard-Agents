"""Demo A: five authored events, and the evidence they would have produced.

The events are written down first, in `GROUND_TRUTH`. The observations below
are then derived from them — what FIRMS would have seen, what the gauge would
have read, what someone would have posted — so the expected output is known
before the pipeline runs. Without that, "it found three fires" cannot be
distinguished from "it found three things".

Calibration is against the real reference data, not invented:

  * Eilat and the Carmel have no `firms_baselines` row, and the satellite
    detector reports a cell it has no baseline for (rarity None is reportable).
  * Station 417's September PM10 p95 is 46-58 ug/m3, so 185 is unambiguous and
    25 is unambiguously normal.
  * Nahal Ashalim's own official discharge thresholds are 5 and 20 m3/s, and
    they travel in the observation payload, so the flood transition is exact.

Noise is not padding. Each noise row is a specific thing the system is supposed
to decline, and the grader checks that it declined it.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from ecoguard.database.engine import Session

# --------------------------------------------------------------------------
# The events, authored
# --------------------------------------------------------------------------

EILAT = (29.5577, 34.9519)
CARMEL = (32.7500, 35.0300)
ASHALIM = (31.0659, 35.3301)
NEGEV_STATION = (30.9644, 34.7008)
NETANYA = (32.3215, 34.8532)

GROUND_TRUTH: list[dict[str, Any]] = [
    {
        "id": "A1",
        "event": "Large fire in central Eilat, growing across three overpasses.",
        "hazard": "fire",
        "latitude": EILAT[0],
        "longitude": EILAT[1],
        "expect_detected": True,
        "expect_route": "emergency",
        "expect_marker_within_km": 3.0,
        "expect_notes": (
            "Highest-intensity fire in the scenario (peak FRP 210 MW, 5 pixels, "
            "growing). Two independent Telegram reports corroborate it, so the "
            "incident must NOT be in the uncorroborated lane. Hot, dry, windy "
            "conditions are in the weather row for this cell and should appear "
            "in the risk reasoning."
        ),
    },
    {
        "id": "A2",
        "event": "Moderate fire in the Carmel forest.",
        "hazard": "fire",
        "latitude": CARMEL[0],
        "longitude": CARMEL[1],
        "expect_detected": True,
        "expect_route": "emergency",
        "expect_marker_within_km": 4.0,
        "expect_notes": (
            "Half the intensity of A1 (peak 65 MW). A correct system ranks it "
            "below A1. No text reports mention it — satellite only."
        ),
    },
    {
        "id": "A3",
        "event": "Flash flood in Nahal Ashalim; discharge crosses the 10-year threshold.",
        "hazard": "flood",
        "latitude": ASHALIM[0],
        "longitude": ASHALIM[1],
        "expect_detected": True,
        "expect_route": "emergency",
        "expect_marker_within_km": 6.0,
        "expect_notes": (
            "Discharge 0.4 -> 62 -> 95 m3/s against this station's own official "
            "thresholds, crossing the 10-year mark (48) on two consecutive "
            "readings, which is what the detector requires. Two other gauges "
            "stay flat and must produce nothing."
        ),
    },
    {
        "id": "A4",
        "event": "Dust/particulate episode at the Negev monitoring station.",
        "hazard": "air_pollution",
        "latitude": NEGEV_STATION[0],
        "longitude": NEGEV_STATION[1],
        "expect_detected": True,
        "expect_route": "non_emergency",
        "expect_marker_within_km": 3.0,
        "expect_notes": (
            "PM10 185 ug/m3 against a September p95 of about 50. Advisory route "
            "only — it must never be classified as an emergency, and no station "
            "should be allocated to it."
        ),
    },
    {
        "id": "A5",
        "event": "Someone reports a fire in Netanya. Nothing else sees it.",
        "hazard": "fire",
        "latitude": NETANYA[0],
        "longitude": NETANYA[1],
        "expect_detected": True,
        "expect_route": "uncorroborated",
        "expect_marker_within_km": 6.0,
        "expect_notes": (
            "One Telegram claim, no satellite hotspot, no second origin. Must "
            "reach the operator as an UNCORROBORATED advisory naming Netanya's "
            "responsible police station and local authority with phone numbers "
            "— and must NOT get a risk score or an allocation."
        ),
    },
]

# Known and accepted by-products of the seeded evidence. Listed so the grader
# does not report them as spurious, and so a reader knows they were expected.
EXPECTED_BYPRODUCTS: list[dict[str, str]] = [
    {"hazard": "fire_weather",
     "why": "The hot, dry, windy weather rows seeded for A1/A2 so the fire risk "
            "analysis has conditions to reason about are themselves a "
            "fire-weather anomaly. It is correct to raise it; note that no "
            "handler is registered for ('fire_weather', 'non_emergency'), so it "
            "is skipped as unsupported_hazard_route and never projected."},
]

# Every one of these is a specific refusal the grader checks for.
EXPECTED_SILENCE: list[dict[str, str]] = [
    {"id": "N1", "noise": "Metaphorical fire: a political 'fire in the Likud'.",
     "expect": "classifier marks it not literal; no candidate, no incident"},
    {"id": "N2", "noise": "A real wildfire, but in Greece.",
     "expect": "classifier marks in_israel=false; no incident in Israel"},
    {"id": "N3", "noise": "Unrelated news item with no hazard at all.",
     "expect": "classifier marks not relevant"},
    {"id": "N4", "noise": "Six normal PM10/NO2 readings at two stations.",
     "expect": "below p95; no air-pollution anomaly"},
    {"id": "N5", "noise": "Two hydrometric gauges reading near zero discharge.",
     "expect": "no threshold crossed; no flood signal"},
    {"id": "N6", "noise": "A FIRMS hotspot observed three days ago.",
     "expect": "outside the detector's staleness window; ignored"},
    {"id": "N7", "noise": "A forwarded copy of the first Eilat report.",
     "expect": "same origin collapsed; must not count as corroboration"},
]


# --------------------------------------------------------------------------
# Evidence derived from those events
# --------------------------------------------------------------------------


def _firms(lat: float, lon: float, frp: float, pixels: int, minutes_ago: int,
           confidence: str = "h", satellite: str = "N20") -> dict[str, Any]:
    """One FIRMS overpass, in the exact shape the collector stores."""
    spread = 0.004
    hotspots = [
        {
            "frp": round(frp / pixels, 4),
            "daynight": "D",
            "latitude": round(lat + spread * (index - pixels / 2), 6),
            "longitude": round(lon + spread * (index % 2), 6),
            "satellite": satellite,
            "confidence": confidence,
            "instrument": "VIIRS",
            "firms_source": "VIIRS_NOAA20_NRT",
            "acquisition_date": "",
            "acquisition_time": "",
        }
        for index in range(pixels)
    ]
    return {
        "hotspots": hotspots,
        "peak_frp_mw": frp,
        "hotspot_count": pixels,
        "satellite_sources": ["VIIRS_NOAA20_NRT"],
    }


def _weather(temperature: float, humidity: float, wind: float,
             gusts: float, direction: float) -> dict[str, Any]:
    return {
        "rain": 0.0,
        "weather_code": 0.0,
        "precipitation": 0.0,
        "temperature_2m": temperature,
        "wind_gusts_10m": gusts,
        "wind_speed_10m": wind,
        "wind_direction_10m": direction,
        "relative_humidity_2m": humidity,
        "soil_moisture_0_to_7cm": 0.03,
        "vapour_pressure_deficit": 4.6,
        "et0_fao_evapotranspiration": 0.42,
    }


def _pollution(station: str, channel: str, pollutant: str, value: float,
               lat: float, lon: float, observed: datetime) -> dict[str, Any]:
    # provider_hour_for_observation() rejects anything whose provider timestamp
    # is not the same instant at a +02:00 offset -- the Ministry publishes on
    # Israel standard time, and the check exists so a caller cannot silently
    # relabel an hour through a DST-equivalent offset. Writing +00:00 here,
    # even with the correct instant, fails as `provider_clock_incompatible`
    # and the reading is dropped before any baseline is consulted.
    israel = observed.astimezone(timezone(timedelta(hours=2)))
    return {
        "unit": "µg/m³",
        "valid": True,
        "value": value,
        "location": {"latitude": lat, "longitude": lon},
        "provider": "israel_ministry_environment_air_monitoring",
        "pollutant": pollutant,
        "source_id": f"station:{station}",
        "observed_at": observed.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "unit_source": "reading",
        "collected_at": observed.isoformat(),
        "reading_unit": "µg/m³",
        "metadata_unit": "µg/m³",
        "provider_unit": "µg/m³",
        "quality_policy": "ecoguard-provider-valid-signed-v1",
        "provider_status": "_",
        "quality_control": "preliminary_unvalidated",
        "measurement_unit": "µg/m³",
        "collection_status": "complete",
        "provider_status_id": "1",
        "provider_timestamp": israel.strftime("%Y-%m-%dT%H:%M:%S+02:00"),
        "provider_channel_id": channel,
        "provider_station_id": station,
        "provider_pollutant_id": "1",
    }


def _gauge(station_id: int, name_en: str, name_he: str, lat: float, lon: float,
           discharge: float, height: float, basin: int) -> dict[str, Any]:
    """One hydrometric reading. Thresholds travel with it, as in production."""
    return {
        "stations": [{
            "name_en": name_en,
            "name_he": name_he,
            "latitude": lat,
            "longitude": lon,
            "discharge_m3s": discharge,
            "water_height_m": height,
            "drainage_basin_id": basin,
            "source_station_id": station_id,
            "flow_threshold_2y_m3s": 5.0,
            "flow_threshold_5y_m3s": 20.0,
            "flow_threshold_status": "complete_thresholds",
            "flow_threshold_10y_m3s": 48.0,
            "flow_threshold_20y_m3s": 92.0,
            "flow_threshold_50y_m3s": 165.0,
            "flow_threshold_100y_m3s": 240.0,
            "flow_start_water_level_m": 0.06,
        }],
    }


def _telegram(peer: int, message_id: int, channel: str, title: str,
              body: str, observed: datetime,
              forwarded: dict | None = None) -> dict[str, Any]:
    return {
        "kind": "telegram",
        "peer_id": peer,
        "raw_text": body,
        "edited_at": None,
        "posted_at": observed.isoformat(),
        "source_id": f"telegram:{peer}",
        "message_id": message_id,
        "source_url": f"https://t.me/{channel}/{message_id}",
        "channel_title": title,
        "channel_username": channel,
        "configured_username": channel,
        "source_verification": {
            "role": "unofficial", "tier": "unofficial",
            "event_verified": False, "peer_id_pinned": True,
            "peer_id_verified": True,
        },
        "forwarded_provenance": forwarded,
    }


def _rss(handle: str, display: str, guid: str, title: str, body: str,
         observed: datetime, feed: str) -> dict[str, Any]:
    return {
        "kind": "rss",
        "title": title,
        "handle": handle,
        "summary": body,
        "raw_text": f"{title}\n{body}",
        "item_guid": guid,
        "posted_at": observed.isoformat(),
        "source_id": feed,
        "source_url": guid,
        "display_name": display,
    }


# Real configured sources, so the text lane's joins resolve against `public`.
FIRE_CHANNEL = (-1001411503185, "fireisrael7777", "כבאות והצלה ארצי")
POLICE_CHANNEL = (-1002843129862, "Israel_Police_100", "דוברות משטרת ישראל")
MDA_CHANNEL = (-1001177174722, "mdaisrael", "מגן דוד אדום")
YNET_FEED = "https://www.ynet.co.il/Integration/StoryRss1854.xml"


def build_rows(now: datetime) -> list[tuple[str, str, datetime, dict[str, Any]]]:
    """Every observation the scenario writes: (source, cell_id, observed_at, payload)."""

    def ago(minutes: int) -> datetime:
        return now - timedelta(minutes=minutes)

    def ago_5(minutes: int) -> datetime:
        """Like ago(), snapped down to a 5-minute boundary and whole seconds.

        The Ministry publishes on a five-minute cadence and the baseline family
        is `five_minute_observation`; keeping the seeded clock on the same grid
        keeps the fake rows indistinguishable from real ones.
        """
        moment = now - timedelta(minutes=minutes)
        return moment.replace(minute=moment.minute // 5 * 5, second=0, microsecond=0)

    rows: list[tuple[str, str, datetime, dict[str, Any]]] = []

    # --- A1: Eilat fire, growing over three overpasses --------------------
    eilat_cell = "risk-05000m-r0003-c0014"
    for minutes, frp, pixels in ((95, 45.0, 1), (55, 120.0, 3), (18, 210.0, 5)):
        rows.append(("firms", eilat_cell, ago(minutes),
                     _firms(*EILAT, frp, pixels, minutes)))
    # Fire weather for the same cell: hot, very dry, strong gusts.
    rows.append(("weather", eilat_cell, ago(60), _weather(41.2, 9.0, 24.0, 52.0, 350.0)))

    # --- A2: Carmel fire, moderate ----------------------------------------
    carmel_cell = "risk-05000m-r0074-c0015"
    for minutes, frp, pixels in ((70, 30.0, 1), (25, 65.0, 2)):
        rows.append(("firms", carmel_cell, ago(minutes),
                     _firms(*CARMEL, frp, pixels, minutes)))
    rows.append(("weather", carmel_cell, ago(60), _weather(33.5, 28.0, 14.0, 31.0, 300.0)))

    # --- N6: a stale hotspot, outside the detector's window ---------------
    rows.append(("firms", "risk-05000m-r0050-c0007", now - timedelta(days=3),
                 _firms(31.6688, 34.5743, 80.0, 2, 4320)))

    # --- A3: Nahal Ashalim flood, and two flat gauges (N5) ----------------
    ashalim_cell = "risk-05000m-r0036-c0021"
    # minimum_alert_level is 3: BOTH readings of a consecutive pair must sit at
    # or above the 10-year threshold (48 m3/s here), not the 2- or 5-year. A
    # rise that merely crosses Q5 is real water and deliberately not an alert.
    for minutes, discharge, height in ((58, 0.4, 0.08), (31, 62.0, 2.6), (6, 95.0, 3.4)):
        rows.append(("water_authority_hydrometric_observations", ashalim_cell,
                     ago(minutes),
                     _gauge(378, "Ashalim", "אשלים במעלה",
                            *ASHALIM, discharge, height, 65)))
    for minutes in (62, 36, 11):
        rows.append(("water_authority_hydrometric_observations",
                     "risk-05000m-r0043-c0021", ago(minutes),
                     _gauge(349, "Zeelim", "צאלים",
                            31.3522, 35.3503, 0.0, -0.96, 97)))
        rows.append(("water_authority_hydrometric_observations",
                     "risk-05000m-r0026-c0012", ago(minutes),
                     _gauge(58, "Ramon", "רמון",
                            30.6144, 34.8601, 0.2, -0.18, 68)))

    # --- A4: Negev PM10 episode, after a normal run-up (N4) ---------------
    pm10_cell = "ministry:417:1:PM10:%C2%B5g%2Fm%C2%B3"
    for minutes, value in ((150, 24.0), (110, 27.0), (70, 31.0)):
        rows.append(("air_pollution", pm10_cell, ago_5(minutes),
                     _pollution("417", "1", "PM10", value, *NEGEV_STATION, ago_5(minutes))))
    rows.append(("air_pollution", pm10_cell, ago_5(12),
                 _pollution("417", "1", "PM10", 185.0, *NEGEV_STATION, ago_5(12))))
    # N4: a second station reading normally throughout.
    no2_cell = "ministry:377:8:NO2:%C2%B5g%2Fm%C2%B3"
    # Below station 377's own September NO2 p95, which is 6.2-6.7 at these
    # hours against a median near 3.2. An earlier draft used 8-11 "normal"
    # readings and the detector correctly called them anomalies -- the noise
    # was wrong, not the detector.
    for minutes, value in ((150, 3.1), (90, 3.6), (20, 3.3)):
        rows.append(("air_pollution", no2_cell, ago_5(minutes),
                     _pollution("377", "8", "NO2", value, 29.5545, 34.9492, ago_5(minutes))))

    # --- A1 corroboration: two independent reports, different wording -----
    peer, channel, title = FIRE_CHANNEL
    rows.append((
        "telegram", f"telegram:{peer}:990001", ago(40),
        _telegram(peer, 990001, channel, title,
                  "שריפה גדולה במרכז אילת, כוחות כיבוי רבים במקום",
                  ago(40))))
    ppeer, pchannel, ptitle = POLICE_CHANNEL
    rows.append((
        "telegram", f"telegram:{ppeer}:5001", ago(31),
        _telegram(ppeer, 5001, pchannel, ptitle,
                  "תנועה נעצרה בשדרות התמרים באילת עקב עשן כבד מדליקה סמוכה",
                  ago(31))))
    # N7: a forward of the first report. Same origin, must not corroborate.
    rows.append((
        "telegram", f"telegram:{MDA_CHANNEL[0]}:26001", ago(28),
        _telegram(MDA_CHANNEL[0], 26001, MDA_CHANNEL[1], MDA_CHANNEL[2],
                  "שריפה גדולה במרכז אילת, כוחות כיבוי רבים במקום",
                  ago(28),
                  forwarded={"origin_peer_id": peer, "origin_message_id": 990001})))

    # --- A5: a lone Netanya claim, nothing else sees it -------------------
    rows.append((
        "telegram", f"telegram:{peer}:990014", ago(22),
        _telegram(peer, 990014, channel, title,
                  "דיווח על שריפה במבנה מגורים בנתניה, התושבים פונו",
                  ago(22))))

    # --- N1/N2/N3: what the classifier must decline -----------------------
    rows.append((
        "telegram", f"telegram:{peer}:990020", ago(50),
        _telegram(peer, 990020, channel, title,
                  "שריפה בליכוד: חברי הכנסת יוצאים נגד היו\"ר",
                  ago(50))))
    rows.append((
        "rss", "rss:ynet:demo-a-greece", ago(46),
        _rss("ynet", "ynet — מבזקים", "demo-a-greece",
             "שריפת ענק ביוון",
             "שריפת יערות נרחבת בפאטראס שביוון, אלפים פונו מבתיהם",
             ago(46), YNET_FEED)))
    rows.append((
        "rss", "rss:ynet:demo-a-unrelated", ago(44),
        _rss("ynet", "ynet — מבזקים", "demo-a-unrelated",
             "הבורסה נעלה בעלייה",
             "מדד תל אביב 125 עלה ב-1.2 אחוז במסחר היום",
             ago(44), YNET_FEED)))

    return rows


INSERT = text(
    'INSERT INTO "{schema}".observations '
    "(source, cell_id, location, observed_at, ingested_at, payload) "
    "VALUES (:source, :cell_id, NULL, :observed_at, :ingested_at, "
    "CAST(:payload AS jsonb))"
)


def seed(schema: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Write the scenario into the sandbox schema. Returns what to expect.

    Written with an explicit schema rather than through the search path, so the
    world can be built while the process is still pointed at the live tables.
    """
    moment = now or datetime.now(timezone.utc)
    rows = build_rows(moment)
    statement = text(str(INSERT).replace("{schema}", schema))

    with Session() as session:
        for source, cell_id, observed_at, payload in rows:
            session.execute(statement, {
                "source": source,
                "cell_id": cell_id,
                "observed_at": observed_at,
                # Everything arrives now: the detectors' bookmarks are empty in
                # a freshly cleared sandbox, so `ingested_at > since` needs the
                # rows to look like they have just landed.
                "ingested_at": moment,
                "payload": json.dumps(payload, ensure_ascii=False),
            })
        session.commit()

    by_source: dict[str, int] = {}
    for source, *_ in rows:
        by_source[source] = by_source.get(source, 0) + 1

    return {
        "observations": len(rows),
        "by_source": by_source,
        "seeded_at": moment.isoformat(),
        "expectations": {
            "events": GROUND_TRUTH,
            "silence": EXPECTED_SILENCE,
        },
    }


__all__ = ["GROUND_TRUTH", "EXPECTED_SILENCE", "build_rows", "seed"]
