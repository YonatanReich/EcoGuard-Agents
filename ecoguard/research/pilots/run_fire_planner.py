"""Analyser to plan, end to end, on a fabricated incident.

    python -m ecoguard.research.pilots.run_fire_planner [scenario_key]

Takes one of the fabricated incidents, runs the analyser on it against real
terrain and settlement data, looks up who is responsible for each exposed
settlement, and asks the planner for a response plan.

One model call per run. Everything else — the spread physics, the exposure,
the escalation verdict, the station and authority lookups — is computed or
read from the store.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from ecoguard.analyzers.emergency.fire.environment import environment_for
from ecoguard.analyzers.emergency.fire.spread_analyzer import analyze_incident
from ecoguard.database.repositories.responsible_services import responsible_services
from ecoguard.paths import REPOSITORY_ROOT
from ecoguard.response_planner.fire.israeli_plan_schemas import as_operator_text
from ecoguard.response_planner.fire.israeli_planner import plan_response
from ecoguard.research.pilots.fire_analyzer_scenarios import SCENARIOS

OUTPUT = REPOSITORY_ROOT / "outputs" / "fire_planner_results.json"

DEFAULT_SCENARIO = "carmel_east_wind"


def services_for(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """Who is responsible for each settlement the fire threatens.

    Only the exposed ones, and only the first few: a plan naming fifteen
    authorities is a plan nobody rings. The analyser has already sorted them
    worst-first, so taking the head takes the ones that matter.
    """
    records = []
    for item in (analysis.get("exposure") or ())[:5]:
        locality_id = item.get("locality_id")
        if not locality_id:
            continue
        try:
            record = responsible_services(str(locality_id))
        except Exception:
            continue
        if record.get("found"):
            records.append(record)
    return records


def run(scenario_key: str) -> dict[str, Any]:
    scenario = next(
        (item for item in SCENARIOS if item["key"] == scenario_key), None
    )
    if scenario is None:
        raise SystemExit(
            f"unknown scenario {scenario_key!r}; "
            f"choose from {[item['key'] for item in SCENARIOS]}"
        )

    incident = scenario["incident"]
    base = environment_for(incident) or {}
    environment = {
        **base,
        **scenario["environment"],
        "gaps": [
            *(gap for gap in base.get("gaps") or () if "weather" not in gap),
            "weather_supplied_by_scenario_not_observed",
        ],
    }

    print(f"scenario: {scenario['key']} — {scenario['title']}")
    analysis = analyze_incident(incident, environment=environment)
    print(f"  analysis: {analysis['status']}, severity "
          f"{analysis['risk_level']} {analysis['risk_score']}, "
          f"{len(analysis['exposure'])} settlements exposed")

    services = services_for(analysis)
    print(f"  responsible services resolved for {len(services)} settlements")

    result = plan_response(analysis, services=services)
    print(f"  planner: {result.status}"
          + (f" ({result.error})" if result.error else "")
          + f", {result.retrieved_chunks} protocol chunks retrieved")

    return {
        "scenario": scenario["key"],
        "title": scenario["title"],
        "analysis": {
            "status": analysis["status"],
            "severity": analysis["risk_level"],
            "severity_score": analysis["risk_score"],
            "detection": analysis.get("detection"),
            "exposure": analysis.get("exposure"),
            "evacuation": analysis.get("evacuation"),
            "report": analysis.get("report"),
        },
        "services": services,
        "planner": json.loads(result.model_dump_json()),
        "operator_text": (
            as_operator_text(result.plan, escalation=result.escalation, dispatch=result.dispatch)
            if result.plan else None
        ),
    }


def main() -> None:
    key = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SCENARIO
    payload = run(key)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    existing = (
        json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {}
    )
    existing[payload["scenario"]] = payload
    OUTPUT.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    if payload["operator_text"]:
        print()
        print(payload["operator_text"])
    print(f"\nwritten: {OUTPUT}")


if __name__ == "__main__":
    main()
