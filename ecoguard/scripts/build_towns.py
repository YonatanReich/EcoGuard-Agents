"""Assemble the towns reference file: one row per Israeli locality.

The roster is the CBS population file — 1,222 localities, each with an official
סמל יישוב and a resident count. That list, not OpenStreetMap, decides what a
town is. An earlier version of this script worked the other way round and
produced 2,017 "towns", because OSM also maps Palestinian West Bank villages,
unrecognised Bedouin encampments, farms, and — where a locality is drawn as
several scattered clusters — the same name ten times over. Anchoring on CBS
makes the count right by construction and gives every row a population, which
OSM supplies for barely one locality in seven.

Each locality then needs an outline, and OSM is still the only source for that.
Three ways, in order of preference:

  place polygon    a way or relation tagged place=* carrying the name. Best:
                   somebody drew this settlement's extent deliberately.
  clipped built-up the locality has only a place *node*. The residential
                   landuse around it is morphologically closed into a footprint
                   and then clipped to the locality's own municipal boundary.
                   The clip is what makes this safe: Haifa's built-up area runs
                   continuously into the Krayot, and without it "Haifa" would
                   be the whole conurbation.
  raw built-up     same, where there is no municipal boundary to clip against —
                   the West Bank, which muni_il does not cover.

Anything still without geometry is reported and dropped; a town with no outline
cannot be drawn or intersected with a spread ring.

The remaining joins — police station, authority phone — are by Hebrew name,
which is not a key. Official lists disagree about קריית/קרית, about באר שבע vs
באר-שבע, about whether תל אביב - יפו has spaces around its hyphen. `normalise`
collapses those; each row records how it matched in `*_match` so an approximate
join can be found later rather than silently trusted.

Run from the repo root, after build_localities.py and build_muni_geojson.py:

    python ecoguard/scripts/build_towns.py
"""

from __future__ import annotations

import csv
import difflib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from shapely import set_precision
from shapely.geometry import MultiPolygon, Point, Polygon, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

REFERENCE = Path("ecoguard/data/reference")
TOWN_INFO = REFERENCE / "Town info"
OSM_CACHE = REFERENCE / ".osm_cache"
LOCALITIES = REFERENCE / "localities_osm.geojson"
DISTRICTS = REFERENCE / "fire_districts.geojson"
MUNI = REFERENCE / "muni_il.geojson"
POPULATION_CSV = TOWN_INFO / "population-and-households-by-locality.csv"
POLICE_CSV = TOWN_INFO / "settlementsbypolicestations.csv"
AUTHORITIES = TOWN_INFO / "authorities.json"
OUTPUT = REFERENCE / "towns.json"

# The CBS export is Windows Hebrew, not UTF-8.
POPULATION_ENCODING = "cp1255"

SETTLEMENT_KINDS = ("city", "town", "village", "hamlet", "isolated_dwelling", "farm")

# Closing distance for residential blocks (~30 m): bridges the street between
# two blocks of one village without welding neighbouring villages together.
CLOSE_DEG = 0.0003

# How far a place node may sit outside its own built-up area and still match
# it (~150 m). Town-centre nodes land on roads and squares.
SNAP_DEG = 0.0015

FUZZY_CUTOFF = 0.88

# Parts of the fabric smaller than this are dropped: clipping a national
# landuse layer to a municipal boundary leaves slivers of the neighbour's
# built-up area along the shared edge, and those are not part of this town.
MIN_PART_KM2 = 0.004

# If the mapped fabric covers less than this share of a town's own municipal
# boundary, and nobody has drawn the settlement as a place polygon either, the
# landuse data is too sparse to describe the town — OSM maps dense Israeli
# cities as individual buildings and tags almost no residential landuse there.
# The boundary is then used whole: it overstates the town, but a warning system
# that misses a city is worse than one that includes its parkland.
FABRIC_COVERAGE_FLOOR = 0.2
# Simplification (~10 m). Settlements are small — a kibbutz is a few hundred
# metres across — so this is finer than the municipal layer's tolerance.
SIMPLIFY_DEG = 0.0001

COORD_GRID_DEG = 1e-5


