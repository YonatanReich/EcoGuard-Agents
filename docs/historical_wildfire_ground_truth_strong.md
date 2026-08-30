# Tiered historical wildfire ground truth

## Why this stage exists

The existing positive label joins a FIRMS candidate to an official Fire and Rescue wildfire aggregate in the same settlement and month. It is useful supporting evidence, but it does not identify an individual incident. This builder preserves those records as `weak_monthly_support` and provides a strict path for independently sourced event-level evidence.

It does not scrape publication archives, geocode vague place names, train a model, or alter the current ML dataset.

## Confidence tiers

- `strong_event_support` (ordinal score 0.95): an authoritative independent source explicitly identifies an open-area/wildfire event, supplies minute/hour precision, and supplies usable point/coordinate precision. FIRMS support is recorded but is not mandatory.
- `multi_source_probable_fire` (0.80): an authoritative independent open-area event has coordinates and date-or-better timing and matches FIRMS within the configured tolerances, but its time or location precision is weaker.
- `weak_monthly_support` (0.60): the existing FIRMS candidate has same-settlement/month Fire and Rescue aggregate support. This is not individual-event confirmation.

Scores are deterministic ordinal tier markers, not calibrated probabilities. Records that do not satisfy a tier are rejected and counted; precision is never upgraded or invented.

## Matching

Default matching uses 5 km and 72 hours. Date-only evidence represents the full stated UTC date internally for matching but remains a date string in output. All qualifying matches are counted. Zero matches remain unmatched; multiple matches are marked `ambiguous_multiple`; the nearest deterministic match is retained only as a reference and ambiguity is never hidden.

External events matching an existing Tier C FIRMS candidate replace that Tier C row in this output, preserving the FIRMS candidate identifier and independent-source provenance. The current training dataset is not replaced.

## Source review

The official Fire and Rescue data.gov.il resources are machine-readable but monthly aggregated. Israel Nature and Parks Authority publications and KKL-JNF forest reports can provide independent wildfire evidence, named open areas, and sometimes event dates, but no documented event-level bulk API was found. They require controlled human review of provenance, timestamp wording, and geographic precision before ingestion. Telegram/public emergency messages may support a Tier B record only when authority, archived timestamp, text, and geocoding precision are retained; they are not sufficient alone.

The generated `historical_wildfire_ground_truth_sources.json` records the evaluated sources and access limitations.

## Curated external input

An optional generated/ignored CSV may be supplied at:

`data/generated/historical_wildfire_external_events_2023_2026.csv`

It must preserve at least source name, source URL/identifier, authority level, original event timestamp, declared timestamp precision, location precision, open-area indicator, and any coordinates actually supported by the source/review process. A named area must not be converted to point precision without a documented coordinate source.

## Build

```powershell
.\.ml-venv\Scripts\python.exe -m scripts.build_strong_historical_wildfire_ground_truth
```

The output is `data/generated/historical_wildfire_ground_truth_strong_2023_2026.csv`. It initially contains current Tier C rows unless a reviewed external-event CSV is supplied.

## Controlled curation checklist

Before adding a row, a human reviewer must open the authoritative source, preserve its URL and raw title, verify explicit wildfire/open-area evidence, and extract the event date/time from the report text. Publication date is not treated as event date unless the text explicitly establishes that relationship. Timestamp and location precision remain honest, and notes identify whether coordinates are a named-area or locality centroid rather than an ignition point.

Use a unique URL fragment only when one official report explicitly describes several separately named fire locations. Reject duplicates, annual summaries without an event date, places merely described as at risk, unsupported coordinates, and records that fail the existing Tier A/B rules. After review, run the builder above; its existing 5 km/72 hour FIRMS matcher determines whether date/area records qualify for Tier B.

The controlled initial pilot stopped at eight accepted Tier B events. It did not loosen tier or matcher rules merely to reach a numerical target.

## Negative-label implications

Current negatives only establish that no FIRMS candidate was observed inside the configured spatial/temporal exclusion window. Future hard negatives should match positive region, season, hour, weather, land cover, and terrain while excluding all prior-known FIRMS and independently sourced events. Monthly official activity must remain contextual rather than a precise negative criterion.
