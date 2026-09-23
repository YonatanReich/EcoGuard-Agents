import pytest

from ecoguard.detectors.flood.telegram_candidate_filter import detect_flood_candidate


@pytest.mark.parametrize(
    "text",
    (
        "הצפה חמורה ברחוב הרצל בחיפה",
        "בשל הצפות, נחסם כביש 90 לתנועה",
        "כביש 90 נחסם בעקבות שיטפון",
        "זרימות חזקות והצפות באזור",
        "כבישים מוצפים באזור השרון",
        "מים על הכביש והכביש נחסם לתנועה",
        "צוותים פועלים לחילוץ מהמים",
        "רכב נלכד במים ונוסעיו חולצו",
        "רכב נסחף במים בנחל",
    ),
)
def test_specific_flood_reports_are_candidates(text):
    result = detect_flood_candidate(text)
    assert result["is_flood_candidate"] is True
    assert result["confidence"] >= 0.70


@pytest.mark.parametrize(
    "text",
    (
        "חשש לשיטפונות בנחלי הדרום",
        "צפי לשיטפונות מחר",
        "סיכוי לשיטפונות במדבר יהודה",
        "גשם חזק עלול לגרום לשיטפונות",
        "צפויים שיטפונות במזרח",
        "חשש להתפתחות שיטפונות בשעות הלילה",
    ),
)
def test_forecast_only_warning_is_not_an_occurrence_candidate(text):
    result = detect_flood_candidate(text)
    assert result["is_flood_candidate"] is False
    assert result["confidence"] < 0.70


def test_generic_flood_safety_boilerplate_does_not_turn_weather_closure_into_occurrence():
    text = (
        "כביש 40 נחסם בשל מזג האוויר. "
        "להימנע מהגעה לאזורי שיטפונות, נחלים, כבישים מוצפים"
    )

    assert detect_flood_candidate(text)["is_flood_candidate"] is False


@pytest.mark.parametrize(
    "text",
    (
        "גשם צפוי בצפון",
        "מזג אוויר חורפי",
        "כביש עמוס לתנועה",
        "אין חשש להצפות",
        "הכביש נפתח לתנועה לאחר שהמים ירדו",
        "האירוע הסתיים והכביש נפתח לתנועה",
    ),
)
def test_broad_or_resolved_language_is_not_a_candidate(text):
    result = detect_flood_candidate(text)
    assert result["is_flood_candidate"] is False


def test_rain_alone_never_supports_flood():
    result = detect_flood_candidate("גשם כבד מאוד יורד באזור חיפה")
    assert result["confidence"] == 0.0
