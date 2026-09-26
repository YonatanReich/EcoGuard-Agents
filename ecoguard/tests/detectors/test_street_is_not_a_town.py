"""A street type that is also a town name must not hijack the location.

שדרות means "boulevard" and is also the town of Sderot. "שדרות התמרים באילת"
is Tamarim Boulevard in Eilat; read word by word the bare שדרות matched Sderot,
250 km away, and matched first because candidates are tried in text order. The
operator was handed Sderot's police station and telephone number for a fire in
Eilat - worse than no answer, because it looks like one.
"""

from ecoguard.detectors.fire.hebrew_location_extractor import locality_name_candidates


def test_a_street_named_after_a_town_does_not_resolve_to_that_town():
    """The case that shipped a wrong phone number."""
    candidates = locality_name_candidates(
        "תנועה נעצרה בשדרות התמרים באילת עקב עשן כבד מדליקה סמוכה"
    )

    assert "שדרות" not in candidates, "the street type must not stand alone as a town"
    assert "אילת" in candidates, "the real town is still offered"
    # And it is now reachable: nothing matching a town precedes it.
    assert candidates.index("אילת") < len(candidates)


def test_the_town_itself_still_resolves():
    """Suppressing the street type must not lose the real Sderot."""
    assert "שדרות" in locality_name_candidates("שריפה גדולה בשדרות")


def test_two_towns_joined_by_and_are_both_kept():
    """"בשדרות ובנתיבות" is two towns, not a street.

    The following word carries the conjunction prefix ו, so it cannot be a
    street name and the bare town stands.
    """
    assert "שדרות" in locality_name_candidates("פיצוץ בשדרות ובנתיבות")
