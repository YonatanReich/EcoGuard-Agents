# Fire Response Protocol Corpus

This directory holds the protocol documents that ground the risk analysis and response
planning agents. `ProtocolRetriever` (see `services/protocol_retrieval_service.py`)
chunks every `.md` file here at import time and retrieves passages by BM25 score. The
language model is only permitted to cite text that was actually retrieved from these
files, and every citation it returns is verified against the source chunk in Python
before it reaches the API response.

`manifest.json` is the machine-readable index: document ids, titles, source URLs,
licences, retrieval dates and SHA-256 hashes. The hashes let you confirm a document has
not drifted from what was reviewed.

## Why these three

Each document covers a different part of the reasoning, and together they span both
halves of the sprint requirement — classifying risk and planning a response.

| Document | Role |
| --- | --- |
| `effis-fire-weather-index.md` | Fire danger classification. Defines the FWI bands the pipeline already collects. |
| `nwcg-standard-orders-watchouts.md` | Engagement safety doctrine. Governs whether and how responders may engage. |
| `usfa-structure-triage.md` | Response actions. Which structures to defend, and when not to. |

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
3. Save as `<document-id>.md` using a lowercase, hyphenated id.
4. Append the attribution block at the bottom of the file.
5. Add an entry to `manifest.json`, including the SHA-256:
   ```
   python -c "import hashlib,pathlib; p=pathlib.Path('data/protocols/<file>.md'); print(hashlib.sha256(p.read_bytes()).hexdigest())"
   ```
6. Run `pytest tests/test_protocol_retrieval_service.py` — one test asserts every
   `document_id` on disk has a manifest entry and that chunk ids stay unique.

The corpus is English-only. The retriever's tokenizer matches `[a-z0-9]+`, so a Hebrew
document would tokenise to nothing and be silently unretrievable. Adding one requires
extending the token pattern first — see the note in
`services/protocol_retrieval_service.py`.
