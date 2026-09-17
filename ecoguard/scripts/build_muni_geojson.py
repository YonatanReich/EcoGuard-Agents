"""Build muni_il.geojson — Israel's local authority boundaries, web-ready.

Source is the Ministry of Interior's seamless jurisdiction layer
(גבולות שיפוט - רצף), a 51 MB shapefile of 411 survey-grade polygons in the
Israel TM Grid. Three things have to happen before a browser can use it:

  reproject   ITM (EPSG:2039, metres) -> WGS84, which the map speaks
  dissolve    411 polygons -> 285 authorities, since 62 of them are multipart
              and one label per authority beats one per fragment
  simplify    1.6M vertices -> ~50k, taking the file from 31 MB to under 1 MB

The projection is done here with a closed-form inverse Transverse Mercator
rather than pyproj/geopandas: neither is installed, and every parameter needed
is sitting in muni_il.prj. It is validated on the way past — see main().

Run from the repo root:

    python ecoguard/scripts/build_muni_geojson.py

Output is checked in, so this only needs re-running if the Ministry publishes a
new edition of the layer.
"""

from __future__ import annotations

import json
import math
import re
import struct
from collections import defaultdict
from pathlib import Path

from shapely import set_precision
from shapely.geometry import MultiPolygon, Polygon, mapping
from shapely.ops import transform, unary_union

REFERENCE = Path("ecoguard/data/reference")
SOURCE = REFERENCE / "גבולות שיפוט - רצף" / "שכבות מידע (Arc View)" / "muni_il"
OUTPUT = REFERENCE / "muni_il.geojson"

# Simplification tolerance, in ITM metres — the grid is metric, so this is a
# real ground distance rather than a fudged number of degrees. 20 m is below
# one screen pixel until roughly zoom 13 and costs 97% of the file size.
TOLERANCE_M = 20

# Coordinate output grid, also in metres, applied through shapely so that rings
# collapsing under it are dropped properly instead of left degenerate.
GRID_M = 1


# ---------------------------------------------------------------------------
# Israel TM Grid, read straight off muni_il.prj
# ---------------------------------------------------------------------------

A = 6378137.0  # GRS 1980 semi-major axis
INVERSE_FLATTENING = 298.257222101
LAT_ORIGIN = math.radians(31.73439361111111)
LON_ORIGIN = math.radians(35.20451694444445)
SCALE_FACTOR = 1.0000067
FALSE_EASTING = 219529.584
FALSE_NORTHING = 626907.39

_F = 1 / INVERSE_FLATTENING
_E2 = 2 * _F - _F * _F
_EP2 = _E2 / (1 - _E2)
_E1 = (1 - math.sqrt(1 - _E2)) / (1 + math.sqrt(1 - _E2))


def _meridional_arc(phi: float) -> float:
    """Distance along the meridian from the equator to latitude `phi`."""
    return A * (
        (1 - _E2 / 4 - 3 * _E2**2 / 64 - 5 * _E2**3 / 256) * phi
        - (3 * _E2 / 8 + 3 * _E2**2 / 32 + 45 * _E2**3 / 1024) * math.sin(2 * phi)
        + (15 * _E2**2 / 256 + 45 * _E2**3 / 1024) * math.sin(4 * phi)
        - (35 * _E2**3 / 3072) * math.sin(6 * phi)
    )


_M0 = _meridional_arc(LAT_ORIGIN)


def itm_to_wgs84(east: float, north: float) -> tuple[float, float]:
    """Inverse Transverse Mercator (Snyder). ITM metres in, lon/lat degrees out."""
    m = _M0 + (north - FALSE_NORTHING) / SCALE_FACTOR
    mu = m / (A * (1 - _E2 / 4 - 3 * _E2**2 / 64 - 5 * _E2**3 / 256))

    # Footprint latitude: the latitude whose meridional arc equals `m`.
    phi1 = (
        mu
        + (3 * _E1 / 2 - 27 * _E1**3 / 32) * math.sin(2 * mu)
        + (21 * _E1**2 / 16 - 55 * _E1**4 / 32) * math.sin(4 * mu)
        + (151 * _E1**3 / 96) * math.sin(6 * mu)
        + (1097 * _E1**4 / 512) * math.sin(8 * mu)
    )

    sin1, cos1, tan1 = math.sin(phi1), math.cos(phi1), math.tan(phi1)
    c1 = _EP2 * cos1**2
    t1 = tan1**2
    n1 = A / math.sqrt(1 - _E2 * sin1**2)
    r1 = A * (1 - _E2) / (1 - _E2 * sin1**2) ** 1.5
    d = (east - FALSE_EASTING) / (n1 * SCALE_FACTOR)

    lat = phi1 - (n1 * tan1 / r1) * (
        d**2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * _EP2) * d**4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1**2 - 252 * _EP2 - 3 * c1**2) * d**6 / 720
    )
    lon = LON_ORIGIN + (
        d
        - (1 + 2 * t1 + c1) * d**3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1**2 + 8 * _EP2 + 24 * t1**2) * d**5 / 120
    ) / cos1

    return math.degrees(lon), math.degrees(lat)


