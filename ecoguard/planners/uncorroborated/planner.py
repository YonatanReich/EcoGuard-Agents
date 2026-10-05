"""What to tell an operator about a report nothing has confirmed.

No model call: the useful answer is who to contact - the police station
responsible for that area, with its number, the local authority, and for a fire
the nearest station and 102. All of that is a lookup, and a lookup is
deterministic, free and always available, which is what an unverified report
deserves.

This planner no longer implies that nothing was analysed. A hazard with an
analyser is analysed whether or not it is confirmed; what this card replaces is
the *mobilisation* plan, not the assessment. Pass `analysis_performed=True` when
an assessment sits beside it, so the limitations say so."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from ecoguard.shared.activity import live_actor

logger = logging.getLogger(__name__)

AGENT_NAME = "UncorroboratedReportAdvisor"

# The national emergency numbers, as the fallback when the point resolves to no
# town and no station — offshore, over a border, or a gazetteer miss. An
# advisory that names nobody is worse than one that names the emergency line.
NATIONAL_POLICE = {"name": "Israel Police", "phone": "100"}
NATIONAL_FIRE = {"name": "Fire and Rescue", "phone": "102"}

HAZARD_LABEL = {
    "fire": "fire",
    "flood": "flooding",
    "earthquake": "earthquake",
    "air_quality": "air quality",
    "air_pollution": "air quality",
}


@dataclass
class UncorroboratedAdvisory:
    """A verification advisory, with the contacts it names."""

    status: str
    hazard: str
    summary: str
    actions: list[dict[str, Any]] = field(default_factory=list)
    contacts: dict[str, Any] = field(default_factory=dict)
    claim: str | None = None
    location_text: str | None = None
    limitations: list[str] = field(default_factory=list)
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """The advisory as plain data."""
        return {
            "status": self.status,
            "hazard": self.hazard,
            "summary": self.summary,
            "actions": self.actions,
            "contacts": self.contacts,
            "claim": self.claim,
            "location_text": self.location_text,
            "limitations": self.limitations,
            "reason": self.reason,
        }


# Said on every advisory, because the single most damaging way to misread this
# card is as confirmation that something is happening.
STANDING_LIMITATIONS = (
    "This is an unverified report from a public channel. No instrument reading "
    "and no independent report supports it.",
    "No severity, spread, exposure or population assessment has been performed, "
    "and none should be inferred from this card.",
    "No responder has been dispatched and no resource has been reserved.",
)

# The same card, for an incident whose hazard analyser did run. Every hazard
# with an analyser is now analysed whether or not it is confirmed, so the middle
# limitation above would be false — and claiming no assessment exists while one
# is displayed beside it is the worse error. What needs saying instead is what
# the assessment rests on: a place somebody named, not a fire anybody measured.
#
# The first line also drops "and no independent report", because an incident can
# now carry two corroborating reports and still be unconfirmed: corroboration
# raises what evidence is worth, only a measurement or a person confirms it.
ANALYSED_LIMITATIONS = (
    "This is an unverified report from a public channel. No instrument reading "
    "supports it.",
    "The severity, spread and exposure on this card were computed from the "
    "reported location, not from a measured fire. They describe what would be "
    "true if the report is.",
    "No responder has been dispatched and no resource has been reserved.",
)


def newest_claim(incident: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """The most recent report's wording and place name, for the operator to read.

    The newest rather than the first, because a later message about the same
    place is usually the more specific one.

    Lives here rather than on a handler because two handlers now need it: the
    advisory handler for hazards with no analyser, and each hazard handler that
    builds a verification plan for an unconfirmed incident.
    """
    claim: str | None = None
    location_text: str | None = None
    newest: Any = None

    for signal in incident.get("signals") or ():
        if not isinstance(signal, Mapping):
            continue
        report = (signal.get("evidence") or {}).get("text_report")
        if not isinstance(report, Mapping):
            continue
        observed_at = signal.get("observed_at")
        if newest is None or (observed_at is not None and observed_at >= newest):
            newest = observed_at
            claim = report.get("claim") or claim
            location_text = report.get("location_text") or location_text

    return claim, location_text


class UncorroboratedReportPlanner:
    """Turn an unconfirmed claim into "who to phone", and nothing more."""

    def __init__(self, *, parties_lookup: Callable[..., Mapping[str, Any]] | None = None):
        """Build the planner. The lookup of who is responsible is injectable for testing."""
        self._lookup = parties_lookup

    def _parties(self, latitude: float, longitude: float) -> Mapping[str, Any]:
        """Who answers for this place: the police station and the local authority."""
        lookup = self._lookup
        if lookup is None:
            from ecoguard.database.repositories.responsible_services import (
                responsible_parties_at,
            )

            lookup = responsible_parties_at
        return lookup(latitude=latitude, longitude=longitude)

    @live_actor("planner.uncorroborated")
    def plan(
        self,
        *,
        hazard: str,
        latitude: float | None,
        longitude: float | None,
        claim: str | None = None,
        location_text: str | None = None,
        analysis_performed: bool = False,
    ) -> UncorroboratedAdvisory:
        """Build the advisory for one unconfirmed report.

        Args:
            analysis_performed: whether a hazard analyser ran for this incident.
                Only changes which limitations are stated — the actions and
                contacts are the same, because who to telephone does not depend
                on whether a spread model was available.
        """
        label = HAZARD_LABEL.get(hazard, hazard)
        place = location_text or "the reported location"
        limitations = list(
            ANALYSED_LIMITATIONS if analysis_performed else STANDING_LIMITATIONS
        )

        if latitude is None or longitude is None:
            return UncorroboratedAdvisory(
                status="skipped",
                hazard=hazard,
                summary=(
                    f"Unverified {label} report with no resolvable location; "
                    "no responsible contacts can be named."
                ),
                claim=claim,
                location_text=location_text,
                limitations=limitations,
                reason="no_resolvable_location",
            )

        try:
            parties = self._parties(latitude, longitude)
        except Exception:
            # The advisory still has to say something useful, so it falls back
            # to the national numbers rather than failing the incident.
            logger.exception("responsible-party lookup failed for %s, %s", latitude, longitude)
            parties = {}

        police = dict(parties.get("police_station") or {})
        authority = dict(parties.get("authority") or {})

        contacts = {
            "police_station": police or None,
            "local_authority": authority or None,
            "national_police": NATIONAL_POLICE,
        }
        if hazard == "fire":
            contacts["national_fire"] = NATIONAL_FIRE
            contacts["nearest_fire_station"] = parties.get("nearest_fire_station")

        actions = [
            self._police_action(police, label, place),
            self._authority_action(authority, label, place),
        ]
        if hazard == "fire":
            actions.append({
                "order": 3,
                "action": (
                    f"If the caller confirms an active fire, escalate on 102 "
                    f"(Fire and Rescue) rather than waiting for this system."
                ),
                "contact": NATIONAL_FIRE,
                "timeframe": "immediately on confirmation",
            })

        return UncorroboratedAdvisory(
            status="success",
            hazard=hazard,
            summary=(
                f"Unverified {label} report at {place}. Nothing corroborates it "
                "yet — verify by telephone before treating it as an event."
            ),
            actions=actions,
            contacts=contacts,
            claim=claim,
            location_text=location_text,
            limitations=limitations,
        )

    @staticmethod
    def _police_action(police: Mapping[str, Any], label: str, place: str) -> dict[str, Any]:
        """The advice to contact the responsible police station, with its number."""
        if not police:
            return {
                "order": 1,
                "action": (
                    f"No police station is on file for {place}. Call the national "
                    "police line on 100 to verify the report."
                ),
                "contact": NATIONAL_POLICE,
                "timeframe": "now",
            }
        # `basis` distinguishes "this town's station" from "the closest one we
        # could find", and an operator ringing the wrong station wastes the one
        # thing an unverified report is short of, which is time.
        responsible = police.get("basis") == "responsible"
        described = (
            f"the police station responsible for {place}"
            if responsible
            else f"the nearest police station to {place}"
        )
        phone = police.get("phone")
        reach = f" on {phone}" if phone else " (no number on file — use 100)"
        return {
            "order": 1,
            "action": (
                f"Call {police.get('name') or 'the police station'}, {described}"
                f"{reach}, and ask whether a {label} incident is known there."
            ),
            "contact": {
                "name": police.get("name"),
                "phone": phone or NATIONAL_POLICE["phone"],
                "address": police.get("address"),
                "basis": police.get("basis"),
            },
            "timeframe": "now",
        }

    @staticmethod
    def _authority_action(
        authority: Mapping[str, Any], label: str, place: str
    ) -> dict[str, Any]:
        """The advice to contact the local authority."""
        if not authority:
            return {
                "order": 2,
                "action": (
                    f"No local authority is on file for {place}; the point may "
                    "fall outside a municipal boundary. Verify with the police "
                    "contact above."
                ),
                "contact": None,
                "timeframe": "after the police call",
            }
        phone = authority.get("phone")
        reach = f" on {phone}" if phone else " (no number on file)"
        return {
            "order": 2,
            "action": (
                f"Call {authority.get('name') or 'the local authority'}"
                f"{reach} to confirm whether they have a {label} report and "
                "whether local services are already responding."
            ),
            "contact": {
                "name": authority.get("name"),
                "phone": phone,
                "type": authority.get("type"),
                "address": authority.get("address"),
                "website": authority.get("website"),
            },
            "timeframe": "after the police call",
        }


__all__ = [
    "AGENT_NAME",
    "STANDING_LIMITATIONS",
    "UncorroboratedAdvisory",
    "UncorroboratedReportPlanner",
]
