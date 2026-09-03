"""
Risk Analysis Agent

Responsible for turning a real detected-fire event from FireDetectionAgent into
an operational risk assessment, grounded in retrieved fire-protocol text.

This replaces an earlier stub that branched on a hardcoded event_type string and
returned fixed numbers. Two things changed. It now consumes the actual nested
event object, and its judgement is produced by a Claude call that may only cite
protocol passages retrieved from data/protocols — every citation is verified in
Python against the chunk it claims to quote before the result is returned.

What this agent does NOT do:
    It does not produce a response plan or a unit list. Those belong to
    ResponsePlanningAgent. The separation mirrors the one FireDetectionAgent
    already maintains between satellite confidence, fire-weather severity and
    operational risk — the detection agent explicitly refuses to compute a risk
    score, and by the same logic risk is not a response plan.

The no-fabrication rule:
    Every failure and skip path returns ``risk_score: None`` and
    ``risk_level: None`` — never 0, never "low". Absence of a detection is not
    evidence of low risk, and a provider outage is not evidence of safety. This
    is the single most important property of the module and the reason
    risk_level is nullable all the way out to the frontend.

Degradation ladder for a detected event, in order:
    1. No Claude credentials      -> failed, "missing credentials", no call made
    2. Retrieval returns nothing  -> failed, no call made
    3. Claude raises              -> failed, with the sanitized error category
    4. No citation verifies       -> failed, "ungrounded response"
    5. Otherwise                  -> success

There is deliberately no ungrounded fallback. Answering from the model's general
knowledge and presenting it as protocol-derived is precisely the fabrication
this sprint exists to remove.

Consumed by: backend.main.get_detected_events
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from agents.risk_analysis_schemas import RiskAssessment, risk_level_for_score
from services.claude_llm_service import (
    ClaudeLLMService,
    ClaudeProviderError,
    build_system_blocks,
)
from services.protocol_retrieval_service import ProtocolRetriever, verify_citations

AGENT_NAME = "RiskAnalysisAgent"

DEFAULT_TOP_K = 5

# Disambiguates this score from FireRiskPredictionAgent's, which shares the
# field names `risk_score` and `risk_level` but means something different and
# uses a different scale:
#
#   estimated_fire_risk               0.0-1.0 probability that a fire STARTS
#                                     here, low/medium/high, from the ML model
#   detected_event_operational_risk   0-100 severity of a fire that ALREADY
#                                     EXISTS, low/medium/high/critical, here
#
# A consumer that confuses 0.85 with 85 would be off by two orders of
# magnitude, so every consumer must branch on this field rather than on the
# score alone.
RISK_SEMANTICS = "detected_event_operational_risk"

# Thresholds used only to steer retrieval toward the right protocol sections.
# They are not scoring rules — the model does the judging, against the evidence
# and the retrieved text.
STRONG_WIND_KMH = 30.0
LOW_HUMIDITY_PERCENT = 30.0
HIGH_TEMPERATURE_C = 35.0
HIGH_FRP = 50.0

RISK_SYSTEM_PROMPT = """\
You are the risk analysis component of EcoGuard Agents, a multi-agent system for
environmental crisis management in Israel. You assess wildfire events that have
been detected by satellite and enriched with fire-weather, meteorological and
geospatial data.

Your job is to produce one operational risk assessment for one detected fire,
grounded in the fire-protocol excerpts supplied with each request.

## What operational risk means here

Operational risk is not the same as fire-weather severity, and it is not the
same as satellite detection confidence. Those are two inputs among several.
Operational risk expresses how urgently and how heavily this event needs to be
responded to, combining:

- How strong the evidence is that a real fire is burning (satellite detection
  confidence, number of hotspots, fire radiative power).
- How favourable conditions are to rapid spread and difficult control
  (fire-weather danger class, wind, humidity, temperature).
- What is exposed (nearby settlements, hospitals, roads) and what response
  capacity is nearby (fire stations).

A high fire-weather danger class with weak detection evidence is not the same as
a confirmed high-intensity fire in moderate conditions. Say which situation you
are looking at.

## The 0-100 scale

- 0-24 (low): Weak or stale evidence, unfavourable conditions for spread, and
  nothing significant exposed.
- 25-49 (medium): A credible event, but conditions or exposure are limited.
  Monitoring and verification are the proportionate response.
- 50-79 (high): Credible event with conditions supporting spread, or meaningful
  exposure of people and infrastructure. Active response is warranted.
