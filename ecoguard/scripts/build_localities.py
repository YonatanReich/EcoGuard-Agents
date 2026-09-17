"""Build settlement polygons for Israel, the West Bank and the Golan, from OSM.

The Ministry of Interior layer (muni_il) stops at local authorities: 81% of the
country's area is regional councils, and a regional council is one polygon
covering dozens of separate villages. For spread analysis that is the wrong
granularity — a forecast ring intersected against מטה יהודה tells you 477 km²
of "affected" and names no village. This builds the missing level: one polygon
per actual settlement, including the West Bank ones the Ministry layer omits
entirely.

OpenStreetMap is the source because it is the only one that covers all three
territories, is current, and is redistributable (ODbL — attribution required).
Settlements arrive two ways:

  place polygons   a way or relation tagged place=city|town|village|...
                   1,700-odd of these, and the preferred source.
  built-up         a place *node* with no polygon, matched to the residential
                   landuse around it. OSM maps a town as many small blocks
                   split by streets, so the blocks are morphologically closed
                   (dilate, union, erode) into one footprint before matching.

Output geometry is Polygon, never MultiPolygon, because exposure.load_localities
skips anything else; a settlement mapped in disjoint parts becomes one feature
per part, sharing a name and carrying a suffixed locality_id.

Run from the repo root:

    python ecoguard/scripts/build_localities.py            # uses cached OSM
    python ecoguard/scripts/build_localities.py --refresh  # re-downloads
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

from shapely import set_precision
from shapely.geometry import MultiPolygon, Point, Polygon, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

REFERENCE = Path("ecoguard/data/reference")
CACHE = REFERENCE / ".osm_cache"
OUTPUT = REFERENCE / "localities_osm.geojson"
DISTRICTS = REFERENCE / "fire_districts.geojson"
LEGACY = REFERENCE / "localities.geojson"

OVERPASS = "https://overpass-api.de/api/interpreter"
USER_AGENT = "EcoGuard/1.0 (wildfire early warning; +https://github.com/)"
BBOX = "29.40,34.20,33.45,35.95"

PLACE_KINDS = "city|town|village|hamlet|suburb|neighbourhood|isolated_dwelling|farm"
NODE_KINDS = "city|town|village|hamlet|isolated_dwelling|farm"

# Closing distance for residential blocks, in degrees (~30 m at this latitude).
# Wide enough to bridge the street between two blocks of one village, narrow
# enough that it does not weld neighbouring villages together.
CLOSE_DEG = 0.0003

# A closed footprint larger than this is a conurbation that swallowed several
# settlements, not one village. Such a match is rejected rather than trusted.
MAX_FOOTPRINT_KM2 = 40.0

# How far a place node may sit outside its own built-up area and still be
# matched to it (~150 m). Town-centre nodes land on roads and squares.
SNAP_DEG = 0.0015

# Simplification, in degrees (~10 m). Settlements are small and a kibbutz is
# only a few hundred metres across, so this is finer than the muni layer's.
SIMPLIFY_DEG = 0.0001

# Output coordinate grid (~1 m), matching the 5 decimals written to the file.
COORD_GRID_DEG = 1e-5

QUERIES = {
    "polys": f'[out:json][timeout:600];('
             f'way["place"~"^({PLACE_KINDS})$"]({BBOX});'
             f'relation["place"~"^({PLACE_KINDS})$"]({BBOX});'
             f');out geom;',
    "points": f'[out:json][timeout:600];'
              f'node["place"~"^({NODE_KINDS})$"]({BBOX});out tags center;',
    "landuse": f'[out:json][timeout:900];('
               f'way["landuse"="residential"]({BBOX});'
               f'relation["landuse"="residential"]({BBOX});'
               f');out geom;',
}


def fetch(name: str, refresh: bool) -> list[dict]:
    """Download one Overpass query, caching the raw response.

    The public instance is frequently saturated and answers 504; that is load,
    not a bad query, so this retries with a widening backoff rather than
    failing the build.
    """
    path = CACHE / f"{name}.json"
    if path.exists() and not refresh:
        print(f"  {name}: cached ({path.stat().st_size / 1e6:.1f} MB)")
        return json.loads(path.read_text(encoding="utf-8"))["elements"]

    CACHE.mkdir(parents=True, exist_ok=True)
    body = urllib.parse.urlencode({"data": QUERIES[name]}).encode()
    for attempt in range(1, 7):
        request = urllib.request.Request(
            OVERPASS, data=body, headers={"User-Agent": USER_AGENT}
        )
        try:
            with urllib.request.urlopen(request, timeout=900) as response:
                payload = response.read().decode("utf-8")
            if payload.lstrip().startswith("{"):
                path.write_text(payload, encoding="utf-8")
                print(f"  {name}: fetched ({len(payload) / 1e6:.1f} MB)")
                return json.loads(payload)["elements"]
            raise ValueError("non-JSON response")
        except Exception as error:  # noqa: BLE001 - any failure is a retry
            wait = attempt * 20
            print(f"  {name}: attempt {attempt} failed ({error}); waiting {wait}s")
            time.sleep(wait)
    raise SystemExit(f"{name}: Overpass unavailable after 6 attempts")


def _ring(coords) -> list[tuple[float, float]]:
    return [(c["lon"], c["lat"]) for c in coords or ()]


def stitch(ways: list[list[tuple[float, float]]]) -> list[list[tuple[float, float]]]:
    """Join member ways end-to-end into closed rings.

    An OSM multipolygon relation rarely hands you closed rings. A town outline
    is normally one ring split across several open ways, in arbitrary order and
    arbitrary direction, because the segments are shared with roads and
    neighbouring boundaries. Treating each member as its own polygon turns one
    town into a handful of slivers, so they have to be walked and joined.
    """
    pending = [list(w) for w in ways if len(w) >= 2]
    rings = []
    while pending:
        current = pending.pop()
        while current[0] != current[-1]:
            for index, candidate in enumerate(pending):
                if candidate[0] == current[-1]:
                    current += candidate[1:]
                elif candidate[-1] == current[-1]:
                    current += candidate[-2::-1]
                elif candidate[-1] == current[0]:
                    current = candidate[:-1] + current
                elif candidate[0] == current[0]:
                    current = candidate[:0:-1] + current
                else:
                    continue
                pending.pop(index)
                break
            else:
                break  # nothing joins on: an unclosed ring, discard below
        if current[0] == current[-1] and len(current) >= 4:
            rings.append(current)
    return rings


def build_geometry(element: dict):
    """An OSM way or multipolygon relation as a shapely geometry."""
    if element["type"] == "way":
        points = _ring(element.get("geometry"))
        return Polygon(points).buffer(0) if len(points) >= 4 else None

    outer_ways, inner_ways = [], []
    for member in element.get("members", ()):
        points = _ring(member.get("geometry"))
        if len(points) < 2:
            continue
        target = inner_ways if member.get("role") == "inner" else outer_ways
        target.append(points)

    outers = [Polygon(r).buffer(0) for r in stitch(outer_ways)]
    inners = [Polygon(r).buffer(0) for r in stitch(inner_ways)]
    if not outers:
        return None
    geometry = unary_union(outers)
    if inners:
        geometry = geometry.difference(unary_union(inners))
    return None if geometry.is_empty else geometry


def km2(geometry, latitude: float) -> float:
    """Rough metric area. Degrees are not equal-area, so scale longitude."""
    return (geometry.area * (111_320 ** 2)
            * math.cos(math.radians(latitude)) / 1e6)


def slugify(name: str, fallback: str) -> str:
    """A stable ASCII id. Hebrew has no useful transliteration here, so names
    that produce nothing usable fall back to the OSM element id."""
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = decomposed.encode("ascii", "ignore").decode().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")
    return slug or fallback


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true",
                        help="re-download from Overpass instead of using the cache")
    args = parser.parse_args()

    print("Fetching OSM data:")
    polys = fetch("polys", args.refresh)
    points = fetch("points", args.refresh)
    landuse = fetch("landuse", args.refresh)

    # The fire service's districts already describe exactly the ground in
    # question — Israel, the West Bank and the Golan — so they serve as the
    # clip mask and this script needs no political boundary of its own.
    mask = unary_union([shape(f["geometry"])
                        for f in json.loads(DISTRICTS.read_text(encoding="utf-8"))
                        ["features"]])

    # --- settlements that already have a polygon ---
    settlements = []
    for element in polys:
        geometry = build_geometry(element)
        if geometry is None or geometry.is_empty or not geometry.is_valid:
            continue
        if not mask.intersects(geometry.representative_point()):
            continue
        tags = element.get("tags", {})
        if not tags.get("name"):
            continue
        settlements.append((tags, geometry, "place"))
    print(f"\nplace polygons inside mask: {len(settlements)}")

    # --- built-up footprints, for the settlements that do not ---
    blocks = [g for g in (build_geometry(e) for e in landuse)
              if g is not None and g.is_valid and not g.is_empty]
    closed = unary_union(blocks).buffer(CLOSE_DEG).buffer(-CLOSE_DEG)
    footprints = list(closed.geoms) if hasattr(closed, "geoms") else [closed]
    print(f"residential blocks: {len(blocks)} -> {len(footprints)} closed footprints")

    tree = STRtree(footprints)
    covered = {tags["name"] for tags, _, _ in settlements}

    resolved = rejected = 0
    for node in points:
        tags = node.get("tags", {})
        name = tags.get("name")
        if not name or name in covered:
            continue
        where = Point(node["lon"], node["lat"])
        if not mask.intersects(where):
            continue
        if any(g.contains(where) for _, g, _ in settlements):
            continue

        # A place node is placed on the town centre, which is as often a road
        # junction or a square as it is a house — so it routinely falls just
        # outside the residential blocks. Accept the footprint it sits in, or
        # failing that the nearest one within SNAP_DEG.
        hits = [footprints[i] for i in tree.query(where)
                if footprints[i].contains(where)]
        if not hits:
            hits = sorted(
                (footprints[i] for i in tree.query(where.buffer(SNAP_DEG))
                 if footprints[i].distance(where) <= SNAP_DEG),
                key=lambda g: g.distance(where),
            )
        if not hits:
            continue
        footprint = hits[0]
        if km2(footprint, where.y) > MAX_FOOTPRINT_KM2:
            rejected += 1
            continue
        settlements.append((tags, footprint, "landuse"))
        covered.add(name)
        resolved += 1
    print(f"resolved from built-up land: {resolved} (rejected {rejected} as conurbations)")

    # Populations from the stub this supersedes, so replacing it loses nothing.
    legacy = {}
    if LEGACY.exists():
        for feature in json.loads(LEGACY.read_text(encoding="utf-8"))["features"]:
            properties = feature["properties"]
            if properties.get("name_he"):
                legacy[properties["name_he"]] = properties

    # OSM often carries the same settlement twice — a place=city relation and a
    # place=suburb or boundary-derived one over the same ground. Same name plus
    # overlapping geometry means one settlement mapped twice, so keep the
    # larger; same name with no overlap is two real places and both stay.
    settlements.sort(key=lambda item: item[1].area, reverse=True)
    deduped: list[tuple[dict, object, str]] = []
    for tags, geometry, source in settlements:
        # Match on the Hebrew name: the same city is routinely tagged with a
        # Hebrew `name` on one object and a Latin one on another, so comparing
        # `name` alone lets a duplicate through.
        name = tags.get("name:he") or tags.get("name")
        if any(name == (other[0].get("name:he") or other[0].get("name"))
               and other[1].intersects(geometry)
               for other in deduped):
            continue
        deduped.append((tags, geometry, source))
    print(f"after de-duplication: {len(deduped)} settlements "
          f"({len(settlements) - len(deduped)} duplicates dropped)")
    settlements = deduped

    features, seen = [], Counter()
    for tags, geometry, source in settlements:
        geometry = geometry.simplify(SIMPLIFY_DEG, preserve_topology=True)
        # Snap to the coordinate grid the file is written on. Rounding the
        # serialised text instead would drag vertices across each other and
        # emit self-intersecting rings; set_precision resolves that
        # topologically. buffer(0) mops up anything left over.
        geometry = set_precision(geometry, COORD_GRID_DEG)
        if not geometry.is_valid:
            geometry = geometry.buffer(0)
        if geometry.is_empty:
            continue
        parts = (list(geometry.geoms)
                 if isinstance(geometry, MultiPolygon) else [geometry])

        name_he = tags.get("name:he") or tags.get("name")
        name_en = tags.get("name:en") or tags.get("name")
        carried = legacy.get(name_he, {})
        population = tags.get("population") or carried.get("population")

        base = carried.get("locality_id") or slugify(name_en, f"osm-{id(tags)}")
        for index, part in enumerate(parts):
            if part.is_empty or part.area <= 0:
                continue
            seen[base] += 1
            # Disjoint parts of one settlement each become a feature, since
            # exposure.load_localities reads only a Polygon's outer ring.
            suffix = "" if seen[base] == 1 else f"-{seen[base]}"
            features.append({
                "type": "Feature",
                "properties": {
                    "locality_id": f"{base}{suffix}",
                    "name": name_en,
                    "name_he": name_he,
                    "population": int(population) if str(population).isdigit() else None,
                    "place": tags.get("place"),
                    "source": source,
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [list(part.exterior.coords)],
                },
            })

    features.sort(key=lambda f: f["properties"]["locality_id"])
    text = json.dumps({"type": "FeatureCollection", "features": features},
                      ensure_ascii=False, separators=(",", ":"))
    text = re.sub(r"-?\d+\.\d{6,}", lambda m: f"{float(m.group()):.5f}", text)
    OUTPUT.write_text(text, encoding="utf-8")

    with_population = sum(1 for f in features if f["properties"]["population"])
    print(f"\n{len(features)} features -> {OUTPUT} ({len(text) / 1e6:.2f} MB)")
    print(f"  with population: {with_population}")
    print(f"  by source: {dict(Counter(f['properties']['source'] for f in features))}")
    print("\nOSM data (c) OpenStreetMap contributors, ODbL. Attribution required.")


if __name__ == "__main__":
    sys.exit(main())
