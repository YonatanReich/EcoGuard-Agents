"""Whether an incident is confirmed, and on whose word.

Two things confirm an incident, and only two:

  instrument   something measured it - a FIRMS hotspot, a gauge, a seismometer
  operator     a person checked and said so

Notably absent: a second person saying the same thing. Two newsrooms reporting
one fire raise how much the evidence is worth - that is what `triage` decides,
and it is why a corroborated report carries 0.7 confidence against an
uncorroborated one's 0.3 - but neither of them measured anything, so neither
confirms. Under the old routing that distinction decided whether an incident was
analysed at all. It no longer does: everything is analysed, and confirmation
decides what the *response plan* is allowed to ask for.

Instrument evidence is read from the signals every time rather than stored,
because a stored flag can disagree with the signals it was derived from and the
signals are the record. Operator confirmation has nowhere else to live, so it is
a column - and instrument evidence outranks it, so a later hotspot does not need
the operator's click to be re-examined.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

# The variable every text-derived signal carries. Anything else came from an
# instrument. Defined in `detectors.text.triage` too, and deliberately repeated
# rather than imported: the coordinator must not depend on a detector to decide
# what counts as a measurement.
TEXT_VARIABLE = "report"

INSTRUMENT = "instrument"
OPERATOR = "operator"


@dataclass(frozen=True)
class Confirmation:
    """The confirmation state of one incident, and the reason for it."""

    confirmed: bool
    basis: str | None = None
    detail: str | None = None
    confirmed_at: datetime | None = None
    confirmed_by: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Plain data for the event projection."""
        return {
            "status": "confirmed" if self.confirmed else "unconfirmed",
            "basis": self.basis,
            "detail": self.detail,
            "confirmed_at": self.confirmed_at,
            "confirmed_by": self.confirmed_by,
        }


def instrument_sources(incident: Mapping[str, Any]) -> list[str]:
    """Which measuring sources have signalled on this incident.

    Empty means every signal on it is somebody's say-so. An incident with no
    readable signals also answers empty, which is the fail-closed reading: an
    incident that cannot show evidence has not been confirmed by any.
    """
    sources = {
        str(signal.get("source") or "unknown")
        for signal in incident.get("signals") or ()
        if isinstance(signal, Mapping) and signal.get("variable") != TEXT_VARIABLE
    }
    return sorted(sources)


def confirmation_of(incident: Mapping[str, Any]) -> Confirmation:
    """Confirmed or not, by what, and with the evidence named.

    Instrument first, deliberately. An operator who confirmed a report an hour
    before the satellite saw it should not leave the incident attributed to the
    click - the stronger evidence is the one that arrived, and an incident that
    says "confirmed by operator" when a hotspot is sitting in its signals reads
    as weaker than it is.
    """
    measured = instrument_sources(incident)
    if measured:
        return Confirmation(
            confirmed=True,
            basis=INSTRUMENT,
            detail=", ".join(measured),
            # Carried through even when the instrument is what confirms, so the
            # card can still show that someone checked as well.
            confirmed_at=incident.get("confirmed_at"),
            confirmed_by=incident.get("confirmed_by"),
        )

    confirmed_at = incident.get("confirmed_at")
    if confirmed_at is not None:
        confirmed_by = incident.get("confirmed_by") or "operator"
        return Confirmation(
            confirmed=True,
            basis=OPERATOR,
            detail=f"marked confirmed by {confirmed_by}",
            confirmed_at=confirmed_at,
            confirmed_by=confirmed_by,
        )

    return Confirmation(
        confirmed=False,
        basis=None,
        detail="no instrument evidence and nobody has confirmed it",
    )


__all__ = [
    "Confirmation",
    "INSTRUMENT",
    "OPERATOR",
    "TEXT_VARIABLE",
    "confirmation_of",
    "instrument_sources",
]
