"""A plain word list, used as a floor under the model.

Runs on every message whether or not the model does: as the fallback when the
model is unavailable, and as a standing check on what the model is missing.
A word match says a word appeared, never that anything is happening."""

from __future__ import annotations

import re
import unicodedata

from ecoguard.detectors.fire.telegram_candidate_filter import detect_fire_candidate
from ecoguard.detectors.flood.telegram_candidate_filter import detect_flood_candidate

FIRE = "fire"
FLOOD = "flood"
EARTHQUAKE = "earthquake"
AIR_QUALITY = "air_quality"

HAZARDS = (FIRE, FLOOD, EARTHQUAKE, AIR_QUALITY)

# Hebrew glues its conjunctions, articles and prepositions onto the front of a
# word: שריפה, השריפה, בשריפה, ושריפה, מהשריפה. A stem list that does not allow
# for them matches the bare noun and misses every sentence that uses it
# naturally. Up to three of ו ה ב כ ל מ ש, preceded by a non-letter so the
# match starts at a word boundary rather than inside another word.
PREFIX = r"(?:^|[^א-ת])[ובכלמשה]{0,3}"

# Stems, not words. Hebrew inflects the ending too — רעידה / רעידת / רעידות —
# so each entry stops before the part that changes.
STEMS: dict[str, tuple[str, ...]] = {
    # Fire and flood have curated filters below, and these stems run as well
    # rather than instead. The curated lists enumerate inflections one at a
    # time — שריפה, השריפה, בשריפה — which means every prefix combination
    # nobody thought of is a miss: ‎והשריפה‎ ("and the fire") was one. A stem
    # plus the generic PREFIX covers the combinations exhaustively, so the two
    # together are broader than either.
    FIRE: (
        r"שרי?פ",
        r"דליק",
        # Not the bare stem ‎להב‎: it is the start of ‎להבין‎, ‎להביא‎ and half
        # the infinitives in the language.
        r"להבות",
        r"להבה",
        r"בוער",
        r"עשן",
        r"מוקד בעירה",
        r"על[התה]? באש",
    ),
    FLOOD: (
        r"הצפ",
        r"שיטפו",
        r"שטפו",
        r"עלה על גדותיו",
        r"זרימ",
    ),
    EARTHQUAKE: (
        r"רעידת אדמה",
        r"רעידות אדמה",
        r"רעש אדמה",
        r"רעיד",
        r"הורגשה רעיד",
        r"מוקד הרעש",
    ),
    AIR_QUALITY: (
        r"זיהום אוויר",
        r"זיהום אויר",
        r"אובך",
        r'חומ"?ס',
        r"חומרים מסוכנים",
        r"ריח חריף",
        r"ריח חזק",
        r"ענן רעיל",
        r"דליפת גז",
        r"איכות האוויר",
    ),
}

# The English outlets on the allowlist carry the same events in a different
# language, and a Hebrew-only net would score them all as negatives — which
# would read as the model over-reporting rather than as the net under-reading.
ENGLISH_STEMS: dict[str, tuple[str, ...]] = {
    FIRE: (r"wildfire", r"\bblaze\b", r"\bfire\b", r"firefighter"),
    FLOOD: (r"flood", r"flash flood", r"inundat"),
    EARTHQUAKE: (r"earthquake", r"\bquake\b", r"seismic", r"tremor"),
    AIR_QUALITY: (r"air pollution", r"\bsmog\b", r"hazardous material", r"gas leak"),
}


def normalise(text: str) -> str:
    """Strip niqqud, unify the quote variants, collapse whitespace.

    Hebrew keyboards and news CMSes disagree about which character a quote is:
    the gershayim inside an acronym like חומ״ס may arrive as ״ or " or ''. All
    three mean the same thing to a reader and are three different strings to a
    regex.
    """
    # Category Mn is the combining marks — niqqud and cantillation both.
    without_points = "".join(
        character for character in unicodedata.normalize("NFD", text)
        if unicodedata.category(character) != "Mn"
    )
    unified = (
        without_points
        .replace("״", '"').replace("“", '"').replace("”", '"')
        .replace("׳", "'").replace("’", "'").replace("''", '"')
    )
    return re.sub(r"\s+", " ", unified).strip()


def _matches(text: str, stems: tuple[str, ...], *, hebrew: bool) -> list[str]:
    """The words that actually matched, not the patterns that matched them.

    These end up in the disagreement report a human reads to decide what to
    add to the list, and `חומ"?ס` is not a word anybody searches for.
    """
    found = []
    for stem in stems:
        pattern = PREFIX + stem if hebrew else stem
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            # The Hebrew prefix group can swallow the preceding space or
            # punctuation; strip it back to the word.
            found.append(match.group().strip(" \t\n.,:;!?-\"'()"))
    return found


def hazards_in(text: str | None) -> dict[str, list[str]]:
    """Every hazard this text mentions, with the terms that matched.

    An empty dict is "no hazard term appears here", which is not the same
    claim as "this is not a hazard report" — that judgement is the model's.
    """
    if not text or not text.strip():
        return {}

    normalised = normalise(text)
    hits: dict[str, list[str]] = {}

    # The curated filters read the original text: they carry their own
    # normalisation and their term lists were built against real messages.
    fire = detect_fire_candidate(text)
    if fire["is_fire_candidate"]:
        hits[FIRE] = list(fire["matched_terms"])
    flood = detect_flood_candidate(text)
    if flood["is_flood_candidate"]:
        hits[FLOOD] = list(flood["matched_terms"])

    for hazard, stems in STEMS.items():
        matched = _matches(normalised, stems, hebrew=True)
        if matched:
            hits.setdefault(hazard, []).extend(matched)

    for hazard, stems in ENGLISH_STEMS.items():
        matched = _matches(normalised, stems, hebrew=False)
        if matched:
            hits.setdefault(hazard, []).extend(matched)

    return {hazard: sorted(set(terms)) for hazard, terms in hits.items()}
