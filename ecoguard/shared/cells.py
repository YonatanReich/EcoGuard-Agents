"""The cell: the one place every hazard agrees to meet.

Nothing in this system observes a cell. Satellites observe 375 m pixels, air
quality stations observe a point on a roof, gauges observe a river section,
weather models observe a ~10 km grid of their own. A cell is not any of those
resolutions — it is deliberately coarser than all of them, because its job is
not to be precise. Its job is to be **shared**.

That is what makes "anomalous brightness in cell 0087-0029" and "anomalous
PM2.5 in cell 0087-0029" comparable statements. They are not comparable because
brightness and PM2.5 are alike; they are comparable because both have been
resolved onto the same ground. Without a common spatial key a coordinator
cannot tell whether two detectors are describing one event or two, and that is
the entire question it exists to answer.

So every source maps onto the cell from wherever it naturally lives:

    finer than a cell   VIIRS pixels, 250 m surface cells   -> aggregate up
    a point             stations, gauges, a Telegram report -> `cell_for`
    coarser than a cell the 15 km forecast subgrid          -> nearest cell

Properties the rest of the system relies on:

  * **Deterministic.** An id resolves to ground with no lookup and no database.
    `risk-05000m-r0002-c0013` is row 2, column 13 of the 5 km grid, forever.
  * **Stable.** Ids are stored on a quarter-million observation rows. The
    layout may be extended; existing ids may never be renumbered.
  * **Square-ish on the ground, not in degrees.** The longitude step is
    recomputed per row, so a cell is 5.00 km wide at Eilat and at Metula. A
    fixed degree step would leave northern cells visibly squashed.

One wart, stated rather than fixed: the `risk-` prefix is historical, from when
the grid served only fire-risk scanning. The cell is hazard-neutral; the prefix
is not, and renaming it would invalidate every stored row for no gain.

Known limit worth carrying: a square is the wrong shape for water. Flood
behaviour follows drainage basins, and "anomalous rainfall in cell Y" is a
weaker statement than "anomalous brightness in cell Y" because the water does
not stay in the square. Basin-shaped hazards should resolve a basin to the set
of cells it covers rather than pretend a basin is a cell.
"""

from __future__ import annotations

import math
import re
from functools import lru_cache

from ecoguard.shared.grid import (
    GRID_RESOLUTION_KM,
    ISRAEL_RISK_BOUNDS,
    LATITUDE_KM_PER_DEGREE,
    LONGITUDE_KM_PER_DEGREE_AT_EQUATOR,
    GridCell,
    generate_grid,
)
from ecoguard.shared.service_area import ServiceArea

CELL_ID_PATTERN = re.compile(r"^risk-(?P<metres>\d{5})m-r(?P<row>\d{4})-c(?P<column>\d{4})$")


@lru_cache(maxsize=1)
def service_area_cells() -> tuple[GridCell, ...]:
    """The 5 km cells inside the operational area — about 1,200 of them.

    Cached because the point-in-polygon sweep over the full 2,848-cell grid
    takes a moment and the answer only changes when the GeoJSON does.
    """
    area = ServiceArea()
    return tuple(
        cell for cell in generate_grid()
        if area.includes_cell(cell.latitude, cell.longitude)
    )


@lru_cache(maxsize=1)
def _cells_by_position() -> dict[tuple[int, int], GridCell]:
    return {(cell.grid_row, cell.grid_col): cell for cell in service_area_cells()}


@lru_cache(maxsize=1)
def _cells_by_id() -> dict[str, GridCell]:
    return {cell.cell_id: cell for cell in service_area_cells()}


def cell_for(latitude: float, longitude: float) -> str | None:
    """The id of the service-area cell containing a point, or None.

    Inverts generate_grid's row-major layout rather than scanning the grid,
    then confirms the result against the generated cells — so a point outside
    the operational area returns None instead of an id that does not exist.

    This is the function every point-shaped source goes through: a station, a
    gauge, a satellite pixel, a geolocated Telegram report. It is what turns
    "somewhere near here" into a key two detectors can agree on.
    """
    west, south, _, _ = ISRAEL_RISK_BOUNDS
    latitude_step = GRID_RESOLUTION_KM / LATITUDE_KM_PER_DEGREE
    row = math.floor((latitude - south) / latitude_step)
    if row < 0:
        return None

    # The longitude step is computed at the row's own centre latitude, exactly
    # as generate_grid does, so cells stay square as you move north.
    row_latitude = south + (row + 0.5) * latitude_step
    longitude_step = GRID_RESOLUTION_KM / (
        LONGITUDE_KM_PER_DEGREE_AT_EQUATOR * math.cos(math.radians(row_latitude))
    )
    column = math.floor((longitude - west) / longitude_step)
    if column < 0:
        return None

    cell = _cells_by_position().get((row, column))
    return cell.cell_id if cell else None