- 80-100 (critical): Strong evidence, conditions that can exceed direct
  suppression capability, and significant exposure. Immediate large-scale
  response and life-safety measures are warranted.

Do not report a risk band or level. Report only the numeric score. The band is
derived from your score by the calling system, so a score and a band cannot
disagree.

## Fire Weather Index reference

The fire_weather_severity field comes from the GWIS/EFFIS implementation of the
Canadian Fire Weather Index. Its classes are: low (FWI below 11.2), moderate
(11.2-21.3), high (21.3-38.0), very_high (38.0-50.0), extreme (50.0-70.0), and
very_extreme (above 70.0). The steps between the upper classes represent
substantially greater difficulty of control, not proportional increases.

## Grounding rules — these are strict

The user message contains protocol excerpts, each preceded by a marker of the
form [chunk_id: some-id]. These excerpts are the only source you may cite.

1. Every citation's chunk_id must be copied character-for-character from a
   [chunk_id: ...] marker in this request. Never construct, guess, abbreviate or
   adapt an id.
2. Every quoted_text must be a verbatim span copied from the body of that same
   chunk. Do not paraphrase, do not correct, do not join text from two chunks.
3. Cite at least one passage and at most six. Each citation's `supports` field
   must state which part of your assessment that passage backs up.
4. If the excerpts do not address something your assessment depends on, record
   it in evidence_gaps. Do not cite from memory, and do not present general
   knowledge as though it came from the protocols.

Citations are verified programmatically against the excerpts you were given. A
citation whose id was not supplied, or whose quote does not appear in that
chunk, is discarded, and an assessment left with no surviving citation is
rejected in full. Quoting accurately is therefore not a formality.

## Handling incomplete evidence

The enrichment sources can fail independently. The evidence summary states which
ones did. When a source is unavailable:

- Do not assume a safe value in its place. Missing wind data is not calm wind.
- Lower your `confidence` to reflect what you could not see.
- Record the specific gap in evidence_gaps.

Some geospatial fields are never populated by the current pipeline —
terrain_type, region_type, vegetation_density, distance_to_water_m, nearby green
areas and nearby water sources are always absent. Do not treat their absence as
meaningful, and do not list them as evidence gaps; they are a known limitation
of the collection layer rather than a property of this event.

## Style

