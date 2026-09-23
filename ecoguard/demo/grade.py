"""Compare what a scenario produced against what its evidence was built to mean.

Mechanical checks only — did an incident appear, in the right lane, near the
right place, with a plan attached. Whether the prose is *sensible* is a
judgement this file deliberately does not pretend to make; it collects the text
so a human can read it, and scores only what has a right answer.

Run it after a scenario, with the sandbox still populated:

    python -m ecoguard.demo.grade demo_a
"""

from __future__ import annotations

import json
import math
import sys
from typing import Any

from sqlalchemy import text

from ecoguard.database.engine import Session

EARTH_KM_PER_DEGREE = 111.32


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    scale = math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(
        (lat2 - lat1) * EARTH_KM_PER_DEGREE,
        (lon2 - lon1) * EARTH_KM_PER_DEGREE * scale,
    )


def _rows(schema: str, sql: str) -> list[dict[str, Any]]:
    with Session() as session:
        return [dict(row) for row in session.execute(
            text(sql.replace("{s}", f'"{schema}"'))
        ).mappings().all()]


def grade(scenario: str, *, schema: str | None = None) -> dict[str, Any]:
    """Score one scenario run. Returns findings, not a verdict."""
    from importlib import import_module

    module = import_module(f"ecoguard.demo.scenarios.{scenario}")
    target = schema or scenario

    incidents = _rows(target, """
        SELECT id, primary_hazard, hazards::text AS hazards, queues::text AS queues,
               status, latitude, longitude, signal_count, last_signal_at
        FROM {s}.incidents ORDER BY id
    """)
    projections = _rows(target, """
        SELECT incident_id, hazard, route, processing_status, analysis_status,
               planner_status, retryable, attempt_count, failure_reason,
               event_payload
        FROM {s}.event_projections ORDER BY incident_id
    """)
    candidates = _rows(target, """
        SELECT hazard, relevant, literal, in_israel, classified_by,
               location_text, claim
        FROM {s}.text_candidates ORDER BY id
    """)

    by_incident = {row["incident_id"]: row for row in projections}
    findings: list[dict[str, Any]] = []

    for expected in module.GROUND_TRUTH:
        match, distance = _closest(incidents, expected)
        entry: dict[str, Any] = {
            "id": expected["id"],
            "event": expected["event"],
            "expected_hazard": expected["hazard"],
            "expected_route": expected["expect_route"],
            "notes": expected["expect_notes"],
        }
        if match is None:
            entry.update(verdict="MISS", detail="no incident within 25 km of the event")
            findings.append(entry)
            continue

        projection = by_incident.get(match["id"]) or {}
        payload = projection.get("event_payload") or {}
        if isinstance(payload, str):
            payload = json.loads(payload)

        problems = []
        if match["primary_hazard"] != expected["hazard"]:
            problems.append(
                f"hazard {match['primary_hazard']!r}, expected {expected['hazard']!r}"
            )
        if distance > expected["expect_marker_within_km"]:
            problems.append(
                f"marker {distance:.1f} km away, allowed "
                f"{expected['expect_marker_within_km']} km"
            )
        route = projection.get("route")
        if route and route != expected["expect_route"]:
            problems.append(f"route {route!r}, expected {expected['expect_route']!r}")
        if not projection:
            problems.append("never projected to the frontend")
        elif projection.get("planner_status") not in {"success", "skipped"}:
            problems.append(f"planner {projection.get('planner_status')!r}")

        entry.update(
            incident_id=match["id"],
            marker_km_from_event=round(distance, 2),
            route=route,
            analysis_status=projection.get("analysis_status"),
            planner_status=projection.get("planner_status"),
            attempts=projection.get("attempt_count"),
            title=payload.get("title"),
            description=payload.get("description"),
            verdict="PASS" if not problems else "PARTIAL",
            problems=problems,
        )
        findings.append(entry)

    # Anything that became an incident but was not one of the authored events.
    # Declared by-products are separated out: they are consequences of the
    # seeded evidence that the scenario expects and explains, and burying them
    # in with genuine surprises would make the surprises easy to miss.
    claimed = {entry.get("incident_id") for entry in findings}
    byproduct_hazards = {
        item["hazard"] for item in getattr(module, "EXPECTED_BYPRODUCTS", [])
    }
    unclaimed = [row for row in incidents if row["id"] not in claimed]
    byproducts = [
        {"incident_id": row["id"], "hazard": row["primary_hazard"]}
        for row in unclaimed if row["primary_hazard"] in byproduct_hazards
    ]
    spurious = [
        {
            "incident_id": row["id"],
            "hazard": row["primary_hazard"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
        }
        for row in unclaimed if row["primary_hazard"] not in byproduct_hazards
    ]

    declined = [
        row for row in candidates
        if not (row["relevant"] and row["literal"] and row["in_israel"])
    ]

    passed = sum(1 for entry in findings if entry["verdict"] == "PASS")
    return {
        "scenario": scenario,
        "schema": target,
        "events_expected": len(module.GROUND_TRUTH),
        "events_passed": passed,
        "events_partial": sum(1 for e in findings if e["verdict"] == "PARTIAL"),
        "events_missed": sum(1 for e in findings if e["verdict"] == "MISS"),
        "spurious_incidents": spurious,
        "expected_byproducts": byproducts,
        "findings": findings,
        "expected_silence": module.EXPECTED_SILENCE,
        "classifier_declined": declined,
        "classifier_total": len(candidates),
        "incident_count": len(incidents),
    }


def _closest(incidents, expected):
    """Nearest incident of any hazard, so a wrong classification still shows."""
    best, best_distance = None, None
    for row in incidents:
        if row["latitude"] is None or row["longitude"] is None:
            continue
        distance = _distance_km(
            expected["latitude"], expected["longitude"],
            float(row["latitude"]), float(row["longitude"]),
        )
        if best_distance is None or distance < best_distance:
            best, best_distance = row, distance
    if best is None or best_distance > 25.0:
        return None, None
    return best, best_distance


def main() -> int:
    # Titles and place names are Hebrew; a Windows console defaults to cp1252
    # and would crash the report rather than print it.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    scenario = sys.argv[1] if len(sys.argv) > 1 else "demo_a"
    report = grade(scenario)

    print(f"\n{report['scenario']}  —  {report['events_passed']}/"
          f"{report['events_expected']} events passed, "
          f"{report['events_partial']} partial, {report['events_missed']} missed")
    print(f"{report['incident_count']} incidents, "
          f"{len(report['spurious_incidents'])} unaccounted for\n")

    for entry in report["findings"]:
        print(f"  [{entry['verdict']:7}] {entry['id']}  {entry['event']}")
        if entry.get("marker_km_from_event") is not None:
            print(f"            marker {entry['marker_km_from_event']} km from the "
                  f"authored location, route={entry.get('route')}, "
                  f"planner={entry.get('planner_status')}")
        if entry.get("title"):
            print(f"            title: {entry['title']}")
        for problem in entry.get("problems", []):
            print(f"            ! {problem}")
        print()

    if report.get("expected_byproducts"):
        print("  Declared by-products (expected, explained in the scenario):")
        for row in report["expected_byproducts"]:
            print(f"    {row['incident_id']}  {row['hazard']}")
        print()

    if report["spurious_incidents"]:
        print("  UNEXPLAINED incidents (each one is a finding):")
        for row in report["spurious_incidents"]:
            print(f"    {row['incident_id']}  {row['hazard']}  "
                  f"{row['latitude']}, {row['longitude']}")
    print(f"\n  classifier: {len(report['classifier_declined'])} of "
          f"{report['classifier_total']} candidates declined as not "
          f"relevant/literal/in-Israel")
    return 0


if __name__ == "__main__":
    sys.exit(main())
