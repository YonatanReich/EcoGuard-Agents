# Response Protocol Corpus

This directory holds the protocol documents that ground the risk analysis, response
planning and judging agents. The language model is only permitted to cite text that was
actually retrieved from these files, and every citation it returns is verified against
the source chunk in Python before it reaches the API response.

## Hazards

The corpus is indexed by hazard, one directory per hazard, each with its own
`manifest.json`:

```
data/protocols/
  README.md          ← this file, covers the whole filebase
  fire/
    manifest.json
    *.md
  flood/             ← when there are documents to put in it
  earthquake/        ← likewise
```

`ProtocolRetriever(hazard="fire")` reads `data/protocols/fire`. One retriever instance
per hazard, constructed where the hazard is already known — the hazards deliberately do
**not** share one index, because a shared index would score fire queries against flood
chunks and degrade BM25's term weighting on a corpus this small.

A hazard directory that does not exist yet is not an error. The retriever reports
`available is False` and returns nothing, and the agents translate that into
`"protocol corpus unavailable"`. So `ProtocolRetriever(hazard="flood")` can be
constructed today and will simply have nothing to say until the corpus is added — it
will never fall back to fire doctrine, which would be worse than answering nothing.

Do not create empty hazard directories in advance.

## Manifests

`manifest.json` is the machine-readable index for one hazard: the hazard name, corpus
version, and per document the id, title, source URL, licence, retrieval date and
SHA-256 hash. The hashes let you confirm a document has not drifted from what was
reviewed.

## Why these three

Each document covers a different part of the reasoning, and together they span both
halves of the sprint requirement — classifying risk and planning a response.

| Document | Role |
| --- | --- |
| `effis-fire-weather-index.md` | Fire danger classification. Defines the FWI bands the pipeline already collects. |
| `nwcg-standard-orders-watchouts.md` | Wildland engagement safety. Governs whether and how responders may engage a fireline. |
| `usfa-structure-triage.md` | Wildland/urban interface. Which structures to defend from an approaching fire, and when not to. |
| `usfa-risk-management-structure-fire.md` | Structural fires. The offensive/defensive decision — whether to send crews *into* a building. |

The first three are wildland-oriented; the fourth covers fires in buildings, so an
apartment or commercial fire has doctrine to ground against rather than falling back on
defensible-space guidance that does not apply to it.

The EFFIS document is deliberately the same authority that `agents/fire_danger_agent.py`
reads its `danger_level` from, so a citation about a danger class refers to the exact
classification scheme that produced the number in the detected event.

## Licences and attribution

All three documents are openly licensed. Attribution is reproduced in full at the bottom
of each file, and summarised here.

### 1. NWCG Standard Firefighting Orders, Watch Out Situations, and LCES

- **Publisher:** National Wildfire Coordinating Group (NWCG), Incident Response Pocket
  Guide (IRPG), PMS 461, as published by the U.S. National Park Service.
- **Source:** https://www.nps.gov/articles/firefighting-orders-watchout-situations.htm
  and https://www.nwcg.gov/publications/pms461
- **Licence:** Public domain. Works of the U.S. federal government are not subject to
  copyright protection in the United States (17 U.S.C. § 105).

### 2. Copernicus EFFIS Fire Weather Index

- **Publisher:** Copernicus Emergency Management Service, European Forest Fire
  Information System (EFFIS).
- **Source:** https://forest-fire.emergency.copernicus.eu/about-effis/technical-background/fire-danger-forecast
- **Licence:** Copernicus open licence — free use, including commercial use, with
  attribution.
- **Required notice:** Contains modified Copernicus Emergency Management Service
  information. Neither the European Commission nor ECMWF is responsible for any use of
  this information.

### 3. USFA Structure Triage in the Wildland/Urban Interface

- **Author:** Keith Brown, Lake Dillon Fire Authority, Silverthorne, CO.
- **Publisher:** U.S. Fire Administration, National Fire Academy, Executive Fire Officer
  Program, February 1994.
- **Source:** https://apps.usfa.fema.gov/pdf/efop/tr_94kb.pdf
- **Licence:** Public domain as a work prepared for a U.S. federal agency programme.
- **Note:** The source document quotes numeric requirements from NFPA 299, "Standard for
  Protection of Life and Property from Wildfire" (1991). NFPA standards are themselves
  copyrighted. Only the source document's paraphrase of specific numeric requirements is
  reproduced here; the NFPA standard itself is not included and must not be added to
  this corpus.

## Editorial policy

These files are **derived** documents, not verbatim reproductions of the originals. Each
was assembled from the cited source and restructured under Markdown headings so the
chunker can split it on meaningful boundaries. Two rules govern that editing:

1. **Numbered doctrine is verbatim.** The 10 Standard Firefighting Orders, the 18 Watch
   Out Situations, and the FWI class thresholds are reproduced exactly as published.
   Never paraphrase these — the citation verifier matches the model's quotes against
   this text, and a grader checks them against the original.
2. **Nothing is invented.** Every operational claim traces to the cited source. If a
   detail was not in the source, it is not here. Where a source is silent, the gap is
   left visible rather than filled in.

## Adding a document

1. Confirm the licence permits redistribution, and record it.
2. Convert to Markdown with `##`/`###` headings; the chunker splits on those, so heading
   quality directly determines retrieval quality.
3. Save as `<hazard>/<document-id>.md` using a lowercase, hyphenated id.
4. Append the attribution block at the bottom of the file.
5. Add an entry to that hazard's `manifest.json`, including the SHA-256:
   ```
   python -c "import hashlib,pathlib; p=pathlib.Path('data/protocols/fire/<file>.md'); print(hashlib.sha256(p.read_bytes()).hexdigest())"
   ```
6. Run `pytest tests/test_protocol_retrieval_service.py` — one test asserts every
   `document_id` on disk has a manifest entry and that chunk ids stay unique.

## Adding a hazard

1. Create `data/protocols/<hazard>/` with at least one document and a `manifest.json`
   carrying `"hazard": "<hazard>"`.
2. Nothing else is required to retrieve from it — `ProtocolRetriever(hazard=...)` and
   `ResponsePlanJudgeAgent(hazard=...)` work immediately.
3. Be aware of the limit: the **judge** is hazard-agnostic, but the **risk and planning
   agents are not**. `analyze_event` returns `skipped/unsupported_event` for any
   `event_type` other than `"fire"`, and both system prompts are fire-specific. Adding a
   flood corpus makes the judge ready for flood; it does not make the pipeline produce
   flood plans.

The corpus is English-only. The retriever's tokenizer matches `[a-z0-9]+`, so a Hebrew
document would tokenise to nothing and be silently unretrievable. Adding one requires
extending the token pattern first — see the note in
`ecoguard/shared/protocols.py`.