Write the explanation for an emergency operations officer reading it under time
pressure. Be specific about numbers and name the drivers. State uncertainty
plainly rather than hedging everything.
"""


class RiskAnalysisAgent:
    """
    Produces a protocol-grounded risk assessment for a detected fire event.

    Both collaborators are injected so the agent is fully testable offline; the
    defaults are real implementations for production use.

    Attributes:
        llm_service: Anything exposing ``available`` and ``parse_structured``.
        retriever: Anything exposing ``retrieve(query, top_k) -> list[dict]``.
        top_k (int): Number of protocol chunks to retrieve per assessment.
    """

    def __init__(
        self,
        *,
        llm_service: object | None = None,
        retriever: object | None = None,
        top_k: int = DEFAULT_TOP_K,
    ) -> None:
        self.llm_service = llm_service if llm_service is not None else ClaudeLLMService()
        self.retriever = retriever if retriever is not None else ProtocolRetriever()
        self.top_k = top_k

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def analyze_event(self, detected_event: dict) -> dict:
        """
        Assess one detected fire event.

        Args:
            detected_event (dict): A FireDetectionAgent result. All three of its
                shapes are accepted — detected True, False, or None.

        Returns:
            dict: A risk assessment. metadata.analysis_status is "success",
                "failed" or "skipped"; risk_score and risk_level are None for
                everything except "success".
        """
        if not isinstance(detected_event, dict):
            return self.build_skipped_assessment({}, "unsupported_event")

        if detected_event.get("event_type") != "fire":
            return self.build_skipped_assessment(detected_event, "unsupported_event")

        detected = detected_event.get("detected")

        # Identity comparisons, never truthiness. The True/False/None distinction
        # is load-bearing: False means FIRMS ran and found nothing, None means
        # FIRMS could not be reached. Those are different facts and must not
        # collapse into one another.
        if detected is False:
            return self.build_skipped_assessment(detected_event, "no_event")

        if detected is not True:
            return self.build_skipped_assessment(detected_event, "detection_unavailable")

        return self.assess_detected_event(detected_event)

    def assess_detected_event(self, detected_event: dict) -> dict:
        """
        Run the grounded assessment for a confirmed detection.

        Args:
            detected_event (dict): An event with detected is True.

        Returns:
            dict: Risk assessment, following the degradation ladder in the
                module docstring.
        """
        # Checked before retrieval so a missing key costs nothing.
        if not getattr(self.llm_service, "available", False):
            return self.build_failed_assessment(detected_event, "missing credentials")

        query = self.build_query(detected_event)
        chunks = self.retriever.retrieve(query, top_k=self.top_k)

        if not chunks:
            corpus_loaded = getattr(self.retriever, "available", True)
            error = "no protocol match" if corpus_loaded else "protocol corpus unavailable"
            logging.error("Risk analysis aborted before the model call: %s", error)
            return self.build_failed_assessment(detected_event, error)

        system_blocks, user_text = self.build_prompt(detected_event, chunks)

        try:
            assessment = self.llm_service.parse_structured(
                system_blocks=system_blocks,
                user_text=user_text,
                output_format=RiskAssessment,
            )
        except ClaudeProviderError as error:
            logging.error("Risk analysis model call failed: %s", error)
            return self.build_failed_assessment(detected_event, str(error))

        payload = assessment.model_dump(mode="json")

        verified, dropped = verify_citations(payload["protocol_citations"], chunks)

        if not verified:
            # The model answered but could not show its work against the text it
            # was given. Keeping the score would present ungrounded reasoning as
            # protocol-derived, which is the thing this design refuses to do.
            logging.error(
                "Risk analysis discarded: no citation verified (%s dropped)", dropped
            )
            return self.build_failed_assessment(detected_event, "ungrounded response")

        return self.build_risk_assessment(
            detected_event=detected_event,
            payload=payload,
            chunks=chunks,
            citations=verified,
            dropped=dropped,
        )

    # ------------------------------------------------------------------
    # Query construction
    # ------------------------------------------------------------------

    def build_query(self, detected_event: dict) -> str:
        """
        Build the retrieval query from the event's evidence.

        Query building lives here rather than in the retriever so the retriever
        stays domain-agnostic and swappable. This query deliberately targets
        classification and danger-rating language; the planning agent builds a
        different query aimed at action sections of the same corpus.

        Args:
            detected_event (dict): A detected event.

        Returns:
            str: A bag of terms for BM25.
        """
        terms = [
            "wildfire fire behaviour risk assessment severity",
            "fire danger rating class index",
        ]

        severity = detected_event.get("fire_weather_severity")
        if severity and severity != "unknown":
            terms.append(f"{severity.replace('_', ' ')} fire danger class")
            if severity in {"very_high", "extreme", "very_extreme"}:
                terms.append("extreme conditions exceed suppression capability control")

        confidence = detected_event.get("detection_confidence")
        if confidence:
            terms.append(f"satellite thermal detection confidence {confidence}")

        satellite = self._section(detected_event, "satellite_evidence")
        hotspot = satellite.get("selected_hotspot")
        if isinstance(hotspot, dict):
            frp = self._number(hotspot.get("frp"))
            if frp is not None and frp >= HIGH_FRP:
                terms.append("high intensity fire radiative power active flaming front")

        current = self._section(self._section(detected_event, "weather_context"), "current")

        wind = self._number(current.get("wind_speed_kmh"))
        if wind is not None and wind >= STRONG_WIND_KMH:
            terms.append("strong wind increases rate of spread wind driven")

        humidity = self._number(current.get("humidity_percent"))
        if humidity is not None and humidity <= LOW_HUMIDITY_PERCENT:
            terms.append("low relative humidity dry cured fine fuels moisture")

        temperature = self._number(current.get("temperature_c"))
        if temperature is not None and temperature >= HIGH_TEMPERATURE_C:
            terms.append("hotter and drier weather temperature")

        geospatial = self._section(detected_event, "geospatial_context")
        if geospatial.get("nearby_settlements"):
            terms.append(
                "values at risk structures populated settlement wildland urban interface"
            )
        if not geospatial.get("nearby_fire_stations"):
            terms.append("remote access extended response time")

        return " ".join(terms)

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def build_prompt(self, detected_event: dict, chunks: list[dict]) -> tuple[list[dict], str]:
        """
        Build the system blocks and user message for the model call.

        The system prompt is stable across requests and marked for caching. The
        evidence and the retrieved excerpts vary per request and therefore go in
        the user message, after the cached prefix.

        Args:
            detected_event (dict): The event being assessed.
            chunks (list[dict]): Retrieved protocol chunks.

        Returns:
            tuple[list[dict], str]: System blocks and user text.
        """
        evidence = self.build_evidence_summary(detected_event)
        excerpts = render_excerpts(chunks)

        user_text = (
            "# Detected fire event\n\n"
            f"{evidence}\n\n"
            "# Protocol excerpts\n\n"
            "These are the only passages you may cite. Copy chunk ids exactly.\n\n"
            f"{excerpts}\n\n"
            "# Task\n\n"
            "Assess the operational risk of this event. Cite the excerpts that "
            "support your reasoning, and record anything the evidence or the "
            "excerpts could not tell you in evidence_gaps."
        )

        return build_system_blocks(RISK_SYSTEM_PROMPT), user_text

    def build_evidence_summary(self, detected_event: dict) -> str:
        """
        Render the event as readable evidence. Delegates to the module function.

        Kept as a method so the agent reads consistently with its other
        ``build_*`` builders, while the implementation stays module-level and
        importable by the planning agent.
        """
        return build_evidence_summary(detected_event)

    def describe_unavailable_sources(self, detected_event: dict) -> list[str]:
        """Name the enrichment sources that failed. Delegates to the module function."""
        return describe_unavailable_sources(detected_event)

    # ------------------------------------------------------------------
    # Response builders
    # ------------------------------------------------------------------

    def build_risk_assessment(
        self,
        *,
        detected_event: dict,
        payload: dict,
        chunks: list[dict],
        citations: list[dict],
        dropped: int,
    ) -> dict:
        """
        Build a successful assessment from a validated model response.

        Args:
            detected_event (dict): The event assessed.
            payload (dict): RiskAssessment.model_dump(mode="json").
            chunks (list[dict]): Chunks that were retrieved.
            citations (list[dict]): Citations that survived verification.
            dropped (int): How many citations failed verification.

        Returns:
            dict: The unified risk assessment.
        """
        risk_score = payload["risk_score"]

        return {
            "metadata": {
                "timestamp": self._timestamp(),
                "agent": AGENT_NAME,
                "analysis_status": "success",
                "model": getattr(self.llm_service, "model", None),
                "reason": None,
            },
            "event_id": build_event_id(detected_event),
            "event_type": "fire",
            "location": self._section(detected_event, "location"),
            "risk_score": risk_score,
            # Derived here, never asked of the model, so the two cannot disagree.
            "risk_level": risk_level_for_score(risk_score),
            "risk_semantics": RISK_SEMANTICS,
            "confidence": payload["confidence"],
            "primary_drivers": payload["primary_drivers"],
            "explanation": payload["explanation"],
            "evidence_gaps": payload["evidence_gaps"],
            "grounding": self.build_grounding(chunks, citations, dropped),
            "error": None,
        }

    def build_skipped_assessment(self, detected_event: dict, reason: str) -> dict:
        """
        Build an assessment for an event that was never a candidate.

        Note risk_score and risk_level are None, not 0 and "low". No detection
        does not mean no risk — it means no information.

        Args:
            detected_event (dict): The event, possibly empty.
            reason (str): "no_event", "detection_unavailable" or
                "unsupported_event".

        Returns:
            dict: A skipped assessment.
        """
        return self._build_empty(detected_event, status="skipped", reason=reason, error=None)

    def build_failed_assessment(self, detected_event: dict, error: str) -> dict:
        """
        Build an assessment for an event we tried and failed to assess.

        Args:
            detected_event (dict): The event.
            error (str): A category from the closed error vocabulary, or
                "ungrounded response" / "no protocol match" /
                "protocol corpus unavailable".

        Returns:
            dict: A failed assessment.
        """
        return self._build_empty(detected_event, status="failed", reason=None, error=error)

    def build_grounding(
        self, chunks: list[dict], citations: list[dict], dropped: int
    ) -> dict:
        """
        Describe what was retrieved and what survived verification.

        Args:
            chunks (list[dict]): Retrieved chunks.
            citations (list[dict]): Verified citations.
            dropped (int): Citations discarded during verification.

        Returns:
            dict: The grounding record attached to the assessment.
        """
        return {
            "retriever": "bm25",
            "retrieved_chunk_ids": [chunk["chunk_id"] for chunk in chunks],
            "citations": citations,
            "unverified_citation_count": dropped,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_empty(
        self, detected_event: dict, *, status: str, reason: str | None, error: str | None
    ) -> dict:
        """Shared shape for skipped and failed assessments."""
        return {
            "metadata": {
                "timestamp": self._timestamp(),
                "agent": AGENT_NAME,
                "analysis_status": status,
                "model": None,
                "reason": reason,
            },
            "event_id": build_event_id(detected_event),
            "event_type": detected_event.get("event_type", "fire"),
            "location": self._section(detected_event, "location"),
            "risk_score": None,
            "risk_level": None,
            # Present even with no score, so a consumer can tell which kind of
            # risk is absent rather than guessing.
            "risk_semantics": RISK_SEMANTICS,
            "confidence": None,
            "primary_drivers": [],
            "explanation": None,
            "evidence_gaps": [],
            "grounding": {
                "retriever": "bm25",
                "retrieved_chunk_ids": [],
                "citations": [],
                "unverified_citation_count": 0,
            },
            "error": error,
        }

    @staticmethod
    def _section(source: dict, key: str) -> dict:
        """
        Read a nested section, tolerating None and wrong types.

        The no-event and failed shapes set fire_danger, weather_context and
        geospatial_context to an explicit None rather than {}, so a plain
        ``.get(key, {})`` would still return None and blow up on the next
        access. This never does.
        """
        if not isinstance(source, dict):
            return {}

        value = source.get(key)
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _number(value: object) -> float | None:
        """Coerce a value to float, returning None when it is not numeric."""
        if isinstance(value, bool) or value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _timestamp() -> str:
        """UTC timestamp in the format every other agent in this project uses."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_event_id(detected_event: dict) -> str:
    """
    Build a stable identifier for a detected fire.

    Derived from the hotspot's coordinates and acquisition time, so the same
    fire keeps the same id across repeated scans. That is what lets the risk
    assessment, the response plan and the dashboard marker all refer to one
    event without a shared database.

    It is also the join key for anything downstream. A resource allocation
    agent receiving a response plan on its own must be able to tell which fire
    the plan is for; without this it would only work when the plan happened to
    arrive in the same payload as the event.

    Args:
        detected_event (dict): A FireDetectionAgent result. Tolerates the
            no-event and failed shapes, which have no hotspot.

    Returns:
        str: Twelve hex characters. Stable for a given hotspot, and stable for
            a given coordinate when no hotspot exists.
    """
    satellite = section(detected_event, "satellite_evidence")
    hotspot = satellite.get("selected_hotspot")
    hotspot = hotspot if isinstance(hotspot, dict) else {}
    location = section(detected_event, "location")

    seed = "|".join(
        str(part)
        for part in (
            hotspot.get("latitude", location.get("latitude")),
            hotspot.get("longitude", location.get("longitude")),
            hotspot.get("acquisition_date", ""),
            hotspot.get("acquisition_time", ""),
        )
    )

    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