def normalise(name: str) -> str:
    """An Israeli place name, reduced to what the official lists agree on."""
    text = (name or "").strip()
    text = re.sub(r"[֑-ׇ]", "", text)               # niqqud
    text = text.replace("־", "-").replace("–", "-").replace("—", "-")
    text = re.sub(r"[\"'`׳״]", "", text)
    text = re.sub(r"\([^)]*\)", "", text)                      # (שבט), (גוליס)
    # Hyphen and space are interchangeable across these lists: CBS writes
    # "באר שבע" where OSM writes "באר-שבע", and "תל אביב -יפו" appears with the
    # space on either side. Collapsing both to a single space settles it.
    text = re.sub(r"[-\s]+", " ", text)
    # Plene vs defective spelling: קריית/קרית, גני תקווה/גני תקוה.
    text = text.replace("יי", "י").replace("וו", "ו")
    return text.strip()


def build_index(pairs):
    index = {}
    for name, value in pairs:
        key = normalise(name)
        if key:
            index.setdefault(key, value)
    return index


def lookup_exact(name: str, index):
    """Exact match on the normalised name, or nothing.

    Used for clip boundaries, where a near-miss is far worse than a miss: a
    village fuzzy-matched to its regional council gets clipped to the whole
    council, and every other village's built-up land is then reported as part
    of it. Better to fall back to growing from the seed.
    """
    return index.get(normalise(name))


def lookup(name: str, index):
    key = normalise(name)
    if not key:
        return None, "miss"
    if key in index:
        return index[key], "exact"
    for candidate in index:
        if candidate.startswith(key + " ") or key.startswith(candidate + " "):
            return index[candidate], "prefix"
    close = difflib.get_close_matches(key, index.keys(), n=1, cutoff=FUZZY_CUTOFF)
    if close:
        return index[close[0]], "fuzzy"
    return None, "miss"


def slugify(name: str, fallback: str) -> str:
    ascii_only = (unicodedata.normalize("NFKD", name)
                  .encode("ascii", "ignore").decode().lower())
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")
    return slug or fallback


def to_int(value: str) -> int | None:
    digits = (value or "").replace(",", "").strip()
    return int(digits) if digits.isdigit() else None


def area_km2(geometry) -> float:
    return (geometry.area * (111_320 ** 2)
            * math.cos(math.radians(geometry.centroid.y)) / 1e6)


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


def osm_geometry(element):
    """An OSM way or multipolygon relation as a shapely geometry."""
    def ring(coords):
        return [(c["lon"], c["lat"]) for c in coords or ()]

    if element["type"] == "way":
        points = ring(element.get("geometry"))
        return Polygon(points).buffer(0) if len(points) >= 4 else None

    outer_ways, inner_ways = [], []
    for member in element.get("members", ()):
        points = ring(member.get("geometry"))
        if len(points) < 2:
            continue
        target = inner_ways if member.get("role") == "inner" else outer_ways
        target.append(points)

    # Stitch, do not close each member on its own: a municipal boundary is one
    # ring split across a dozen ways shared with roads and neighbours, and
    # closing each separately turns Jerusalem into 27 slivers totalling a fifth
    # of its real area.
    outers = [Polygon(r).buffer(0) for r in stitch(outer_ways)]
    inners = [Polygon(r).buffer(0) for r in stitch(inner_ways)]
    if not outers:
        return None
    geometry = unary_union(outers)
    if inners:
        geometry = geometry.difference(unary_union(inners))
    return None if geometry.is_empty else geometry


def polygon_parts(geometry):
    """Every Polygon in whatever shapely handed back."""
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    # A GeometryCollection, from an intersection that also produced lines.
    return [g for g in getattr(geometry, "geoms", []) if isinstance(g, Polygon)]


def km2(geometry) -> float:
    return area_km2(geometry)


def largest_polygon(geometry):
    """One Polygon from whatever shapely handed back.

    The table stores a single outline per town because exposure.load_localities
    reads one ring. Where a locality is genuinely split, the largest part is the
    settlement and the rest are outlying plots.
    """
    if geometry is None or geometry.is_empty:
        return None
    if isinstance(geometry, MultiPolygon):
        geometry = max(geometry.geoms, key=lambda g: g.area)
    return geometry if isinstance(geometry, Polygon) else None


