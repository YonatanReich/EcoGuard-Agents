"""One small model call, to answer "is the API actually working?".

Worth running before a demo: an exhausted account fails quietly, and every
model-backed lane simply produces nothing."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ecoguard.planners.fire.planning_agent import ResponsePlanningAgent
from ecoguard.analyzers.fire.risk_analysis_agent import RiskAnalysisAgent
from ecoguard.shared.llm import ClaudeLLMService
from ecoguard.shared.protocols import ProtocolRetriever

# A plausible high-risk event near Givat Shmuel, shaped exactly like a real
# FireDetectionAgent result so the smoke check exercises the true code path.
SAMPLE_EVENT = {
    "metadata": {"timestamp": "2026-08-28T11:00:00Z", "collection_status": "success"},
    "event_type": "fire",
    "detected": True,
    "location": {"latitude": 32.0786, "longitude": 34.8483},
    "detection_confidence": "high",
    "fire_weather_severity": "very_high",
    "satellite_evidence": {
        "source": "NASA FIRMS",
        "hotspots_count": 4,
        "selected_hotspot": {
            "latitude": 32.0786,
            "longitude": 34.8483,
            "acquisition_date": "2026-08-28",
            "acquisition_time": "1042",
            "satellite": "N20",
            "instrument": "VIIRS",
            "confidence": "h",
            "normalized_confidence": "high",
            "frp": 94.6,
            "daynight": "D",
        },
        "hotspots": [],
    },
    "fire_danger": {
        "source": "GWIS/EFFIS",
        "index": "FWI",
        "danger_level": "very_high",
        "fwi_min": 38.0,
        "fwi_max": 50.0,
    },
    "weather_context": {
        "current": {
            "temperature_c": 38.2,
            "humidity_percent": 14,
            "wind_speed_kmh": 41.0,
            "precipitation_mm": 0.0,
            "weather_code": 0,
        },
        "forecast": {"daily": {}},
    },
    "geospatial_context": {
        "terrain_type": None,
        "region_type": None,
        "vegetation_density": None,
        "distance_to_water_m": None,
        "nearby_roads": [{"name": "Route 4", "type": "trunk"}],
        "nearby_settlements": [{"name": "Givat Shmuel", "type": "town"}],
        "nearby_hospitals": [{"name": "Beilinson Hospital", "type": "hospital"}],
        "nearby_police_stations": [],
        "nearby_fire_stations": [],
        "nearby_green_areas": [],
        "nearby_water_sources": [],
    },
    "source_status": {
        "nasa_firms": "success",
        "gwis_effis": "success",
        "weather": "success",
        "geospatial": "partial",
    },
}


def report(label: str, ok: bool, detail: str = "") -> bool:
    """Print one check result and return its outcome."""
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}{(' — ' + detail) if detail else ''}")
    return ok


def main() -> int:
    """Make one small model call, to confirm the key and the credit still work."""
    print("EcoGuard — Claude smoke check\n")

    retriever = ProtocolRetriever()

    print("Corpus")
    ok = report(
        "protocol corpus loaded",
        retriever.available,
        f"{len(retriever.chunks)} chunks from {len(retriever.documents)} documents",
    )
    if not ok:
        print("\nNothing else can run without a corpus.")
        return 1

    risk_service = ClaudeLLMService(effort="medium")

    if not risk_service.available:
        print("\n  [FAIL] ANTHROPIC_API_KEY is not set.")
        print("  Add it to a .env file at the repository root, then re-run.")
        return 1

    risk_agent = RiskAnalysisAgent(llm_service=risk_service, retriever=retriever)
    planning_agent = ResponsePlanningAgent(
        llm_service=ClaudeLLMService(effort="low"), retriever=retriever
    )

    print("\nRisk analysis (real Claude call, this takes a few seconds)")
    risk = risk_agent.analyze_event(SAMPLE_EVENT)

    passed = report(
        "assessment succeeded",
        risk["metadata"]["analysis_status"] == "success",
        risk.get("error") or "",
    )

    if not passed:
        print("\nStopping: the risk call must succeed before planning can run.")
        return 1

    passed &= report(
        "score is in range",
        isinstance(risk["risk_score"], int) and 0 <= risk["risk_score"] <= 100,
        f"score={risk['risk_score']} level={risk['risk_level']}",
    )
    passed &= report(
        "citations verified against the corpus",
        len(risk["grounding"]["citations"]) > 0,
        f"{len(risk['grounding']['citations'])} verified, "
        f"{risk['grounding']['unverified_citation_count']} discarded",
    )

    print("\n  Explanation:")
    print(f"    {risk['explanation']}")
    print("\n  Cited:")
    for citation in risk["grounding"]["citations"]:
        print(f"    [{citation['chunk_id']}]")
        print(f"      \"{citation['quoted_text'][:110]}...\"")

    print("\nResponse planning (second real Claude call)")
    plan = planning_agent.plan_response(SAMPLE_EVENT, risk)

    # "partial" is a working plan, not a failure. The planner keeps the actions
    # it could ground and labels the rest, so a run that lands there has done
    # its job — reporting it as a failure here would train a reader to ignore
    # the one line that says whether the model is reachable at all.
    status = plan["metadata"]["planning_status"]
    grounded = plan.get("grounding", {}).get("protocol_grounded", True)
    passed &= report(
        "plan produced",
        status in {"success", "partial"} and bool(plan.get("response_actions")),
        plan.get("error") or status,
    )

    if status in {"success", "partial"}:
        citations = len(plan["grounding"]["citations"])
        if grounded:
            passed &= report(
                "plan cites the corpus",
                citations > 0,
                f"{citations} verified"
                + ("" if status == "success" else ", some actions dropped as ungrounded"),
            )
        else:
            # Not a failure of the run, but the operator-visible outcome is
            # advice rather than doctrine, and a demo should know which it got.
            report(
                "plan is NOT protocol-verified",
                True,
                "returned as advice; citations withheld",
            )
        print("\n  Units:", ", ".join(plan["recommended_units"]))
        print("  Actions:")
        for action in plan["response_actions"]:
            print(
                f"    - [{action['timeframe']}] {action['responsible_unit']}: "
                f"{action['action']}"
            )

    # Prompt caching only shows up on a second call sharing the same prefix.
    print("\nPrompt caching (repeating the risk call to check for a cache hit)")
    risk_agent.analyze_event(SAMPLE_EVENT)

    usage = risk_service.last_usage or {}
    cache_read = usage.get("cache_read_input_tokens") or 0

    report(
        "cached prefix was read on the second call",
        cache_read > 0,
        f"cache_read_input_tokens={cache_read}",
    )

    if cache_read == 0:
        # Not a failure: below roughly 1024 tokens the API silently declines to
        # cache. Worth knowing about rather than assuming caching is working.
        print(
            "    Note: caching is a cost optimisation, not a correctness "
            "requirement.\n"
            "    A zero here usually means the system prompt is under the "
            "~1024-token minimum."
        )

    print(f"\n{'All checks passed.' if passed else 'Some checks failed.'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