def section(source: dict, key: str) -> dict:
    """
    Read a nested section, tolerating None and wrong types.

    The no-event and failed event shapes set fire_danger, weather_context and
    geospatial_context to an explicit None rather than {}, so a plain
    ``.get(key, {})`` still returns None and blows up on the next access. This
    never does.

    Args:
        source (dict): Containing dict.
        key (str): Section key.

    Returns:
        dict: The section, or {} when it is absent or not a dict.
    """
    if not isinstance(source, dict):
        return {}

    value = source.get(key)
    return value if isinstance(value, dict) else {}


def describe_unavailable_sources(detected_event: dict) -> list[str]:
    """
    Name the enrichment sources that failed or returned nothing.

    Shared by both agents so the model is told the same story about missing
    evidence in the assessment call and the planning call.

    Args:
        detected_event (dict): The event being assessed.

    Returns:
        list[str]: Human-readable descriptions, empty when all sources returned.
    """
    unavailable: list[str] = []

    fire_danger = detected_event.get("fire_danger")
    if not isinstance(fire_danger, dict) or fire_danger.get("collection_status") == "failed":
        unavailable.append(
            "GWIS/EFFIS fire weather index — no danger class for this coordinate"
        )

    weather = detected_event.get("weather_context")
    if not isinstance(weather, dict) or not section(weather, "current"):
        unavailable.append("Open-Meteo weather — no current conditions")

    geospatial = detected_event.get("geospatial_context")
    if not isinstance(geospatial, dict) or not geospatial:
        unavailable.append(
            "OpenStreetMap geospatial context — exposure and response capacity unknown"
        )

    return unavailable


