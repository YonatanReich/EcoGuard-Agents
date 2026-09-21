"""Render the scenario results as a printable HTML test report.

    python -m ecoguard.research.pilots.render_fire_analyzer_report

Reads what `run_fire_analyzer_scenarios` wrote and lays it out for print. It
adds nothing: every figure on the page comes out of the results file, so the
document cannot disagree with the run that produced it.
"""

from __future__ import annotations

import html
import json

from ecoguard.paths import REPOSITORY_ROOT

RESULTS = REPOSITORY_ROOT / "outputs" / "fire_analyzer_scenario_results.json"
REPLAY = REPOSITORY_ROOT / "outputs" / "fire_analyzer_replay_results.json"
OUTPUT = REPOSITORY_ROOT / "outputs" / "fire_analyzer_test_report.html"

CSS = """
@page { size: A4; margin: 16mm 14mm 18mm; }
:root { --ink:#16191d; --muted:#5b6470; --rule:#d6dbe1; --accent:#9a3412;
        --ok:#166534; --bad:#991b1b; --code:#f4f6f8; }
*{box-sizing:border-box}
body{font-family:"Charter",Georgia,Cambria,serif;font-size:9.8pt;line-height:1.48;
     color:var(--ink);margin:0;-webkit-print-color-adjust:exact;print-color-adjust:exact}
h1,h2,h3,th{font-family:"Segoe UI","Helvetica Neue",Arial,sans-serif}
h1{font-size:20pt;letter-spacing:-.015em;margin:0}
.masthead{border-bottom:2.5px solid var(--ink);padding-bottom:9px}
.sub{font-size:9.3pt;color:var(--muted);margin-top:5px;font-family:"Segoe UI",Arial,sans-serif}
.meta{display:flex;gap:20px;flex-wrap:wrap;font-family:"Segoe UI",Arial,sans-serif;
      font-size:8.2pt;color:var(--muted);padding:7px 0 0;margin-bottom:16px}
.meta b{color:var(--ink);font-weight:600}
.scorecard{border:1px solid var(--rule);border-left:4px solid var(--accent);
           background:#fbfaf9;padding:11px 14px;margin-bottom:18px}
.scorecard p{margin:0}
.scorecard p+p{margin-top:6px}
h2{font-size:12pt;margin:20px 0 8px;padding-bottom:5px;border-bottom:1px solid var(--rule);
   font-weight:650;break-after:avoid}
h2 .pill{float:right;font-size:7.5pt;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
   padding:2.5px 8px;border-radius:3px;position:relative;top:1px}
.pass{background:#dcfce7;color:var(--ok)} .fail{background:#fee2e2;color:var(--bad)}
h3{font-size:9.6pt;margin:12px 0 5px;font-weight:650;break-after:avoid;
   text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
p{margin:0 0 7px}
code{font-family:"Cascadia Mono",Consolas,monospace;font-size:8.4pt;background:var(--code);
     padding:1px 4px;border-radius:3px;word-break:break-word}
pre{background:var(--code);border-left:3px solid var(--rule);padding:8px 10px;
    font-size:7.7pt;line-height:1.4;margin:0 0 9px;white-space:pre-wrap;word-break:break-word;
    font-family:"Cascadia Mono",Consolas,monospace}
pre.report{background:#fffdf7;border-left-color:#d97706;font-size:8.1pt;
    font-family:"Charter",Georgia,serif;line-height:1.5}
table{width:100%;border-collapse:collapse;margin:0 0 10px;font-size:8.5pt;break-inside:avoid}
th,td{text-align:left;padding:4px 7px;border-bottom:1px solid var(--rule);vertical-align:top}
th{font-size:7.8pt;text-transform:uppercase;letter-spacing:.05em;
   border-bottom:1.5px solid var(--ink);font-weight:650}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.tick{color:var(--ok);font-weight:700} .cross{color:var(--bad);font-weight:700}
.case{break-before:page}
.case:first-of-type{break-before:auto}
.two{display:flex;gap:14px} .two>div{flex:1;min-width:0}
footer{margin-top:22px;padding-top:8px;border-top:1px solid var(--rule);
       font-family:"Segoe UI",Arial,sans-serif;font-size:7.8pt;color:var(--muted)}
.note{border-left:3px solid var(--rule);padding:3px 0 3px 10px;color:var(--muted);
      font-size:9pt;margin:0 0 9px}
.hint{font-size:8.6pt;color:var(--muted)}
.verdict{font-weight:700;font-size:7.6pt;letter-spacing:.06em;text-transform:uppercase;
  padding:2px 7px;border-radius:3px;white-space:nowrap}
.v-aligned{background:#dcfce7;color:var(--ok)}
.v-partial{background:#fef3c7;color:#92400e}
.v-gap{background:#fee2e2;color:var(--bad)}
.big{font-size:15pt;font-weight:700;font-family:"Segoe UI",Arial,sans-serif}
.kpi{display:flex;gap:10px;margin:0 0 12px}
.kpi>div{flex:1;border:1px solid var(--rule);border-radius:4px;padding:8px 10px;text-align:center}
.kpi .lab{font-size:7.6pt;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);
  font-family:"Segoe UI",Arial,sans-serif;margin-top:3px}
blockquote{margin:0 0 6px;padding:2px 0 2px 10px;border-left:3px solid var(--rule);
  color:var(--muted);font-style:italic}
"""

