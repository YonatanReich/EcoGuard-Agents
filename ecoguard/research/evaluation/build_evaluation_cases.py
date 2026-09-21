"""
Build the artificial fire evaluation cases.

The eight cases in data/evaluation/fire_cases are hand-authored inputs, but their
protocol citations are extracted from the live corpus at build time rather than
copied by hand. A mistyped quotation would fail verification the moment the
harness ran, and the mistake would look like a pipeline failure rather than an
authoring error — so the quotes are taken from the source text mechanically and
the build fails loudly if a marker no longer appears.

Re-run after editing a case definition or after changing the corpus:

    python scripts/build_evaluation_cases.py

Every generated file is committed. They are inputs, not output, so they do not
live in ecoguard/data/generated.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ecoguard.analyzers.emergency.fire.risk_analysis_agent import build_event_id, build_situational_facts
from ecoguard.shared.protocols import ProtocolRetriever
from ecoguard.paths import EVALUATION

OUTPUT_DIR = EVALUATION / "fire_cases"

RETRIEVER = ProtocolRetriever(hazard="fire")
CHUNKS = {chunk["chunk_id"]: chunk for chunk in RETRIEVER.chunks}


def quote(chunk_id: str, marker: str, length: int = 160) -> str:
    """
    Take a verbatim span from a real corpus chunk.

    Args:
        chunk_id (str): Chunk to quote from.
        marker (str): Text to start the quote at. Must be present verbatim.
        length (int): How many characters to take.

    Returns:
        str: A span that will pass verify_citations.

    Raises:
        SystemExit: If the chunk or the marker is missing, which means a case
            definition has drifted from the corpus.
    """
    chunk = CHUNKS.get(chunk_id)
    if chunk is None:
        raise SystemExit(f"No such chunk: {chunk_id}")

    text = " ".join(chunk["text"].split())
    index = text.find(marker)

    if index < 0:
        raise SystemExit(f"Marker not found in {chunk_id}: {marker!r}")

    return text[index : index + length].strip()


def citation(chunk_id: str, marker: str, supports: str, length: int = 160) -> dict:
    """Build one citation whose quote is guaranteed to verify."""
    chunk = CHUNKS[chunk_id]
    return {
        "chunk_id": chunk_id,
        "document_title": chunk["document_title"],
        "quoted_text": quote(chunk_id, marker, length),
        "supports": supports,
    }


def detected_event(
    *,
    latitude: float,
    longitude: float,
    detected,
    confidence=None,
    severity=None,
    hotspot=None,
    hotspots_count=0,
    fire_danger=None,
    weather=None,
    geospatial=None,
    report_evidence=None,
    collection_status="success",
    satellite_error=None,
) -> dict:
    """Assemble a FireDetectionAgent-shaped event."""
    satellite: dict = {"source": "NASA FIRMS"}

    if satellite_error is not None:
        satellite["collection_status"] = "failed"
        satellite["error"] = satellite_error
    else:
        satellite["hotspots_count"] = hotspots_count
        satellite["selected_hotspot"] = hotspot
        if detected is True:
            satellite["hotspots"] = [hotspot] if hotspot else []

    event = {
        "metadata": {
            "timestamp": "2026-09-03T09:00:00Z",
            "collection_status": collection_status,
        },
        "event_type": "fire",
        "detected": detected,
        "location": {"latitude": latitude, "longitude": longitude},
        "detection_confidence": confidence,
        "fire_weather_severity": severity,
        "satellite_evidence": satellite,
        "fire_danger": fire_danger,
        "weather_context": weather,
        "geospatial_context": geospatial,
    }

    if report_evidence is not None:
        event["report_evidence"] = report_evidence

    if detected is True:
        event["source_status"] = {
            "nasa_firms": "success",
            "gwis_effis": "success" if fire_danger else "failed",
            "weather": "success" if weather else "failed",
            "geospatial": "success" if geospatial else "failed",
        }

    return event


def hotspot(lat, lon, frp, date, time, conf) -> dict:
    return {
        "latitude": lat,
        "longitude": lon,
        "acquisition_date": date,
        "acquisition_time": time,
        "satellite": "N20",
        "instrument": "VIIRS",
        "confidence": conf[0],
        "normalized_confidence": conf,
        "frp": frp,
        "daynight": "D",
    }


def weather(temp, humidity, wind, rain=0.0) -> dict:
    return {
        "current": {
            "temperature_c": temp,
            "humidity_percent": humidity,
            "wind_speed_kmh": wind,
            "precipitation_mm": rain,
            "weather_code": 0,
        },
        "forecast": {"daily": {}},
    }


def fwi(level, low, high) -> dict:
    return {
        "source": "GWIS/EFFIS",
        "index": "FWI",
        "danger_level": level,
        "fwi_min": low,
        "fwi_max": high,
    }


def assessment(
    *,
    event: dict,
    score,
    confidence,
    situational,
    drivers,
    explanation,
    gaps,
    citations,
    status="success",
    reason=None,
    error=None,
    web_findings=None,
) -> dict:
    """Assemble a RiskAnalysisAgent-shaped assessment."""
    from ecoguard.shared.schemas import risk_level_for_score

    if status != "success":
        return {
            "metadata": {
                "timestamp": "2026-09-03T09:00:05Z",
                "agent": "RiskAnalysisAgent",
                "analysis_status": status,
                "model": None,
                "reason": reason,
            },
            "event_id": build_event_id(event),
            "event_type": "fire",
            "location": event["location"],
            "risk_score": None,
            "risk_level": None,
            "risk_semantics": "detected_event_operational_risk",
            "confidence": None,
            "situational_context": None,
            "primary_drivers": [],
            "explanation": None,
            "evidence_gaps": [],
            "web_findings": [],
            "grounding": {
                "retriever": "bm25",
                "retrieved_chunk_ids": [],
                "citations": [],
                "unverified_citation_count": 0,
                "web_search": {
                    "enabled": True,
                    "searches_used": 0,
                    "findings_verified": 0,
                    "findings_dropped": 0,
                },
            },
            "error": error,
        }

    context = dict(situational)
    context["derived"] = build_situational_facts(event)

    findings = web_findings or []

    return {
        "metadata": {
            "timestamp": "2026-09-03T09:00:05Z",
            "agent": "RiskAnalysisAgent",
            "analysis_status": "success",
            "model": "claude-sonnet-5",
            "reason": None,
        },
        "event_id": build_event_id(event),
        "event_type": "fire",
        "location": event["location"],
        "risk_score": score,
        "risk_level": risk_level_for_score(score),
        "risk_semantics": "detected_event_operational_risk",
        "confidence": confidence,
        "situational_context": context,
        "primary_drivers": drivers,
        "explanation": explanation,
        "evidence_gaps": gaps,
        "web_findings": findings,
        "grounding": {
            "retriever": "bm25",
            "retrieved_chunk_ids": [c["chunk_id"] for c in citations],
            "citations": [
                {
                    **c,
                    "document_id": CHUNKS[c["chunk_id"]]["document_id"],
                    "source_url": CHUNKS[c["chunk_id"]]["source_url"],
                    "heading_path": CHUNKS[c["chunk_id"]]["heading_path"],
                    "verified": True,
                }
                for c in citations
            ],
            "unverified_citation_count": 0,
            "web_search": {
                "enabled": True,
                "searches_used": len(findings),
                "findings_verified": len(findings),
                "findings_dropped": 0,
            },
        },
        "error": None,
    }


def situational(
    area, basis, band, pop_basis, evac, gaps=None
) -> dict:
    return {
        "area_type": area,
        "area_type_basis": basis,
        "population_band": band,
        "population_basis": pop_basis,
        "evacuation_consideration": evac,
        "context_gaps": gaps or [],
    }


def geo(settlements=None, hospitals=None, stations=None, police=None, roads=None) -> dict:
    """Geospatial context that RAN. Empty lists mean searched and found none."""
    return {
        "terrain_type": None,
        "region_type": None,
        "vegetation_density": None,
        "distance_to_water_m": None,
        "nearby_settlements": settlements or [],
        "nearby_hospitals": hospitals or [],
        "nearby_fire_stations": stations or [],
        "nearby_police_stations": police or [],
        "nearby_roads": roads or [],
        "nearby_green_areas": [],
        "nearby_water_sources": [],
    }


def build_cases() -> list[dict]:
    """Define all eight cases. Order matters only for filenames."""
    cases: list[dict] = []

    # ---------------------------------------------------------------- 01
    ev = detected_event(
        latitude=32.6560, longitude=35.1050, detected=True,
        confidence="low", severity="low", hotspots_count=1,
        hotspot=hotspot(32.6560, 35.1050, 2.1, "2026-09-03", "0842", "low"),
        fire_danger=fwi("low", None, 11.2),
        weather=weather(24.0, 55, 9.0, 0.0),
        geospatial=geo(
            settlements=[{"name": "Yokneam Illit", "type": "town", "population": "21000"}],
            hospitals=[{"name": "Yokneam Medical Centre"}],
            stations=[{"name": "Yokneam Fire Station"}],
            roads=[{"name": "Ha-Nasi Blvd", "type": "residential"},
                   {"name": "Route 70", "type": "trunk"}],
        ),
    )
    cases.append({
        "case_id": "fire-01-apartment-town",
        "title": "Small apartment fire in a small town",
        "hazard": "fire",
        "probes": ["proportionality", "area-type-inference", "corpus-coverage"],
        "notes": (
            "A compartment fire inside a third-floor flat is essentially invisible to "
            "VIIRS; a 2.1 MW hotspot at this location is artificial and the case does "
            "not claim the system detects apartment fires. Its value is downstream: the "
            "corpus was wildland-only until recently, so this probes whether the planner "
            "transplants defensible-space and aerial-drop doctrine into a residential "
            "building, or reaches for the structural rules of engagement instead."
        ),
        "expected_behaviour_notes": (
            "Low score. Must NOT recommend aerial_firefighting or forestry_service, and "
            "must not talk about defensible space. A fire station is 800 m away, so "
            "extended response time is not a constraint here. Occupancy is unknown and "
            "should be named as an assumption rather than asserted."
        ),
        "detected_event": ev,
        "risk_assessment": assessment(
            event=ev, score=22, confidence="medium",
            situational=situational(
                "urban_residential",
                "One settlement tagged place=town with a residential-class road and a "
                "hospital inside the search radius; no agricultural or open-natural "
                "indication is present in the collected records.",
                "10k_to_100k", "osm_population_tag", "shelter_in_place_candidate",
            ),
            drivers=["Very low fire radiative power (2.1 MW)",
                     "Low satellite detection confidence",
                     "Low fire-weather danger class",
                     "Fire station within the search radius"],
            explanation=(
                "A weak thermal signal in a residential area under low fire-weather "
                "danger. The 2.1 MW radiative power and low detection confidence are "
                "consistent with a small, contained fire rather than a spreading one, "
                "and conditions do not favour rapid spread. A fire station lies within "
                "the search radius, so response time is not a limiting factor. The "
                "dominant unknown is occupancy of the building, which the collected "
                "evidence cannot establish and which governs how aggressively crews "
                "may be committed."
            ),
            gaps=["Building occupancy is not established by the collected evidence",
                  "No information on floor of origin or internal access"],
            citations=[
                citation("usfa-risk-management-structure-fire#the-three-acceptable-risk-guidelines#0",
                         "Activities that present a significant risk",
                         "Committing crews is justified only by potential to save lives", 170),
                citation("usfa-risk-management-structure-fire#unoccupied-vacant-and-abandoned-structures#0",
                         "The distinguishing characteristics",
                         "Occupancy status drives the engagement decision", 150),
            ],
        ),
    })

    # ---------------------------------------------------------------- 02
    ev = detected_event(
        latitude=31.7420, longitude=35.0080, detected=True,
        confidence=None, severity="very_high", hotspots_count=0, hotspot=None,
        fire_danger=fwi("very_high", 38.0, 50.0),
        weather=weather(35.5, 17, 38.0, 0.0),
        geospatial=geo(
            settlements=[{"name": "Beit Shemesh", "type": "city", "population": "160000"},
                         {"name": "Nes Harim", "type": "village"}],
            hospitals=[],
            stations=[{"name": "Beit Shemesh Station"}],
            roads=[{"name": "Route 38", "type": "primary"}],
        ),
        report_evidence={
            "source": "Telegram public channels",
            "reports_count": 6,
            "channels": ["fireisrael7777", "Israel_Police_100"],
            "first_report_at": "2026-09-03T07:31:00Z",
            "latest_report_at": "2026-09-03T09:01:00Z",
            "candidate_confidence": 0.95,
            "matched_terms": ["שריפה", "מתפשטת", "יער", "לוחמי האש"],
            "location_precision": "settlement",
            "geocode_confidence": 0.7,
            "corroborated_by_satellite": False,
        },
    )
    cases.append({
        "case_id": "fire-02-telegram-wildfire-large",
        "title": "Legacy synthetic Telegram-only planner input (not operational)",
        "hazard": "fire",
        "probes": ["non-satellite-evidence", "confidence-calibration", "evacuation"],
        "notes": (
            "This is a legacy planner-evaluation fixture, not a runtime detection case. "
            "EA-374 forbids Telegram-only evidence from creating an operational event; "
            "runtime Telegram data may only corroborate an existing structured Fire or "
            "Flood signal. The fixture is retained only to test downstream uncertainty."
        ),
        "expected_behaviour_notes": (
            "High risk, but confidence should be no better than medium because nothing "
            "corroborates the reports. A plan that treats uncorroborated channel reports "
            "as established fact is wrong; so is one that dismisses six independent "
            "reports under very high fire danger. Evacuation of Nes Harim should feature."
        ),
        "detected_event": ev,
        "risk_assessment": assessment(
            event=ev, score=72, confidence="medium",
            situational=situational(
                "wildland_urban_interface",
                "A city and a village lie within the search radius alongside forested "
                "terrain implied by the reports; a primary road runs through the area. "
                "Records do not distinguish this from rural_settlement with certainty.",
                "over_100k", "osm_population_tag", "localised_evacuation",
                ["No satellite hotspot corroborates the reported fire"],
            ),
            drivers=["Six independent channel reports over 90 minutes",
                     "Very high fire-weather danger class (FWI 38.0-50.0)",
                     "Strong wind at 38 km/h with 17% relative humidity",
                     "Populated city and village within the search radius"],
            explanation=(
                "Multiple independent public-channel reports describe a spreading "
                "wildfire, sustained over 90 minutes, under very high fire-weather "
                "danger with strong wind and very low humidity. No satellite hotspot "
                "corroborates them, which lowers confidence in the detection but is not "
                "evidence that no fire is burning: a fire beneath canopy or between "
                "satellite passes is invisible to VIIRS. Conditions strongly favour "
                "rapid spread, and a city and a village lie within the search radius."
            ),
            gaps=["No satellite corroboration of the reported fire",
                  "Fire location known only to settlement precision",
                  "No hospital within the search radius"],
            citations=[
                citation("effis-fire-weather-index#interpreting-the-classes-operationally#0",
                         "Conditions support fire behaviour that can exceed",
                         "Very high danger can exceed direct suppression capability", 190),
                citation("nwcg-standard-orders-watchouts#operational-use-in-assessment#0",
                         "Whether observed weather trends match Watch Out",
                         "Rising wind and falling humidity elevate risk independently", 170),
                citation("usfa-structure-triage#evacuation-planning-components#0",
                         "Evacuation plan components should incorporate",
                         "Evacuation planning components for the exposed settlements", 180),
            ],
        ),
    })

    # ---------------------------------------------------------------- 03
    ev = detected_event(
        latitude=32.7400, longitude=35.0350, detected=True,
        confidence="high", severity="very_extreme", hotspots_count=12,
        hotspot=hotspot(32.7400, 35.0350, 180.4, "2026-09-03", "0905", "high"),
        fire_danger=fwi("very_extreme", 70.0, None),
        weather=weather(41.0, 11, 55.0, 0.0),
        geospatial=geo(
            settlements=[{"name": "Isfiya", "type": "town", "population": "12000"},
                         {"name": "Nir Etzion", "type": "village", "population": "700"}],
            hospitals=[{"name": "Carmel Clinic"}],
            stations=[],
            roads=[{"name": "Route 672", "type": "secondary"}],
        ),
    )
    cases.append({
        "case_id": "fire-03-carmel-wui-extreme",
        "title": "Extreme wildland-urban interface fire on the Carmel",
        "hazard": "fire",
        "probes": ["critical-mobilisation", "safety-preconditions", "extended-response"],
        "notes": (
            "The most severe case in the suite, modelled on Carmel-type conditions: "
            "khamsin wind, single-digit-teens humidity, very extreme fire weather, and "
            "no fire station inside the search radius."
        ),
        "expected_behaviour_notes": (
            "Critical. Should mobilise broadly including aerial_firefighting and "
            "home_front_command, address evacuation of both settlements, and name the "
            "absent fire station as an extended-response constraint. Crucially it must "
            "state safety preconditions on engagement rather than assuming they hold — "
            "at very extreme FWI, direct attack on the head is not viable."
        ),
        "detected_event": ev,
        "risk_assessment": assessment(
            event=ev, score=93, confidence="high",
            situational=situational(
                "wildland_urban_interface",
                "Two settlements tagged place=town and place=village sit within the "
                "search radius on wooded Carmel terrain, served by a single "
                "secondary-class road.",
                "10k_to_100k", "osm_population_tag", "large_scale_evacuation",
            ),
            drivers=["Twelve hotspots with 180.4 MW peak radiative power",
                     "High satellite detection confidence",
                     "Very extreme fire-weather danger (FWI above 70)",
                     "Khamsin wind at 55 km/h with 11% relative humidity",
                     "Two settlements exposed and no fire station in radius"],
            explanation=(
                "A confirmed, high-intensity fire under the most severe fire-weather "
                "class the index defines. Twelve hotspots and 180 MW radiative power "
                "indicate an established, actively spreading fire, and 55 km/h wind with "
                "11% humidity will drive rapid rate of spread through cured fuels. Two "
                "settlements totalling roughly 12,700 people lie within the search "
                "radius, and no fire station was found inside it, so initial-attack "
                "resources must travel. At this danger class, control efforts at the "
                "head of the fire should be expected to fail."
            ),
            gaps=["Wind direction not reported, only speed",
                  "No fire station within the search radius, so response time is unknown"],
            citations=[
                citation("effis-fire-weather-index#interpreting-the-classes-operationally#0",
                         "Reserved for the most severe observed conditions",
                         "Very extreme conditions: assume head attack fails", 170),
                citation("nwcg-standard-orders-watchouts#lces-lookouts-communications-escape-routes-safety#0",
                         "LCES is the framework wildland firefighters use",
                         "Safety preconditions must be established before engagement", 180),
                citation("usfa-structure-triage#the-scarce-resource-problem#0",
                         "There are never enough resources to protect every",
                         "Structure triage under scarce resources", 170),
            ],
        ),
    })

    # ---------------------------------------------------------------- 04
    ev = detected_event(
        latitude=30.6100, longitude=34.8000, detected=True,
        confidence="nominal", severity="moderate", hotspots_count=1,
        hotspot=hotspot(30.6100, 34.8000, 14.2, "2026-09-03", "0855", "nominal"),
        fire_danger=fwi("moderate", 11.2, 21.3),
        weather=weather(33.0, 24, 15.0, 0.0),
        geospatial=geo(),   # ran, found absolutely nothing
    )
    cases.append({
        "case_id": "fire-04-negev-open-nothing-nearby",
        "title": "Moderate hotspot in open Negev with nothing exposed",
        "hazard": "fire",
        "probes": ["proportionality", "over-response", "grounded-none-nearby"],
        "notes": (
            "The geospatial layer RAN and returned zero of everything. That is a real "
            "empty result, not a failure, so the counts are 0 rather than null and "
            "population_band none_nearby is a grounded answer rather than an unknown."
        ),
        "expected_behaviour_notes": (
            "The correct plan here is minimal: monitor, verify, and do not commit. "
            "Over-response is the failure mode this case exists to catch. Recommending "
            "evacuation, structure protection or a large mobilisation is wrong when "
            "nothing is exposed and conditions are only moderate."
        ),
        "detected_event": ev,
        "risk_assessment": assessment(
            event=ev, score=18, confidence="medium",
            situational=situational(
                "open_natural",
                "The geospatial search ran and returned no settlements, roads, hospitals "
                "or stations within the radius, which is consistent with open desert "
                "terrain rather than any populated or cultivated area.",
                "none_nearby", "osm_population_tag", "not_indicated",
            ),
            drivers=["Single hotspot at moderate radiative power (14.2 MW)",
                     "Moderate fire-weather danger class",
                     "No settlements, roads or infrastructure within the search radius"],
            explanation=(
                "A single moderate-intensity hotspot in open terrain with nothing "
                "exposed. The geospatial search ran and returned no settlements, roads, "
                "hospitals or fire stations within the radius, so there are no values at "
                "risk in the immediate area. Fire-weather danger is moderate, meaning "
                "spread rates are generally within initial-attack capability. The "
                "operational priority is verification and monitoring rather than "
                "commitment of resources."
            ),
            gaps=["Nothing beyond the search radius is characterised"],
            citations=[
                citation("effis-fire-weather-index#interpreting-the-classes-operationally#0",
                         "Low and Moderate",
                         "Moderate danger is within initial-attack capability", 170),
                citation("usfa-risk-management-structure-fire#the-three-acceptable-risk-guidelines#0",
                         "No risk to the safety of members shall be acceptable",
                         "No risk is acceptable where nothing can be saved", 130),
            ],
        ),
    })

    # ---------------------------------------------------------------- 05
    ev = detected_event(
        latitude=33.0100, longitude=35.3400, detected=True,
        confidence="low", severity="low", hotspots_count=1,
        hotspot=hotspot(33.0100, 35.3400, 1.8, "2026-08-30", "2214", "low"),
        fire_danger=fwi("low", None, 11.2),
        weather=weather(18.0, 82, 5.0, 12.0),
        geospatial=geo(
            settlements=[{"name": "Peqi'in", "type": "village", "population": "5800"}],
            stations=[{"name": "Ma'alot Station"}],
            roads=[{"name": "Route 89", "type": "secondary"}],
        ),
    )
    cases.append({
        "case_id": "fire-05-stale-weak-detection",
        "title": "Four-day-old weak hotspot with rain since",
        "hazard": "fire",
        "probes": ["stale-evidence", "assumptions", "no-search-on-weak-evidence"],
        "notes": (
            "Acquisition is four days before the assessment timestamp and 12 mm of rain "
            "is in the weather record. This is the case that must NOT trigger a web "
            "search: the gap-filling rules forbid spending on an event that may not be "
            "real."
        ),
        "expected_behaviour_notes": (
            "Low score, low confidence. The plan should be reconnaissance before "
            "commitment, and 'this reflects an active fire' belongs in assumptions "
            "rather than being taken as given. Mobilising suppression for a four-day-old "
            "1.8 MW signal after rain is over-response."
        ),
        "detected_event": ev,
        "risk_assessment": assessment(
            event=ev, score=9, confidence="low",
            situational=situational(
                "rural_settlement",
                "A single settlement tagged place=village lies within the radius with a "
                "secondary road; no urban density or industrial indication is present.",
                "1k_to_10k", "osm_population_tag", "not_indicated",
            ),
            drivers=["Hotspot acquired four days before assessment",
                     "Very low radiative power (1.8 MW) and low confidence",
                     "12 mm of precipitation recorded since",
                     "Low fire-weather danger class"],
            explanation=(
                "The only satellite evidence is four days old, weak at 1.8 MW, and "
                "carries low detection confidence. Twelve millimetres of precipitation "
                "appear in the weather record since acquisition, and current conditions "
                "are cool and humid under the lowest fire-weather danger class. Taken "
                "together the evidence does not support an actively burning fire, though "
                "it does not exclude a smouldering remnant. The proportionate action is "
                "verification rather than suppression."
            ),
            gaps=["No satellite pass since the original acquisition",
                  "Whether the hotspot was ever a fire is unconfirmed"],
            citations=[
                citation("effis-fire-weather-index#interpreting-the-classes-operationally#0",
                         "Low and Moderate",
                         "Low danger implies spread within initial-attack capability", 160),
                citation("usfa-risk-management-structure-fire#known-versus-assumed-risk-factors#0",
                         "An Incident Commander must consciously differentiate",
                         "Known versus assumed factors must be separated", 170),
            ],
        ),
    })

    # ---------------------------------------------------------------- 06
    ev = detected_event(
        latitude=31.2500, longitude=34.9800, detected=True,
        confidence="high", severity=None, hotspots_count=4,
        hotspot=hotspot(31.2500, 34.9800, 76.5, "2026-09-03", "0858", "high"),
        fire_danger=None,
        weather={"current": {}, "forecast": {"daily": {}}},
        geospatial=None,
    )
    cases.append({
        "case_id": "fire-06-degraded-all-sources-failed",
        "title": "Solid detection, every enrichment source failed",
        "hazard": "fire",
        "probes": ["honesty-under-missing-data", "null-versus-zero", "gap-filling"],
        "notes": (
            "The most important case in the suite. FIRMS worked and the detection is "
            "strong, but fire weather, current conditions and geospatial context all "
            "failed. This is also the strongest gap-filling case: a bare coordinate with "
            "a credible fire is exactly what the web lookup exists for."
        ),
        "expected_behaviour_notes": (
            "Confidence must be low and the gaps must be explicit. The derived counts "
            "must be null, not zero — nothing was searched. area_type unknown and "
            "population_basis no_basis are correct unless a lookup supplied them. The "
            "plan must not assume structures, roads or absent exposure; a plan that "
            "quietly treats 'no data' as 'nothing there' fails this case."
        ),
        "detected_event": ev,
        "risk_assessment": assessment(
            event=ev, score=55, confidence="low",
            situational=situational(
                "unknown",
                "The geospatial search did not run, so nothing distinguishes open "
                "natural terrain from an agricultural or populated area at this "
                "coordinate. No basis exists to choose between them.",
                "unknown", "no_basis", "unknown",
                ["Geospatial context unavailable; exposure is entirely unknown",
                 "Fire weather index unavailable; spread potential cannot be assessed"],
            ),
            drivers=["Four hotspots with 76.5 MW radiative power",
                     "High satellite detection confidence",
                     "No fire weather, current conditions or exposure data available"],
            explanation=(
                "Satellite evidence is strong: four hotspots with 76.5 MW radiative "
                "power at high confidence indicate a real, actively burning fire. Every "
                "enrichment source failed, so fire-weather danger, current conditions "
                "and exposure are all unavailable. The score reflects credible detection "
                "with entirely unknown context, and confidence is low accordingly. "
                "Nothing here supports a judgement about spread potential or what is at "
                "risk, and the absence of exposure data is not evidence that nothing is "
                "exposed."
            ),
            gaps=["GWIS/EFFIS unavailable, so fire-weather danger is unknown",
                  "Open-Meteo unavailable, so wind and humidity are unknown",
                  "OpenStreetMap unavailable, so exposure and response capacity are unknown"],
            citations=[
                citation("usfa-risk-management-structure-fire#known-versus-assumed-risk-factors#0",
                         "It is often impossible to obtain and verify all",
                         "Decisions must be made on incomplete information, flagged as such", 190),
                citation("usfa-risk-management-structure-fire#continuous-reassessment#0",
                         "A risk assessment should be reprocessed with every",
                         "Reassess as the missing information arrives", 160),
            ],
        ),
    })

    # ---------------------------------------------------------------- 07
    ev = detected_event(
        latitude=31.7900, longitude=34.6500, detected=True,
        confidence="high", severity="high", hotspots_count=3,
        hotspot=hotspot(31.7900, 34.6500, 121.0, "2026-09-03", "0901", "high"),
        fire_danger=fwi("high", 21.3, 38.0),
        weather=weather(32.0, 40, 22.0, 0.0),
        geospatial=geo(
            settlements=[],                       # no place= tag in radius
            hospitals=[{"name": "Assuta Ashdod"}],
            stations=[],
            roads=[{"name": "Route 4", "type": "trunk"},
                   {"name": "Ha-Melacha", "type": "trunk"}],
        ),
    )
    cases.append({
        "case_id": "fire-07-industrial-zone",
        "title": "High-intensity fire in an industrial zone",
        "hazard": "fire",
        "probes": ["industrial-inference", "utility-isolation", "fabrication-trap"],
        "notes": (
            "Trunk-class roads and a hospital nearby but no place= settlement in the "
            "radius, which is the signature of an industrial or logistics zone rather "
            "than a residential area. The fabrication trap: the corpus contains nothing "
            "on hazardous materials, so a plan that invents hazmat protocol and cites it "
            "should be penalised, while one that names the limitation in assumptions "
            "should not."
        ),
        "expected_behaviour_notes": (
            "utility_operator should appear for power isolation. Structure protection is "
            "reasonable; evacuation of residents is not, since no settlement is in "
            "radius. Any hazmat handling must be flagged as outside available guidance "
            "rather than cited to a protocol that does not exist."
        ),
        "detected_event": ev,
        "risk_assessment": assessment(
            event=ev, score=68, confidence="medium",
            situational=situational(
                "industrial",
                "Two trunk-class roads and a hospital fall within the radius while no "
                "settlement carries a place= tag, a pattern consistent with an "
                "industrial or logistics zone rather than a residential area.",
                "none_nearby", "osm_population_tag", "shelter_in_place_candidate",
                ["Occupancy and contents of the affected premises are unknown"],
            ),
            drivers=["Three hotspots at 121 MW radiative power",
                     "High satellite detection confidence",
                     "High fire-weather danger class",
                     "Trunk roads and a hospital within the radius, no residential settlement"],
            explanation=(
                "A high-intensity fire with 121 MW radiative power and high detection "
                "confidence under high fire-weather danger. The surrounding records show "
                "trunk-class roads and a hospital but no tagged settlement, which points "
                "to an industrial or logistics area. Contents of the affected premises "
                "are unknown, and that matters here more than in vegetation fires "
                "because it governs both the hazard to responders and whether nearby "
                "occupied buildings must shelter in place."
            ),
            gaps=["Contents and hazardous materials at the site are unknown",
                  "No fire station within the search radius"],
            citations=[
                citation("usfa-risk-management-structure-fire#rules-of-engagement-offensive-or-defensive#0",
                         "The decision to operate offensively",
                         "Offensive versus defensive posture for a structure fire", 180),
                citation("usfa-risk-management-structure-fire#specialist-capability-as-a-constraint#0",
                         "Where an incident requires skills or equipment",
                         "Specialist capability must be present or the action waits", 170),
            ],
        ),
    })

    # ---------------------------------------------------------------- 08
    ev = detected_event(
        latitude=32.0853, longitude=34.7818, detected=None,
        collection_status="failed", satellite_error="timeout",
    )
    cases.append({
        "case_id": "fire-08-detection-unavailable",
        "title": "Satellite detection unavailable",
        "hazard": "fire",
        "probes": ["refusal", "zero-cost", "gate"],
        "notes": (
            "detected is None: FIRMS could not be reached, so whether a fire exists is "
            "unknown. This is distinct from detected False, which means the scan ran and "
            "found nothing. The frozen assessment is deliberately the skipped shape."
        ),
        "expected_behaviour_notes": (
            "The pipeline must refuse: risk skipped, planning skipped, ZERO model calls "
            "and zero cost. The judge must score this refusal as correct rather than "
            "treating an empty plan as a bad plan. If any model call is made for this "
            "case, that is a defect."
        ),
        "detected_event": ev,
        "risk_assessment": assessment(
            event=ev, score=None, confidence=None, situational=None,
            drivers=None, explanation=None, gaps=None, citations=None,
            status="skipped", reason="detection_unavailable",
        ),
    })

    return cases


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    cases = build_cases()

    for index, case in enumerate(cases, start=1):
        # removeprefix, not replace: "fire-02-telegram-wildfire-large" contains
        # "fire-" twice, and replace() would mangle "wildfire-large".
        slug = case["case_id"].removeprefix("fire-").removeprefix(f"{index:02d}-")
        path = OUTPUT_DIR / f"case_{index:02d}_{slug.replace('-', '_')}.json"
        path.write_text(
            json.dumps(case, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        citations = (case["risk_assessment"].get("grounding") or {}).get("citations", [])
        print(f"  wrote {path.name:44} citations={len(citations)}")

    print(f"\n{len(cases)} cases written to {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