def cell_by_id(cell_id: str) -> GridCell | None:
    """The cell an id names, or None when it is outside the service area."""
    return _cells_by_id().get(cell_id)


def parse_cell_id(cell_id: str) -> tuple[int, int, int] | None:
    """(resolution_metres, row, column) from an id, or None if unparseable.

    Deliberately tolerant of ids the service area does not contain — parsing
    asks what an id *means*, which is a different question from whether we
    collect there. A caller that needs both checks both.

    Returns None rather than raising for `telegram`-style ids like
    `fire_alerts_il:4821`, which are message identities and not places at all.
    That case is common enough that it is a return value, not an exception.
    """
    match = CELL_ID_PATTERN.match(cell_id)
    if not match:
        return None
    return (
        int(match.group("metres")),
        int(match.group("row")),
        int(match.group("column")),
    )


def is_cell_id(cell_id: str) -> bool:
    """Whether a string names a place at all.

    `observations.cell_id` holds grid ids for every source except telegram,
    whose ids are `channel:message_id`. Any query that joins cell_id to
    geography must filter those out, and this is the check to use.
    """
    return CELL_ID_PATTERN.match(cell_id) is not None


def bounds_of(cell_id: str) -> tuple[float, float, float, float] | None:
    """(west, south, east, north) of a cell, or None if the id is not a cell.

    Recomputed from the grid arithmetic rather than stored, so it cannot drift
    from what `generate_grid` produced.
    """
    parsed = parse_cell_id(cell_id)
    if parsed is None:
        return None
    metres, row, column = parsed

    resolution_km = metres / 1000
    west, south, _, _ = ISRAEL_RISK_BOUNDS
    latitude_step = resolution_km / LATITUDE_KM_PER_DEGREE
    cell_south = south + row * latitude_step

    # The same per-row longitude step generate_grid used, evaluated at this
    # row's centre latitude.
    row_latitude = cell_south + latitude_step / 2
    longitude_step = resolution_km / (
        LONGITUDE_KM_PER_DEGREE_AT_EQUATOR * math.cos(math.radians(row_latitude))
    )
    cell_west = west + column * longitude_step
    return (cell_west, cell_south, cell_west + longitude_step, cell_south + latitude_step)


def neighbours(cell_id: str, radius: int = 1) -> tuple[str, ...]:
    """Ids of the cells around one, within `radius` steps, excluding itself.

    The coordinator needs this because events do not respect cell edges. A fire
    on a boundary lights pixels in two cells, and a satellite detection and a
    ground report of the same fire routinely land one cell apart — treating
    those as two events is the most common way a deduplicator fails.

    Only cells inside the service area are returned, so an edge cell simply has
    fewer neighbours rather than reporting ids that do not exist.
    """
    parsed = parse_cell_id(cell_id)
    if parsed is None:
        return ()
    _, row, column = parsed
    by_position = _cells_by_position()

    return tuple(
        by_position[(row + row_offset, column + column_offset)].cell_id
        for row_offset in range(-radius, radius + 1)
        for column_offset in range(-radius, radius + 1)
        if (row_offset or column_offset)
        and (row + row_offset, column + column_offset) in by_position
    )


def are_adjacent(first: str, second: str, radius: int = 1) -> bool:
    """Whether two cells are the same cell or within `radius` steps of it.

    "Same place" for corroboration purposes. Same cell counts as adjacent to
    itself on purpose — every caller asking this wants one answer covering
    both, and forcing them to write `a == b or are_adjacent(a, b)` is how the
    equality case gets forgotten.
    """
    if first == second:
        return True
    left, right = parse_cell_id(first), parse_cell_id(second)
    if left is None or right is None:
        return False
    return (
        abs(left[1] - right[1]) <= radius
        and abs(left[2] - right[2]) <= radius
    )