def build_evidence_summary(detected_event: dict) -> str:
    """
    Render a detected event as readable evidence, including what is missing.

    Only fields actually present are rendered, and failed enrichment sources are
    named explicitly. The model needs to know what it could not see — that is
    what makes its evidence_gaps and confidence honest rather than decorative.

    Module-level rather than a method because both agents render the same
    evidence and a second, drifting copy would be worse than a shared function.

    Args:
        detected_event (dict): The event being assessed.

    Returns:
        str: Markdown evidence summary.
    """
    lines: list[str] = []

    location = section(detected_event, "location")
    latitude = location.get("latitude")
    longitude = location.get("longitude")
    if latitude is not None and longitude is not None:
        lines.append(f"- Location: {latitude}, {longitude}")

    timestamp = section(detected_event, "metadata").get("timestamp")
    if timestamp:
        lines.append(f"- Detected at: {timestamp}")

    confidence = detected_event.get("detection_confidence")
    if confidence:
        lines.append(f"- Satellite detection confidence: {confidence}")

    severity = detected_event.get("fire_weather_severity")
    if severity:
        lines.append(f"- Fire weather severity (GWIS/EFFIS FWI class): {severity}")

    fire_danger = section(detected_event, "fire_danger")
    fwi_min = fire_danger.get("fwi_min")
    fwi_max = fire_danger.get("fwi_max")
    if fwi_min is not None or fwi_max is not None:
        lines.append(f"- FWI band for that class: {fwi_min} to {fwi_max}")

    satellite = section(detected_event, "satellite_evidence")
    count = satellite.get("hotspots_count")
    if count is not None:
        lines.append(f"- Satellite hotspots within the search radius: {count}")

    hotspot = satellite.get("selected_hotspot")
    if isinstance(hotspot, dict):
        details = []
        if hotspot.get("frp") is not None:
            details.append(f"fire radiative power {hotspot['frp']} MW")
        if hotspot.get("acquisition_date"):
            details.append(f"acquired {hotspot['acquisition_date']}")
        if hotspot.get("satellite"):
            details.append(f"satellite {hotspot['satellite']}")
        if hotspot.get("daynight"):
            details.append(f"day/night flag {hotspot['daynight']}")
        if details:
            lines.append(f"- Strongest hotspot: {', '.join(details)}")

    current = section(section(detected_event, "weather_context"), "current")
    if current:
        weather_bits = []
        for label, key, unit in (
            ("temperature", "temperature_c", "C"),
            ("relative humidity", "humidity_percent", "%"),
            ("wind speed", "wind_speed_kmh", "km/h"),
            ("precipitation", "precipitation_mm", "mm"),
        ):
            value = current.get(key)
            if value is not None:
                weather_bits.append(f"{label} {value} {unit}")
        if weather_bits:
            lines.append(f"- Current weather: {', '.join(weather_bits)}")

    geospatial = section(detected_event, "geospatial_context")
    if geospatial:
        for label, key in (
            ("settlements", "nearby_settlements"),
            ("hospitals", "nearby_hospitals"),
            ("fire stations", "nearby_fire_stations"),
            ("police stations", "nearby_police_stations"),
            ("main roads", "nearby_roads"),
        ):
            items = geospatial.get(key) or []
            names = [i.get("name") for i in items if isinstance(i, dict) and i.get("name")]
            if names:
                lines.append(f"- Nearby {label} ({len(items)}): {', '.join(names[:5])}")
            else:
                lines.append(f"- Nearby {label}: none found within the search radius")

    unavailable = describe_unavailable_sources(detected_event)
    if unavailable:
        lines.append("")
        lines.append("Enrichment sources that did not return data for this event:")
        lines.extend(f"- {item}" for item in unavailable)

    return "\n".join(lines) if lines else "- No usable evidence was collected."


def render_excerpts(chunks: list[dict]) -> str:
    """
    Render retrieved chunks for the prompt, each tagged with its chunk id.

    The ``[chunk_id: ...]`` marker is what the model copies into its citations
    and what verification matches against, so the format is a contract between
    this function, the system prompt's grounding rules, and verify_citations.

    Args:
        chunks (list[dict]): Retrieved protocol chunks.

    Returns:
        str: Markdown excerpt block.
    """
    rendered = []

    for chunk in chunks:
        heading = chunk.get("heading_path") or chunk.get("document_title", "")
        rendered.append(
            f"[chunk_id: {chunk['chunk_id']}]\n{heading}\n\n{chunk['text']}"
        )

    return "\n\n---\n\n".join(rendered)