def main() -> None:
    # ---------- the roster ----------
    roster = list(csv.DictReader(
        POPULATION_CSV.read_text(encoding=POPULATION_ENCODING).splitlines()))
    print(f"CBS roster: {len(roster)} localities")

    # ---------- OSM place polygons ----------
    features = json.loads(LOCALITIES.read_text(encoding="utf-8"))["features"]
    place_polygons = defaultdict(list)
    for feature in features:
        properties = feature["properties"]
        if properties.get("place") not in SETTLEMENT_KINDS:
            continue
        if not properties.get("name_he"):
            continue
        place_polygons[normalise(properties["name_he"])].append(feature)
    print(f"OSM place polygons: {sum(len(v) for v in place_polygons.values())} "
          f"under {len(place_polygons)} names")

    # ---------- OSM place nodes ----------
    nodes = json.loads((OSM_CACHE / "points.json").read_text(encoding="utf-8"))["elements"]
    node_index = build_index(
        ((n.get("tags", {}).get("name:he") or n.get("tags", {}).get("name") or ""), n)
        for n in nodes
    )

    # ---------- the town fabric ----------
    # Residential blocks, plus the industrial estates, campuses and hospitals
    # that are equally part of a town and equally exposed to a fire.
    blocks = []
    for name in ("landuse.json", "nonresidential.json"):
        path = OSM_CACHE / name
        if not path.exists():
            raise SystemExit(f"missing {path} - run the Overpass fetch first")
        for element in json.loads(path.read_text(encoding="utf-8"))["elements"]:
            geometry = osm_geometry(element)
            if geometry is not None and geometry.is_valid and not geometry.is_empty:
                blocks.append(geometry)

    # Closing merges blocks separated by a street into one body, so a town
    # mapped as forty parcels does not arrive as forty parts.
    fabric = unary_union(blocks).buffer(CLOSE_DEG).buffer(-CLOSE_DEG)
    fabric_parts = polygon_parts(fabric)
    fabric_tree = STRtree(fabric_parts)
    print(f"town fabric: {len(blocks)} blocks -> {len(fabric_parts)} bodies")

    # ---------- administrative boundaries ----------
    # admin_level=8 is the municipality. muni_il stops at the Green Line, so
    # this is the only clip boundary available for Ariel and its neighbours.
    admin8_index = {}
    admin_path = OSM_CACHE / "admin8.json"
    if admin_path.exists():
        pairs = []
        for element in json.loads(admin_path.read_text(encoding="utf-8"))["elements"]:
            tags = element.get("tags", {})
            label = tags.get("name:he") or tags.get("name")
            geometry = osm_geometry(element)
            if label and geometry is not None and geometry.is_valid and not geometry.is_empty:
                pairs.append((label, geometry))
        admin8_index = build_index(pairs)
    print(f"admin_level=8 boundaries: {len(admin8_index)}")

    # ---------- boundaries ----------
    districts = [(f["properties"]["district"], shape(f["geometry"]))
                 for f in json.loads(DISTRICTS.read_text(encoding="utf-8"))["features"]]
    district_tree = STRtree([g for _, g in districts])

    munis = [(f["properties"], shape(f["geometry"]))
             for f in json.loads(MUNI.read_text(encoding="utf-8"))["features"]]
    muni_tree = STRtree([g for _, g in munis])
    muni_index = build_index((p["name"], (p, g)) for p, g in munis)

    # ---------- name-joined reference ----------
    # A large city is split across several stations, and the CSV says so with
    # one row per station — 'חיפה (תחנת נשר)' beside a bare 'חיפה' whose station
    # is blank. Parentheses are stripped by `normalise`, so all of them land on
    # the same key; keeping only the first would keep the blank parent row.
    # Every row is kept instead and the stations are reported together.
    police_index: dict[str, list[dict]] = defaultdict(list)
    for row in csv.DictReader(POLICE_CSV.read_text(encoding="utf-8-sig").splitlines()):
        key = normalise(row["שם יישוב"])
        if key:
            police_index[key].append(row)
    authority_index = build_index(
        ((entry.get("Data") or {}).get("namecity", ""), entry.get("Data") or {})
        for entry in json.loads(AUTHORITIES.read_text(encoding="utf-8"))
    )

    towns, used_ids, stats, dropped = [], Counter(), Counter(), []

    for row in roster:
        name_he = (row["LocNameHeb"] or "").strip()
        code = (row["LocalityCode"] or "").strip()
        if not name_he or not code.isdigit():
            dropped.append((name_he or code, "not a locality row"))
            continue

        key = normalise(name_he)
        place_kind = None
        name_en = name_he

        # The seed: what we know locates this town. A drawn place polygon if
        # OSM has one, otherwise the place node.
        seed = None
        candidates = place_polygons.get(key)
        if not candidates:
            close = difflib.get_close_matches(key, place_polygons.keys(), n=1,
                                              cutoff=FUZZY_CUTOFF)
            candidates = place_polygons[close[0]] if close else None
        if candidates:
            best = max(candidates, key=lambda f: shape(f["geometry"]).area)
            seed = shape(best["geometry"])
            place_kind = best["properties"].get("place")
            name_en = best["properties"].get("name") or name_he
        else:
            node, _ = lookup(name_he, node_index)
            if node:
                seed = Point(node["lon"], node["lat"])
                place_kind = node.get("tags", {}).get("place")
                name_en = node.get("tags", {}).get("name:en") or name_he

        if seed is None:
            dropped.append((name_he, "no place polygon or node"))
            continue

        anchor = seed.representative_point() if seed.geom_type != "Point" else seed

        # The clip boundary, and it has to be *this town's own*. Exact name
        # match only, and never the polygon that merely contains the town: a
        # kibbutz sits inside a regional council whose boundary holds thirty
        # other villages, and clipping to that hands every one of their
        # built-up areas to this row. OSM's admin_level=8 comes first because
        # muni_il stops at the Green Line and Ariel needs a boundary.
        boundary, boundary_kind = None, None
        found = lookup_exact(name_he, admin8_index)
        if found is not None:
            boundary, boundary_kind = found, "admin8"
        if boundary is None:
            found = lookup_exact(name_he, muni_index)
            if found is not None:
                boundary, boundary_kind = found[1], "muni_il"

        # The town fabric inside that boundary: homes, industrial estates,
        # campuses and hospitals, every part of it. This is what the choice of
        # "built-up + industrial + institutional" means in practice — the
        # boundary supplies the extent, the fabric supplies the substance, and
        # the open land in between belongs to neither.
        # The drawn place polygon is part of the answer, not an alternative to
        # it. Fabric alone loses Givat Shmuel — OSM has it drawn as a place but
        # maps little landuse inside it — so the two are unioned and then cut
        # to the boundary.
        drawn = seed if seed.geom_type != "Point" else None

        outline, source = None, None
        if boundary is not None:
            clipped = fabric.intersection(boundary)
            kept = [part for part in polygon_parts(clipped)
                    if km2(part) >= MIN_PART_KM2]
            if drawn is not None:
                kept.extend(polygon_parts(drawn.intersection(boundary)))
            if kept:
                covered = unary_union(kept)
                if drawn is None and km2(covered) < FABRIC_COVERAGE_FLOOR * km2(boundary):
                    outline, source = boundary, f"boundary/{boundary_kind}"
                else:
                    outline, source = covered, f"fabric/{boundary_kind}"

        # No boundary — West Bank villages muni_il does not reach and OSM has
        # not bounded. Grow from the seed instead: its own polygon plus any
        # fabric touching it.
        if outline is None:
            touching = [part for part in
                        (fabric_parts[i] for i in fabric_tree.query(seed))
                        if part.intersects(seed)]
            pieces = ([drawn] if drawn is not None else []) + touching
            if pieces:
                grown = unary_union(pieces)
                # Only fabric the seed actually touches, so a village cannot
                # annex its neighbour across a shared council boundary.
                kept = [part for part in polygon_parts(grown)
                        if part.intersects(seed)]
                outline = unary_union(kept) if kept else grown
                source = "fabric/seed"

        # Nothing built is mapped here at all; fall back to the administrative
        # outline itself, which overstates the town but locates it.
        if outline is None and boundary is not None:
            outline = boundary
            source = f"boundary/{boundary_kind}"

        if outline is None and seed.geom_type != "Point":
            outline, source = seed, "place"

        # Neither OSM nor the roster always has a Latin name; muni_il does, for
        # every authority. Without this the search dropdown shows the Hebrew
        # name twice and the town_id degenerates to its CBS code.
        if not name_en.isascii():
            found, _ = lookup(name_he, muni_index)
            if found and found[0].get("name_en"):
                name_en = found[0]["name_en"]


        if outline is None or outline.is_empty:
            dropped.append((name_he, "no geometry"))
            continue

        outline = set_precision(outline.simplify(SIMPLIFY_DEG, preserve_topology=True),
                                COORD_GRID_DEG)
        if not outline.is_valid:
            outline = outline.buffer(0)
        parts = [part for part in polygon_parts(outline) if km2(part) >= MIN_PART_KM2]
        if not parts:
            # Everything survived the clip but nothing survived the sliver
            # filter — the town is smaller than MIN_PART_KM2 in total. Keep its
            # largest piece rather than losing the locality.
            parts = polygon_parts(outline)[:1]
        if not parts:
            dropped.append((name_he, "geometry collapsed"))
            continue
        outline = MultiPolygon(parts)

        stats[source] += 1

        label = outline.representative_point()
        minx, miny, maxx, maxy = outline.bounds

        fire_district = None
        for i in district_tree.query(label):
            if districts[i][1].contains(label):
                fire_district = districts[i][0]
                break
        stats["fire_district"] += bool(fire_district)

        authority = authority_type = None
        for i in muni_tree.query(label):
            if munis[i][1].contains(label):
                authority, authority_type = munis[i][0]["name"], munis[i][0]["type"]
                break
        stats["authority"] += bool(authority)

        contact, contact_match = {}, "miss"
        if authority:
            found, contact_match = lookup(authority, authority_index)
            contact = found or {}
        if not contact:
            found, contact_match = lookup(name_he, authority_index)
            contact = found or {}
        stats["phone"] += bool((contact.get("tel") or {}).get("title"))

        matches, police_match = lookup(name_he, police_index)
        matches = matches or []
        stations, region, district = [], None, None
        for candidate in matches:
            station = (candidate.get("שם תחנה") or "").strip()
            if station and station not in stations:
                stations.append(station)
            region = region or (candidate.get("שם מרחב") or "").strip() or None
            district = district or (candidate.get("שם מחוז") or "").strip() or None
        # Tel Aviv answers to five stations; naming one of them would be wrong.
        police_station = ", ".join(stations) or None
        stats["police"] += bool(police_station)

        base = slugify(name_en, f"loc-{code}")
        used_ids[base] += 1
        town_id = base if used_ids[base] == 1 else f"{base}-{used_ids[base]}"

        towns.append({
            "town_id": town_id,
            "cbs_code": code,
            "name_he": name_he,
            "name_en": name_en,
            "place": place_kind,
            "population": to_int(row["Total_Population"]),
            "households": to_int(row["Households "]),
            "outline_source": source,

            "fire_district": fire_district,
            "authority": authority,
            "authority_type": authority_type,
            "authority_phone": (contact.get("tel") or {}).get("title") or None,
            "authority_address": contact.get("Address") or None,
            "authority_website": (contact.get("WebLink") or {}).get("URL") or None,
            "authority_match": contact_match,

            "police_station": police_station,
            "police_region": region,
            "police_district": district,
            "police_match": police_match,

            "area_km2": round(km2(outline), 4),
            "parts": len(outline.geoms),
            "label_lat": round(label.y, 6),
            "label_lon": round(label.x, 6),
            "bbox": [round(minx, 6), round(miny, 6), round(maxx, 6), round(maxy, 6)],
            # MultiPolygon always, even for a single-part town, so every
            # consumer takes one code path. Outer rings only; a hole in a town
            # is a park, and a fire there is still a fire in the town.
            "geometry": {
                "type": "MultiPolygon",
                "coordinates": [[[[round(x, 5), round(y, 5)]
                                  for x, y in part.exterior.coords]]
                                for part in outline.geoms],
            },
        })

    towns.sort(key=lambda t: t["town_id"])
    OUTPUT.write_text(json.dumps(towns, ensure_ascii=False, separators=(",", ":")),
                      encoding="utf-8")

    total = len(towns)
    print(f"\n{total} towns -> {OUTPUT} ({OUTPUT.stat().st_size / 1e6:.2f} MB)")
    print("  outline source:")
    for label, count in sorted(((k, v) for k, v in stats.items() if "/" in k),
                               key=lambda kv: -kv[1]):
        print(f"    {label:22s} {count:5d}")
    multipart = sum(1 for t in towns if t["parts"] > 1)
    print(f"  multipart towns     {multipart:5d}")
    for label, key in [("fire district", "fire_district"), ("local authority", "authority"),
                       ("authority phone", "phone"), ("police station", "police")]:
        print(f"  with {label:16s} {stats[key]:5d} ({100 * stats[key] / total:3.0f}%)")
    with_population = sum(1 for t in towns if t["population"])
    print(f"  with population     {with_population:5d} ({100 * with_population / total:3.0f}%)")

    if dropped:
        print(f"\n{len(dropped)} roster rows produced no town:")
        for name, why in dropped[:25]:
            print(f"    {name}  — {why}")
        if len(dropped) > 25:
            print(f"    ... and {len(dropped) - 25} more")


if __name__ == "__main__":
    main()
