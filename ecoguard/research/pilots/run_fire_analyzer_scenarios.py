"""Run the six fabricated incidents and write the results as one JSON file.

    python -m ecoguard.research.pilots.run_fire_analyzer_scenarios

Terrain, fuel, settlements and population come from the store; only the weather
is the scenario's own. Each result records what was expected, what the analyser
produced, and whether the two agree — so the file is a test report rather than
a dump.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ecoguard.analyzers.emergency.fire.environment import environment_for
from ecoguard.analyzers.emergency.fire.spread_analyzer import analyze_incident
from ecoguard.response_planner.emergency.adapters import (
    OperationalAnalysisUnavailable,
    build_fire_spread_plan_input,
)
from ecoguard.paths import REPOSITORY_ROOT
from ecoguard.research.pilots.fire_analyzer_scenarios import SCENARIOS

OUTPUT = REPOSITORY_ROOT / "outputs" / "fire_analyzer_scenario_results.json"


def check(scenario: dict[str, Any], result: dict[str, Any]) -> list[dict[str, Any]]:
    """Each expectation as a pass/fail line, so a regression names itself."""
    expect = scenario["expect"]
    checks: list[dict[str, Any]] = []

    def record(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "passed": bool(ok), "detail": detail})

    status = result["status"]
    wanted = expect["status"]
    if wanted == "any":
        record("status", True, f"status={status} (unconstrained)")
    elif wanted == "stalled_or_skipped":
        record("status", status in {"stalled", "skipped"}, f"status={status}")
    else:
        record("status", status == wanted, f"status={status}, wanted {wanted}")

    spread = (result.get("behaviour") or {}).get("head_ros_m_per_min") or 0.0
    if expect.get("spreads"):
        record("spreads", spread > 1.0, f"head rate {spread} m/min")
    else:
        record("no significant spread", spread < 2.0, f"head rate {spread} m/min")

    if expect.get("unscored"):
        record(
            "unscored, not zero",
            result["risk_score"] is None,
            f"risk_score={result['risk_score']}",
        )

    if "heading_roughly" in expect:
        heading = (result.get("behaviour") or {}).get("heading_compass") or ""
        record(
            f"heads roughly {expect['heading_roughly']}",
            expect["heading_roughly"] in heading,
            f"heading={heading}",
        )

    named = {item["name"] for item in result.get("exposure") or ()}
    for settlement in expect.get("names_settlements", ()):
        record(f"names {settlement}", settlement in named, f"exposed={sorted(named)}")

    for settlement in expect.get("excludes_settlements", ()):
        record(
            f"does not name {settlement} (upwind)",
            settlement not in named,
            f"exposed={sorted(named)}",
        )

    if "names_origin" in expect:
        origin = (result.get("origin") or {}).get("locality")
        record(
            f"origin is {expect['names_origin']}",
            origin == expect["names_origin"],
            f"origin={origin}",
        )

    if expect.get("evacuation_nonempty"):
        record(
            "produces an evacuation list",
            bool(result.get("evacuation")),
            f"{len(result.get('evacuation') or ())} entries",
        )

    if expect.get("flags_built_up"):
        record(
            "flags the built-up share",
            "built up" in (result.get("report") or ""),
            "report mentions built-up cover",
        )

    record(
        "produces a textual report",
        bool(result.get("report")),
        f"{len(result.get('report') or '')} characters",
    )
    return checks


def _plan_input(result: dict[str, Any]) -> dict[str, Any]:
    """The real planner contract, or the refusal and why.

    This is `EmergencyResponsePlanInput` — what `EmergencyResponsePlanner`
    actually validates and serialises into its prompt — rather than a shape
    invented for the report. A refusal is recorded rather than hidden: the
    planner's hard gate declining to plan for a fire that produced no forecast
    is correct behaviour and worth showing.
    """
    try:
        return json.loads(
            build_fire_spread_plan_input(result).model_dump_json()
        )
    except OperationalAnalysisUnavailable as error:
        return {
            "refused_by_planner_adapter": str(error),
            "why": (
                "The analysis made no forecast, so there is nothing to plan "
                "from. Planning anyway would fabricate a basis for dispatch."
            ),
        }


def run() -> dict[str, Any]:
    cases = []
    for scenario in SCENARIOS:
        incident = scenario["incident"]
        # Real terrain and fuel for this ground; the scenario's own weather.
        base = environment_for(incident) or {}
        # The scenario states the weather, so whatever the store could or could
        # not find about this hour no longer describes what is being analysed.
        # Replacing the gap rather than keeping it matters: a report that says
        # "no weather reading" while quoting a wind speed contradicts itself,
        # and a reader who notices stops trusting the rest of the page. What
        # they do need to know is that the weather is hypothetical.
        observed_gaps = [
            gap for gap in base.get("gaps") or ()
            if "weather" not in gap
        ]
        environment = {
            **base,
            **scenario["environment"],
            "gaps": [*observed_gaps, "weather_supplied_by_scenario_not_observed"],
        }
        result = analyze_incident(incident, environment=environment)
        checks = check(scenario, result)
        cases.append({
            "key": scenario["key"],
            "title": scenario["title"],
            "plain_english": scenario["plain_english"],
            "expected": scenario["expect"],
            "incident": json.loads(json.dumps(incident, default=str)),
            "environment": {
                key: environment.get(key) for key in (
                    "temperature_c", "humidity_percent", "wind_speed_kmh",
                    "wind_direction_deg", "slope_deg", "slope_max_deg",
                    "aspect_deg", "built_up_fraction", "burnable_fraction",
                    "dominant_fuel", "sampled_radius_m", "gaps",
                )
            },
            "cover_fractions": environment.get("cover_fractions"),
            "checks": checks,
            "passed": all(item["passed"] for item in checks),
            "outcome": {
                "status": result.get("status"),
                "reason": result.get("reason"),
                "severity_score": result.get("risk_score"),
                "severity_level": result.get("risk_level"),
                "settlements_exposed": len(result.get("exposure") or ()),
                "evacuation_entries": len(result.get("evacuation") or ()),
                "people_in_spread": (
                    (result.get("population_in_spread") or {}).get("people")
                ),
                "population_at_risk": result.get("population_at_risk"),
                "heading_compass": (result.get("behaviour") or {}).get(
                    "heading_compass"
                ),
                "head_rate_m_per_min": (result.get("behaviour") or {}).get(
                    "head_ros_m_per_min"
                ),
            },
            "planner_json": _plan_input(result),
            "report": result.get("report"),
        })

    summary = {
        "cases": len(cases),
        "passed": sum(1 for case in cases if case["passed"]),
        "checks": sum(len(case["checks"]) for case in cases),
        "checks_passed": sum(
            1 for case in cases for item in case["checks"] if item["passed"]
        ),
    }
    return {"summary": summary, "cases": cases}


def main() -> None:
    payload = run()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    summary = payload["summary"]
    print(
        f"{summary['passed']}/{summary['cases']} scenarios, "
        f"{summary['checks_passed']}/{summary['checks']} checks passed"
    )
    for case in payload["cases"]:
        mark = "PASS" if case["passed"] else "FAIL"
        print(f"  [{mark}] {case['key']}")
        for item in case["checks"]:
            if not item["passed"]:
                print(f"         x {item['check']}: {item['detail']}")
    print(f"written: {OUTPUT}")


if __name__ == "__main__":
    main()
