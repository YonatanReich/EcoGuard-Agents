"""National-event escalation: decided in code, citing the clause.

§2.1 of 201.02.003 is nine numbered thresholds. Making a model re-derive them
is slower, costlier and free to answer differently on a second run — for a
question that has exactly one answer. These are the checks that the code
version says what the procedure says.
"""

from ecoguard.planners.fire import escalation


def _analysis(**overrides):
    return {
        "risk_semantics": "fire_spread_forecast",
        "status": "ok",
        "exposure": [],
        "infrastructure_at_risk": [],
        **overrides,
    }


def test_a_fire_inside_a_settlement_triggers_2_1_6():
    result = escalation.assess(_analysis(exposure=[
        {"name": "Beit Oren", "exposure": "burning", "population": 526},
    ]))
    assert result["is_national"] is True
    assert [item["clause"] for item in result["triggered"]] == ["2.1.6"]
    assert "Beit Oren" in result["triggered"][0]["evidence"]


def test_a_fire_forecast_to_reach_a_settlement_also_triggers_2_1_6():
    """Danger to a settlement, not damage to one. The clause says סכנה."""
    result = escalation.assess(_analysis(exposure=[
        {"name": "Yokneam", "exposure": "likely", "population": 24000},
    ]))
    assert result["is_national"] is True
    assert result["triggered"][0]["clause"] == "2.1.6"


def test_a_settlement_only_a_wind_shift_could_reach_does_not_trigger():
    """`possible` is a contingency, not a danger. Treating it as one would make
    every fire in the country a national event."""
    result = escalation.assess(_analysis(exposure=[
        {"name": "Haifa", "exposure": "possible", "population": 289507},
    ]))
    assert result["is_national"] is False


def test_a_hospital_in_the_forecast_path_triggers_2_1_2():
    result = escalation.assess(_analysis(infrastructure_at_risk=[
        {"name": "Rambam", "kind": "hospital", "category": "life_safety",
         "exposure": "likely"},
    ]))
    assert "2.1.2" in [item["clause"] for item in result["triggered"]]


def test_an_industrial_site_does_not_trigger_the_population_clause():
    """2.1.2 is about occupants who cannot leave, not about property."""
    result = escalation.assess(_analysis(infrastructure_at_risk=[
        {"name": "Estate", "kind": "industrial area", "category": "economic",
         "exposure": "likely"},
    ]))
    assert result["is_national"] is False


def test_both_clauses_can_trigger_together():
    result = escalation.assess(_analysis(
        exposure=[{"name": "Town", "exposure": "burning", "population": 5000}],
        infrastructure_at_risk=[
            {"name": "School", "kind": "school", "category": "life_safety",
             "exposure": "likely"},
        ],
    ))
    assert {item["clause"] for item in result["triggered"]} == {"2.1.6", "2.1.2"}


def test_the_five_unevaluable_clauses_are_named_not_silently_dropped():
    """A verdict of "not national" that hides five unchecked criteria is worse
    than one that says which it could not see, because the first stops somebody
    looking."""
    result = escalation.assess(_analysis())
    clauses = {item["clause"] for item in result["unevaluable"]}
    assert clauses == {"2.1.1", "2.1.3", "2.1.4", "2.1.5", "2.1.7", "2.1.8", "2.1.9"}
    assert "cannot be assessed" in result["statement"]


def test_every_verdict_cites_the_procedure():
    for analysis in (
        _analysis(),
        _analysis(exposure=[{"name": "X", "exposure": "burning", "population": 1}]),
    ):
        result = escalation.assess(analysis)
        assert result["source"] == "הוראה 201 / 201.02.003 §2.1"
        assert result["source"] in result["statement"] or \
               result["source_title"] in result["statement"]


def test_the_nine_criteria_match_the_published_clause_numbering():
    """A renumbering here would silently cite the wrong rule."""
    assert [item["clause"] for item in escalation.CRITERIA] == [
        f"2.1.{n}" for n in range(1, 10)
    ]
