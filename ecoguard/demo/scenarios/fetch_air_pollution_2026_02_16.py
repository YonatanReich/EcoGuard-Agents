"""Download the evidence for the 16 February 2026 air-pollution replay.

Run once; the output is committed so the demo never depends on the Ministry
API on the day it is shown:

    python -m ecoguard.demo.scenarios.fetch_air_pollution_2026_02_16

What it keeps, all from the Ministry of Environmental Protection's own API:

  readings   every active station's five-minute readings, 11:05-11:30 on
             16 Feb 2026 (Ministry clock, UTC+2), for the five pollutants the
             detector judges. Raw, exactly as the API returned them; the
             production normaliser turns them into rows at seed time.
  stations   the station metadata and status vocabulary the normaliser needs.
  index      the Ministry index for each of those readings. The provider no
             longer serves its index for this date (indexFastSrv answers 204),
             so it is reconstructed from the same stations' preceding 24 hours
             of readings with the Ministry's published method
             (shared/ministry_index_formula.py) and marked `reconstructed`.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

from ecoguard.shared.ministry_air_quality_client import (
    MINISTRY_INDEX_CLOCK,
    MinistryAirQualityClient,
)
from ecoguard.shared.ministry_index_formula import AVERAGING_MINUTES, index

OUTPUT = Path(__file__).with_name("air_pollution_2026_02_16_data.json")

# The Ministry's warning went out at 11:32 on 16 Feb 2026. The replay stops at
# 11:30: what the collector had stored by then is what the system would have
# acted on.
CHECKPOINT = datetime(2026, 2, 16, 11, 30, tzinfo=MINISTRY_INDEX_CLOCK)
WINDOW_START = CHECKPOINT - timedelta(minutes=25)
HISTORY_START = WINDOW_START - timedelta(minutes=1440)

# What detectors/air_pollution/live_baseline.py evaluates; the rest are stored
# by the collector and never judged.
EVALUATED = {"PM10", "PM2.5", "NO2", "O3", "SO2"}

# Table 1 of the Ministry's method: category names as indexFastSrv labels them.
CATEGORIES = ((51, "טובה", "#00e400"), (0, "בינונית", "#ffff00"),
              (-200, "נמוכה", "#ff0000"), (-400, "נמוכה מאוד", "#8f3f97"))


def _category(value: float) -> tuple[str, str]:
    for floor, name, colour in CATEGORIES:
        if value >= floor:
            return name, colour
    return CATEGORIES[-1][1], CATEGORIES[-1][2]


def _clock(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M")


def main() -> None:
    """Fetch, reconstruct, and write the committed data file."""
    load_dotenv()
    client = MinistryAirQualityClient()
    stations = [
        station.model_dump(mode="json") for station in client.get_station_metadata().stations
        if station.active and {
            monitor.pollutant for monitor in station.monitors if monitor.active
        } & EVALUATED
    ]
    statuses = client.get_statuses()

    readings, indexes = {}, {}
    for station in stations:
        sid = station["provider_station_id"]
        try:
            rows = client._get_json(f"stations/{sid}/data", params={
                "from": _clock(HISTORY_START), "to": _clock(CHECKPOINT),
            }).get("data") or []
        except Exception as error:
            print(f"station {sid}: {getattr(error, 'category', error)}")
            continue
        series: dict[str, list[tuple[datetime, float, str]]] = {}
        window = []
        for row in rows:
            at = datetime.fromisoformat(row["datetime"])
            channels = [c for c in row["channels"] if c.get("name") in EVALUATED]
            for channel in channels:
                if channel.get("name") in AVERAGING_MINUTES and channel.get("valid") is True \
                        and isinstance(channel.get("value"), (int, float)) and channel["value"] >= 0:
                    series.setdefault(channel["name"], []).append((at, channel["value"], str(channel["id"])))
            if WINDOW_START <= at <= CHECKPOINT and channels:
                window.append({"datetime": row["datetime"], "channels": channels})
        if not window:
            continue
        readings[sid] = window

        entries = []
        for row in window:
            at = datetime.fromisoformat(row["datetime"])
            subs = []
            for pollutant, points in series.items():
                recent = [v for t, v, _ in points
                          if at - timedelta(minutes=AVERAGING_MINUTES[pollutant]) < t <= at]
                # The Ministry's method needs a full day; refuse a thin one
                # rather than publish an index from a few hours.
                if len(recent) < 0.75 * AVERAGING_MINUTES[pollutant] / 5:
                    continue
                mean = round(sum(recent) / len(recent), 1)
                subs.append({
                    "MonitorId": int(points[-1][2]), "pollutant": pollutant,
                    "index": index(pollutant, mean), "value": mean,
                    "PollutantTimeBase": AVERAGING_MINUTES[pollutant],
                    "datetime": row["datetime"], "reconstructed": True,
                })
            if not subs:
                continue
            worst = min(subs, key=lambda item: item["index"])
            name, colour = _category(worst["index"])
            entries.append({
                "stationId": int(sid), "index": worst["index"], "pollutant": worst["pollutant"],
                "description": name, "color": colour, "datetime": row["datetime"],
                "reconstructed": True, "indexes": subs,
            })
        if entries:
            indexes[sid] = {"stationId": int(sid), "data": entries}
        time.sleep(0.2)

    OUTPUT.write_text(json.dumps({
        "_about": __doc__.strip().splitlines()[0],
        "checkpoint": CHECKPOINT.isoformat(),
        "warning": {
            "issued": "2026-02-16T11:32:00+02:00",
            "url": "https://www.gov.il/he/pages/air-pollution-alert-feb-16-2026",
        },
        "stations": [s for s in stations if s["provider_station_id"] in readings],
        "statuses": statuses,
        "readings": readings,
        "index": indexes,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUTPUT}: {len(readings)} stations, {len(indexes)} with an index")


if __name__ == "__main__":
    main()
