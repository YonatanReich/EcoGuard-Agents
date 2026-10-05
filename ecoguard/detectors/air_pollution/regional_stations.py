"""Which monitoring stations speak for each Ministry region, and only they raise advisories.

A nationwide episode lights up every station at once - on 16 Feb 2026 that
was 29 incidents, 29 cards and 29 planner calls for what the Ministry issued
as one warning, and live the collector stores ~200 stations every five
minutes. So the country is read through the fewest stations that cover it:
for each of the Ministry's own regions (the `regionId` its API tags every
station with), the smallest set whose active baselines cover the four
pollutants that drive episodes - PM10 and PM2.5 (dust, smoke), NO2 (traffic),
O3 (summer photochemistry). One station where one covers them, a second only
where it fills a gap: 18 stations for 13 regions.

How they were picked (2026-10-05, from the live station metadata and the
active five-minute baselines):
  - coverage first: a station counts only for pollutants it has a baseline
    for, because without one the detector cannot judge it at all;
  - then the operator: the Ministry, then a city or regional association,
    then infrastructure (power plants); never a quarry or cement works, whose
    fence-line monitors read their own dust as regional pollution.

Every station of a region reports under the region's anchor cell (its first
station's), so a region is one incident and one card however many of its
stations exceed, and two of them agreeing corroborates it. Each signal keeps
its own station's true location.

The cost is local: a hotspot by a station not listed here (an industrial
release in Haifa Bay, say) raises no advisory of its own. The collector still
stores every station, so history and baselines are complete and changing a
pick here is the whole change.

Gaps that remain because no station in the region has the baseline: Shomron
and Western Galilee have no PM2.5, Upper Galilee no PM10, Eilat no PM2.5,
Lower Galilee no PM2.5 outside quarry monitors. Be'er Sheva (station 6) has
no particulate baseline at all, so Arad speaks for the Northern Negev.
"""

from __future__ import annotations

# Ministry region id -> (region, anchor cell, [(station id, station), ...]).
# The first station is the region's primary; its cell is the anchor.
REGIONS: dict[str, tuple[str, str, list[tuple[str, str]]]] = {
    "2": ("חיפה וקריות", "risk-05000m-r0074-c0015", [("86", "נווה שאנן")]),
    "4": ("שרון כרמל", "risk-05000m-r0061-c0012", [
        ("154", "רחוב אחוזה, רעננה"),       # Ministry: NO2, PM2.5
        ("378", "קציר"),                     # power plant: PM10, NO2, O3
    ]),
    "5": ("שומרון", "risk-05000m-r0059-c0018", [("3", "אריאל")]),
    "6": ("שפלה פנימית", "risk-05000m-r0055-c0013", [("367", "בית חשמונאי")]),
    "7": ("גוש דן", "risk-05000m-r0060-c0011", [
        ("39", "אוניברסיטה, תל אביב"),       # Ministry: PM10, NO2, O3
        ("2", "רחוב לחי, תל אביב"),          # Ministry: PM2.5
    ]),
    "8": ("ירושלים", "risk-05000m-r0052-c0019", [
        ("13", "בקעה"),                      # Ministry: PM10, PM2.5, NO2
        ("36", "כיכר ספרא"),                 # Ministry: O3
    ]),
    "9": ("אזור יהודה", "risk-05000m-r0049-c0017", [("21", "גוש עציון")]),
    "10": ("מישור החוף הדרומי", "risk-05000m-r0052-c0008", [
        ("405", "שדרות ירושלים, אשדוד"),     # city association: PM2.5, NO2
        ("61", "ניר גלים"),                  # power plant: PM10, O3
    ]),
    "11": ("צפון הנגב", "risk-05000m-r0040-c0019", [("158", "נגב מזרחי, ערד")]),
    "12": ("אילת", "risk-05000m-r0003-c0014", [
        ("304", "שכונת שחמון"),              # port: PM10
        ("377", "בית ספר גולדווטר"),         # power plant: NO2, O3
    ]),
    "13": ("גליל תחתון והעמקים", "risk-05000m-r0070-c0020", [("1", "עפולה")]),
    "14": ("גליל מערבי", "risk-05000m-r0077-c0020", [("11", "גליל מערבי, כרמיאל")]),
    "15": ("גליל עליון והגולן", "risk-05000m-r0084-c0025", [("387", "מכללת תל חי")]),
}

_BY_STATION = {
    station: (region, anchor)
    for region, anchor, stations in REGIONS.values()
    for station, _ in stations
}

DESIGNATED_STATIONS = frozenset(_BY_STATION)


def region_of(station_id: str) -> str | None:
    """The Ministry region a designated station speaks for, or None."""
    entry = _BY_STATION.get(str(station_id))
    return entry[0] if entry else None


def anchor_cell(station_id: str) -> str | None:
    """The cell every station of this station's region reports under, or None."""
    entry = _BY_STATION.get(str(station_id))
    return entry[1] if entry else None
