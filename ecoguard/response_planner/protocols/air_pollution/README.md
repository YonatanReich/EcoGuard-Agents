# Air-pollution guidance corpus v1.1

Israeli primary sources support particulate-pollution public-health advice and
official monitoring/public-information responsibilities for PM2.5 and PM10.
US EPA AirNow documents add pollutant-specific public-health advice for ambient
O3, NO2, SO2 and CO, strictly as United States guidance and only when an
authorized source explicitly supplies the matching US AQI category. EcoGuard
does not translate Israeli AQI, anomaly severity or raw concentrations into a
US AQI category.

WHO health guidelines, Israeli clean-air reference material, US EPA NAAQS and
South Coast AQMD Rule 701 are retained as clearly labelled reference material.
They authorize no planner action in this corpus. WHO values are health-based
guidelines rather than Israeli legal thresholds; NAAQS are US regulations; Rule
701 is a district-specific international operational reference.

The documents are concise English editorial summaries. Hebrew-source summaries
are not official translations. No source document, image or substantial
verbatim passage is redistributed. Sources were reviewed on 2026-09-08;
publication/update dates are recorded when available. Review does not establish
that a historical advisory remains active, so its recommendation stays
conditional on a current applicable authority advisory.

The manifest records attribution, jurisdiction, scope, publication date, review
date and SHA-256 of UTF-8 document text with LF-normalized line endings. Its
`reviewed_actions` are constrained editorial recommendations, not new official
rules. Timeframe and priority remain `not_specified` when the source gives none.
The pollution planner validates action text, type and timing against this list
and requires the complete action passage to be quoted from a retrieved chunk.
This supplements the shared citation verifier without changing fire behavior.

The AirNow actions are conditional on an explicitly reported US EPA AQI category.
They are not silently activated by an Israeli AQI category. Ambient CO coverage
does not include indoor CO poisoning. An EA-309 high/critical severity or
statistical anomaly never supplies an official advisory condition automatically.
Nearby facilities do not establish exposure.

Unsupported: NO/NOx, H2S, benzene and other unlisted pollutants; mixed-pollutant
plans without one document supporting the complete pollutant set; indoor CO
poisoning; industrial-release procedures; evacuation; road closure; industrial
shutdown; emergency routing; facility selection; dispatch; source attribution;
exposure confirmation; and automatic numeric threshold/AQI conversion.
Unsupported scopes fail closed. No recommendation is sent externally.

Adding coverage requires reviewing applicable primary guidance, adding scoped
documents and reviewed actions, updating hashes, and running corpus/planner
tests. A URL, hazard name or valid quote alone is not action authorization.