def _check_projection() -> None:
    """Anchor the transform before it is trusted on 1.6M coordinates.

    The false easting/northing *is* the grid origin by definition, so it has to
    map back to the origin lat/lon exactly; a point 100 km north of it has to
    stay on the same meridian and gain ~0.9 degrees of latitude. Between them
    these catch a mistyped parameter or a dropped term.
    """
    lon, lat = itm_to_wgs84(FALSE_EASTING, FALSE_NORTHING)
    assert abs(lon - math.degrees(LON_ORIGIN)) < 1e-9, lon
    assert abs(lat - math.degrees(LAT_ORIGIN)) < 1e-9, lat

    lon_n, lat_n = itm_to_wgs84(FALSE_EASTING, FALSE_NORTHING + 100_000)
    assert abs(lon_n - math.degrees(LON_ORIGIN)) < 1e-6, lon_n
    assert 0.88 < lat_n - lat < 0.92, lat_n - lat


# ---------------------------------------------------------------------------
# Shapefile reading — stdlib struct, no fiona
# ---------------------------------------------------------------------------

def read_dbf(path: Path) -> list[dict[str, str]]:
    raw = path.read_bytes()
    record_count, header_len, record_len = struct.unpack("<IHH", raw[4:12])

    fields, cursor = [], 32
    while raw[cursor] != 0x0D:
        name = raw[cursor:cursor + 11].split(b"\0")[0].decode("utf-8")
        fields.append((name, raw[cursor + 16]))
        cursor += 32

    rows = []
    for i in range(record_count):
        start = header_len + i * record_len
        # Byte 0 of each record is the deletion flag, hence the +1.
        offset, row = start + 1, {}
        for name, length in fields:
            row[name] = raw[offset:offset + length].decode("utf-8", "replace").strip()
            offset += length
        rows.append(row)
    return rows


def read_polygons(path: Path) -> list[Polygon | MultiPolygon]:
    raw = path.read_bytes()
    shapes, cursor = [], 100  # 100-byte file header

    while cursor < len(raw):
        content_len = struct.unpack(">I", raw[cursor + 4:cursor + 8])[0]
        body = raw[cursor + 8:cursor + 8 + content_len * 2]

        # Shape type 15 is PolygonZ: identical x/y layout to plain Polygon (5),
        # with Z and optional M arrays trailing after the points. Reading only
        # the x/y prefix handles both, and the Z values are of no use on a map.
        part_count, point_count = struct.unpack("<II", body[36:44])
        starts = list(struct.unpack(f"<{part_count}I", body[44:44 + 4 * part_count]))
        starts.append(point_count)

        xy_offset = 44 + 4 * part_count
        xy = struct.unpack(
            f"<{2 * point_count}d", body[xy_offset:xy_offset + 16 * point_count]
        )
        rings = [
            [(xy[2 * j], xy[2 * j + 1]) for j in range(starts[k], starts[k + 1])]
            for k in range(part_count)
        ]

        # A shapefile polygon record is a bag of rings — clockwise outer,
        # counter-clockwise hole. Unioning them lets shapely work the nesting
        # out instead of this code re-deriving winding rules.
        shapes.append(
            unary_union([Polygon(r).buffer(0) for r in rings if len(r) >= 4])
        )
        cursor += 8 + content_len * 2

    return shapes


def main() -> None:
    _check_projection()

    rows = read_dbf(SOURCE.with_suffix(".dbf"))
    shapes = read_polygons(SOURCE.with_suffix(".shp"))
    assert len(rows) == len(shapes), f"{len(rows)} records vs {len(shapes)} shapes"

    # 62 authorities are split across several polygons — exclaves, or a council
    # whose land is interrupted by a city carved out of it. Group first so each
    # authority becomes one feature, and the map draws one label for it.
    grouped: dict[str, list] = defaultdict(list)
    attributes: dict[str, dict[str, str]] = {}
    for row, geom in zip(rows, shapes):
        name = row["Muni_Heb"]
        grouped[name].append(geom)
        attributes.setdefault(name, row)

    features = []
    for name, geoms in grouped.items():
        merged = unary_union(geoms).simplify(TOLERANCE_M)

        # Snap to the output grid here, in projected metres and before
        # reprojection: rounding the lon/lat text afterwards collapses sliver
        # rings to two distinct points and leaves invalid geometry behind,
        # while set_precision drops those slivers properly.
        merged = set_precision(merged, GRID_M)
        if merged.is_empty:
            continue

        merged = transform(
            lambda xs, ys, zs=None: tuple(
                zip(*(itm_to_wgs84(x, y) for x, y in zip(xs, ys)))
            ),
            merged,
        )
        if isinstance(merged, Polygon):
            merged = MultiPolygon([merged])

        row = attributes[name]
        features.append({
            "type": "Feature",
            "properties": {
                "name": name,
                "name_en": row["Muni_Eng"],
                "type": row["Sug_Muni"],
                "district": row["Machoz"],
                # CBS code where there is one; the Interior code otherwise.
                # Regional councils and unincorporated areas have no CBS code.
                "code": row["CR_LAMAS"] or row["CR_PNIM"],
            },
            "geometry": mapping(merged),
        })

    features.sort(key=lambda f: f["properties"]["name"])
    text = json.dumps(
        {"type": "FeatureCollection", "features": features},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    # float64 leaves 34.78123400000001 in the output; nothing needs 9 decimals
    # of a degree (0.1 mm), and trimming to 5 (~1 m) is a third of the bytes.
    text = re.sub(r"-?\d+\.\d{6,}", lambda m: f"{float(m.group()):.5f}", text)

    OUTPUT.write_text(text, encoding="utf-8")
    print(f"{len(features)} authorities -> {OUTPUT} ({len(text) / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