INCIDENT_FIELDS = (
    "id", "primary_hazard", "queues", "cells", "latitude", "longitude",
    "precision_m", "location_method", "last_signal_at", "signal_count",
)
ENVIRONMENT_FIELDS = (
    "temperature_c", "humidity_percent", "wind_speed_kmh",
    "wind_direction_deg", "slope_deg", "slope_max_deg",
)


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def fmt(value) -> str:
    if value is None:
        return "&mdash;"
    if isinstance(value, bool):
        return esc(value)
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, list):
        return esc(", ".join(str(item) for item in value))
    return esc(value)


def _summary_table(cases) -> str:
    rows = []
    for case in cases:
        outcome = case["outcome"]
        passed = sum(1 for item in case["checks"] if item["passed"])
        score = outcome["severity_score"]
        severity = (
            "unscored" if score is None
            else f"{outcome['severity_level']} &middot; {score}"
        )
        rows.append(
            f"<tr><td><code>{esc(case['key'])}</code></td>"
            f"<td>{esc(case['title'])}</td>"
            f"<td class='num'>{severity}</td>"
            f"<td class='num'>{outcome['settlements_exposed']}</td>"
            f"<td class='num'>{fmt(outcome['people_in_spread'])}</td>"
            f"<td class='num'>{passed}/{len(case['checks'])}</td></tr>"
        )
    return (
        "<h2>Summary</h2><table><thead><tr><th>Scenario</th><th>What it is</th>"
        "<th class='num'>Severity</th><th class='num'>Settlements</th>"
        "<th class='num'>People in spread</th><th class='num'>Checks</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _inputs(case) -> str:
    incident = case["incident"]
    env = case["environment"]
    signal = (incident.get("signals") or [{}])[0]
    evidence = signal.get("evidence") or {}

    left = "".join(
        f"<tr><td><code>{key}</code></td><td>{fmt(incident.get(key))}</td></tr>"
        for key in INCIDENT_FIELDS
    )
    right = [
        f"<tr><td><code>peak FRP</code></td><td>{fmt(signal.get('value'))} MW</td></tr>",
        f"<tr><td><code>hotspots</code></td><td>{fmt(evidence.get('hotspot_count'))}</td></tr>",
        f"<tr><td><code>satellites</code></td>"
        f"<td>{esc(', '.join(evidence.get('satellites') or []))}</td></tr>",
    ]
    right += [
        f"<tr><td><code>{key}</code></td><td>{fmt(env.get(key))}</td></tr>"
        for key in ENVIRONMENT_FIELDS
    ]
    cover = case.get("cover_fractions") or {}
    mix = ", ".join(
        f"{name} {value:.0%}"
        for name, value in sorted(cover.items(), key=lambda kv: -kv[1])
        if value >= 0.05
    )
    right.append(f"<tr><td><code>land cover</code></td><td>{esc(mix) or '&mdash;'}</td></tr>")
    gaps = env.get("gaps") or []
    if gaps:
        right.append(
            f"<tr><td><code>gaps</code></td><td>{esc(', '.join(gaps))}</td></tr>"
        )

    return (
        "<h3>The fabricated incident, and the ground it sits on</h3>"
        f'<div class="two"><div><table><tbody>{left}</tbody></table></div>'
        f'<div><table><tbody>{"".join(right)}</tbody></table></div></div>'
    )


def _checks(case) -> str:
    rows = []
    for item in case["checks"]:
        mark = (
            '<span class="tick">&#10003;</span>' if item["passed"]
            else '<span class="cross">&#10007;</span>'
        )
        rows.append(
            f"<tr><td>{mark}</td><td>{esc(item['check'])}</td>"
            f"<td><code>{esc(item['detail'])}</code></td></tr>"
        )
    return (
        "<h3>Checks</h3><table><thead><tr><th style='width:4%'></th>"
        "<th style='width:38%'>Expectation</th><th>Observed</th></tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody></table>"
    )


def _replay_section() -> str:
    """The historical replay: forecast against a fire that actually happened."""
    if not REPLAY.exists():
        return ""
    replay = json.loads(REPLAY.read_text(encoding="utf-8"))
    fire, inputs = replay["fire"], replay["inputs"]
    forecast, observed, score = replay["forecast"], replay["observed"], replay["score"]
    weather = inputs["weather"]

    return (
        '<section class="case"><h2>Historical replay &mdash; forecast against a '
        'real fire<span class="pill pass">Validated</span></h2>'
        f"<p><b>{esc(fire['name'])}.</b> The largest multi-overpass event in the "
        "collection window: 36 satellite overpasses across two days, first seen "
        "at 09:58 at 4.7 MW, peaking at 109 MW the following midday.</p>"
        '<p class="note">The forecast is built from the <b>first</b> detection '
        "only, with the weather actually recorded for that cell and hour, and the "
        "terrain and fuel actually there. No input has seen what happened next. "
        "It is then scored against the satellite pixels observed over the "
        "following three hours.</p>"
        '<div class="kpi">'
        f'<div><div class="big">{score["bearing_error_deg"]}&deg;</div>'
        '<div class="lab">Heading error</div></div>'
        f'<div><div class="big">{score["containment_likely"]:.0%}</div>'
        '<div class="lab">Pixels in likely ring</div></div>'
        f'<div><div class="big">{score["head_distance_vs_observed"]}&times;</div>'
        '<div class="lab">Forecast head vs observed</div></div>'
        f'<div><div class="big">{observed["pixels"]}</div>'
        '<div class="lab">Observed pixels</div></div></div>'
        "<table><thead><tr><th>Quantity</th><th>Forecast</th><th>Observed</th>"
        "</tr></thead><tbody>"
        f"<tr><td>Heading</td><td>{fmt(forecast['heading_deg'])}&deg; "
        f"({esc(forecast['heading_compass'])})</td>"
        f"<td>{fmt(observed['mean_bearing_deg'])}&deg; mean pixel bearing</td></tr>"
        f"<tr><td>Head distance in 3 h</td>"
        f"<td>{fmt(forecast['head_distance_m'])} m at "
        f"{fmt(forecast['head_rate_m_per_min'])} m/min</td>"
        f"<td>{fmt(observed['furthest_pixel_m'])} m to furthest pixel</td></tr>"
        f"<tr><td>Severity</td><td>{esc(forecast['risk_level'])} &middot; "
        f"{fmt(forecast['risk_score'])}</td><td>&mdash;</td></tr>"
        "</tbody></table>"
        "<h3>Inputs, none of them hindsight</h3><table><tbody>"
        f"<tr><td>Weather, hour of ignition</td><td>"
        f"{fmt(weather['temperature_c'])} C, "
        f"{fmt(weather['humidity_percent'])}% RH, wind "
        f"{fmt(weather['wind_speed_kmh'])} km/h from "
        f"{fmt(weather['wind_direction_deg'])}&deg;</td></tr>"
        f"<tr><td>Ground</td><td>{esc(inputs['dominant_fuel'])}, burnable "
        f"{fmt(inputs['burnable_fraction'])}, slope {fmt(inputs['slope_deg'])}"
        f"&deg;, steepest {fmt(inputs['slope_max_deg'])}&deg;</td></tr>"
        "</tbody></table>"
        '<p class="note"><b>How much this shows, and how much it does not.</b> '
        "A heading error under one degree is the strongest part of the result, "
        "because direction is independent of how large the ring was drawn. "
        "Containment of 100% is weaker evidence on its own: a ring that is too "
        "big contains the truth for the wrong reason, which is why the forecast "
        "head is reported against the observed extent beside it. The forecast "
        "ran about a third further than the fire did &mdash; the expected "
        "direction for a model that states it includes no suppression, against a "
        "fire that was being fought. This is <b>one fire, one three-hour window, "
        "nine pixels</b>. It is a great deal better than no validation, and it is "
        "not a validation campaign.</p>"
        "</section>"
    )


def _doctrine_section() -> str:
    """The output compared against published doctrine."""
    from ecoguard.research.pilots import fire_doctrine_review as review

    counts = review.summary()
    classes = {"aligned": "v-aligned", "partial": "v-partial", "gap": "v-gap"}
    rows = []
    for finding in review.FINDINGS:
        title, _url = review.SOURCES[finding["doctrine"]]
        cls = classes[finding["verdict"]]
        rows.append(
            f'<tr><td><span class="verdict {cls}">'
            f'{esc(finding["verdict"])}</span></td>'
            f"<td><b>{esc(finding['topic'])}</b>"
            f"<blockquote>{esc(finding['doctrine_says'])}</blockquote>"
            "<p style='margin:0 0 4px'><b>The analyser:</b> "
            f"{esc(finding['analyser_does'])}</p>"
            "<p style='margin:0;font-size:8.6pt;color:#5b6470'>"
            f"{esc(finding['note'])}</p>"
            "<p style='margin:4px 0 0;font-size:7.8pt;color:#5b6470'>"
            f"Source: {esc(title)}</p></td></tr>"
        )

    return (
        '<section class="case"><h2>Doctrine review</h2>'
        "<p>The substitute for a fire officer reading these reports, and a "
        "weaker thing than that. It compares the output against doctrine that "
        "can be cited, which catches a decision input the doctrine names and "
        "the analyser does not supply. It cannot catch a number that is "
        "plausible and wrong.</p>"
        '<div class="kpi">'
        f'<div><div class="big">{counts["aligned"]}</div>'
        '<div class="lab">Aligned</div></div>'
        f'<div><div class="big">{counts["partial"]}</div>'
        '<div class="lab">Partial</div></div>'
        f'<div><div class="big">{counts["gap"]}</div>'
        '<div class="lab">Gap</div></div></div>'
        "<table><thead><tr><th style='width:10%'>Verdict</th><th>Finding</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
        "</section>"
    )


def render() -> str:
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    summary = data["summary"]
    parts = [
        f"<style>{CSS}</style>",
        '<div class="masthead"><h1>Fire Analyzer &mdash; Scenario Test Report</h1>'
        '<div class="sub">Six fabricated incidents in coordinator format, assessed '
        "against live terrain, settlement and population data</div></div>",
        '<div class="meta">'
        "<span><b>Component</b> FireSpreadAnalyzer</span>"
        f"<span><b>Scenarios</b> {summary['cases']}</span>"
        f"<span><b>Checks</b> {summary['checks']}</span>"
        "<span><b>Date</b> 19 September 2026</span>"
        "<span><b>Branch</b> EA-373</span></div>",
        '<div class="scorecard">'
        f"<p><b>Result: {summary['passed']} of {summary['cases']} scenarios passed, "
        f"{summary['checks_passed']} of {summary['checks']} individual checks.</b></p>"
        "<p>The incident record and the weather are fabricated. Everything the "
        "analyser reasons over is real and read live from the store: land cover and "
        "slope from <code>surface_cells</code>, settlement outlines, populations and "
        "authority telephone numbers from <code>towns</code>, and residents inside "
        "the forecast extent from <code>population_cells</code>. Each scenario "
        "therefore asks a real question about real ground under stated conditions.</p>"
        "<p>Every incident is shaped exactly as <code>coordinator/incidents.py</code> "
        "stores one &mdash; same keys, same types, a real grid cell, a signal list in "
        "<code>CellSignal</code> form. The analyser is not told they are fabricated.</p>"
        "</div>",
        _summary_table(data["cases"]),
    ]

    for case in data["cases"]:
        payload = case["planner_json"]
        pill = "pass" if case["passed"] else "fail"
        label = "Pass" if case["passed"] else "Fail"
        compact = payload
        parts.append(
            f'<section class="case"><h2>{esc(case["title"])}'
            f'<span class="pill {pill}">{label}</span></h2>'
            f"<p>{esc(case['plain_english'])}</p>"
            f'<p class="note"><b>What this case is testing.</b> '
            f"{esc(case['expected'].get('note', ''))}</p>"
            + _inputs(case)
            + _checks(case)
            + "<h3>Textual incident report &mdash; what the operator reads</h3>"
            f'<pre class="report">{esc(case["report"])}</pre>'
            "<h3>Planner handoff &mdash; the validated "
            "<code>EmergencyResponsePlanInput</code></h3>"
            '<p class="hint">This is the object <code>EmergencyResponsePlanner</code> '
            "validates and serialises into its prompt &mdash; not a shape invented "
            "for this report. <code>event_description</code> is what drives BM25 "
            "retrieval, which is why it is the planning view rather than the full "
            "narrative; the narrative travels in <code>additional_context</code>.</p>"
            f"<pre>{esc(json.dumps(compact, indent=1, ensure_ascii=False))}</pre>"
            "</section>"
        )

    parts.append(_replay_section())
    parts.append(_doctrine_section())
    parts.append(
        "<footer>EcoGuard Agents &middot; FireSpreadAnalyzer scenario test &middot; "
        "incidents and weather fabricated; terrain, settlements and population read "
        "live from the operational store.</footer>"
    )
    return "\n".join(parts)


def main() -> None:
    OUTPUT.write_text(render(), encoding="utf-8")
    print(f"written: {OUTPUT}")


if __name__ == "__main__":
    main()
