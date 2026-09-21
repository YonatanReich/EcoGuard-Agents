# EcoGuard — Protocol Corpus & Response Planner

Build plan for the retrieval layer that grounds the response planner, and the
planner that consumes it.

Scoped to one thing: turning 84 Israeli fire authority procedure PDFs plus
public-domain international wildland doctrine into a corpus the planner can
retrieve from, and building the planner around it.

Each phase ends with a **STOP** checkpoint. Stop and wait for review.

---

## Background

The response planner receives an incident report — a fire at a location, a
projected spread footprint, the towns inside it, exposure figures — plus access
to weather data and contact details. It must produce a response plan grounded in
official procedure rather than improvised from general knowledge.

### What the corpus is

**84 Israeli procedure PDFs**, verified text-extractable (no OCR needed):

- `נהלי חטיבת מבצעים` — 42 docs, operations division: tactical guidance,
  command, aerial firefighting, staging areas, incident investigation.
- `נהלי משל"ט ארצי` — 42 docs, national control centre: dispatch, inter-district
  assistance, interfaces with MDA, police, Health, Transport, Education,
  Meteorological Service.

**Plus international wildland doctrine** (NWCG, public domain) to fill a gap
described below.

### Four things already established — do not re-litigate

1. **Hebrew breaks BM25.** Prefixes attach directly to words (ב, ל, ה, ו, כ, מ, ש),
   so `בשריפה` / `לשריפה` / `השריפה` / `שריפה` are four distinct tokens to a
   lexical matcher. The existing `protocol_retrieval_service.py` was built for
   English NWCG text and works there; it will degrade badly on this corpus.
   → Use multilingual embeddings in pgvector, with BM25 as a hybrid second
   channel for exact procedure numbers like `200.210.37`.

2. **The dispatch guidance table (`טבלת ההנחיה לשיגור`) is NOT in the corpus.**
   `נוהל סיוע בין מחוזי` references it as living in שלהבת, the CAD system. That
   table is what maps event type and severity to vehicle counts. Its absence is
   the single biggest gap, and it is not solvable by better retrieval.

3. **Wildland tactics are thin.** The only detailed tactical document is
   `קווים מנחים ללחימה באש במבנים גבוהים ומורכבים` (high-rise). There is no
   open-area / forest fire tactical equivalent. `נוהל הסדרת פעילות קק"ל` covers
   coordination with KKL, not tactics. The corpus is strong on command, control
   and coordination; weak on wildland firefighting technique — which is the
   primary hazard.

4. **Nothing covers evacuation criteria or public advisory content.** Evacuation
   likely routes through פקע"ר. The advisory planner (EA-341) has no Israeli
   source in this set.

---

# PHASE 1 — Ingest the corpus

## 1a. What I need from you before starting

- The two zip files placed at `data/protocols/raw/`.
- Confirmation of the **pgvector-enabled Postgres connection string**
  (`DATABASE_URL`). pgvector must be enabled — `CREATE EXTENSION IF NOT EXISTS vector;`
- A decision on **classification handling**: several documents are marked
  `בלמ"ס` (unclassified but restricted) and some carry explicit external-publication
  permission while others do not. Decide whether restricted documents are
  excluded from any published demo. This must be a stored column, not a
  convention.

## 1b. Filenames are mojibake — decode first

Both archives store Hebrew filenames as `#Uxxxx` escapes. Decode before anything
else, and note that some decoded names exceed filesystem limits on extract:

```python
import re
def decode(name: str) -> str:
    return re.sub(r'#U([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), name)
```

Extract to sequential safe filenames (`ops/00.pdf`) and keep a mapping file of
`safe_name → real_title`. Do not rely on the filesystem to hold the Hebrew names.

## 1c. Chunk on clause numbering, NOT token count

These documents are rigidly structured: `1.`, `1.1`, `2.1.1`, `2.1.2`. That
hierarchy is better chunking than any sliding window.

**Chunk at the second level (`2.1`)**, carrying the parent heading and document
header as context.

Concrete example of why this matters — `נוהל אירועים ארציים` (הוראה 201,
`201.02.003`) defines when an event escalates to national level. Its criteria are
individually numbered clauses:

```
2.1.1  fire in a building of 20 floors or more
2.1.2  event in a building with large population (central station, mall, clinic)
2.1.3  event in mass transit (train, aircraft, ship)
2.1.5  participation of 10 teams or more
2.1.6  danger to a settlement
2.1.7  trapped or injured firefighter evacuated to hospital
2.1.8  more than 10 simultaneous events in one district
2.1.9  two or more trapped persons
```

Each clause must be independently retrievable while still knowing it belongs to
"events with potential for national-level assistance or intervention." A
fixed-size splitter cuts this list in half and destroys it.

## 1d. Metadata schema — this is where retrieval quality comes from

```sql
protocol_chunks (
  id                 bigserial PRIMARY KEY,
  procedure_number   text,        -- '200.210.37', '201.02.003'
  title              text,        -- Hebrew title
  division           text,        -- 'אג"ם / תוה"ד', 'משל"ט ארצי'
  classification     text,        -- 'בלמ"ס' | 'unrestricted'
  external_pub_ok    boolean,
  publish_date       date,
  supersedes         text,
  doctrine_layer     text,        -- 'israeli' | 'international'
  function           text,        -- escalation|dispatch|command|interface|tactical
  hazard             text,        -- fire|structural|wildland|hazmat|aerial|all
  clause_path        text,        -- '2.1.6'
  heading            text,
  content            text,
  embedding          vector(1024),
  tsv                tsvector     -- BM25 channel
);
CREATE INDEX ON protocol_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON protocol_chunks USING gin (tsv);
CREATE INDEX ON protocol_chunks (function, hazard);
CREATE INDEX ON protocol_chunks (procedure_number);
```

**Most retrieval quality comes from filtering on `function` and `hazard` before
ranking, not from better embeddings.** "What resources for a wildfire threatening
a town" must never surface high-rise tactics — a filter guarantees that,
similarity only makes it likely.

Two fields matter for correctness specifically:
- `publish_date` — some procedures supersede others; a 2016 document must not
  outrank a 2025 one.
- `classification` — so restricted material can be excluded from a published demo.

Classify `function` and `hazard` with an LLM pass over each document's title and
first page, then **spot-check by hand**. Getting these wrong silently degrades
every subsequent retrieval.

## 1e. Extraction notes

- Text extraction verified working on all 84 — **no OCR needed**.
- RTL text extracts with reversed segments in places. Do not try to "fix" it —
  embeddings handle it, and reordering risks corrupting the content.
- Some documents contain tables. Note which; table content extracts poorly and
  may need manual transcription if a table turns out to be decision-relevant.
- Largest file is ~6 MB (`עקרונות מנחים לטיפול באתר הרס`). Nothing needs
  special handling for size.

## 1f. Verify

```sql
SELECT function, hazard, count(*) FROM protocol_chunks GROUP BY 1,2;
SELECT count(DISTINCT procedure_number) FROM protocol_chunks;
```

Then retrieve for three probe queries and read the results by hand:
- "שריפה מתקרבת ליישוב" → must surface the escalation criteria, not high-rise
- "סיוע בין מחוזי" → must surface the inter-district dispatch procedure
- "201.02.003" → exact-number lookup must return that procedure

### ▶ STOP. Report chunk counts by function/hazard, and paste the top 3 results for each probe query.

---

# PHASE 2 — Retrieval layer

## 2a. Hybrid search

```python
def search_protocols(query, function=None, hazard=None,
                     doctrine_layer=None, top_k=8):
    """Filter first, then rank. Filters are not optional performance tuning —
    they are what stops structural tactics answering wildland questions."""
```

Combine semantic and lexical scores. Reciprocal rank fusion is fine; don't
over-engineer the weighting before measuring.

**Prefer recent on ties.** Where two chunks from superseding procedures both
match, the later `publish_date` wins.

## 2b. Two more tools the planner gets

```python
def get_procedure(number: str):
    """Exact lookup by procedure number. Semantic search handles these poorly."""

def get_related(procedure_number: str):
    """Follow מסמכי קריאה קשורים — these documents cross-reference each other
    explicitly, and following a citation from escalation to dispatch is exactly
    the reasoning we want."""
```

`get_related` is worth building properly. Parse the cross-reference sections
during ingestion and store the edges.

## 2c. Keep the existing interface

`protocol_retrieval_service.py` already has a swappable interface and is
deliberate hand-written BM25. Replace the implementation behind it; do not
rewrite the callers.

### ▶ STOP. Demonstrate hybrid retrieval beating the current BM25 on the three probe queries.

---

# PHASE 3 — The planner

## 3a. Bounded agentic, NOT an open research loop

Give the planner the three tools above and **cap it at 3–4 tool calls**.

A good filtered first retrieval answers most queries; follow-ups are for
citation-chasing via `get_related`.

**Do not build an agent that searches until it feels confident.** Unbounded cost,
nondeterministic plans, untestable. This system recommends dispatching emergency
vehicles — "the plan varies run to run" is not an acceptable property.

## 3b. Deterministic rubric in code, not retrieved text

The national-escalation criteria in §1c are numeric thresholds with a stated
source. Encode them:

```python
NATIONAL_EVENT_SOURCE = "הוראה 201 / 201.02.003 §2.1"

def is_national_event(event, plan) -> tuple[bool, list[str]]:
    """Returns (is_national, list of triggered clause paths).
    Cites the clause rather than making the LLM re-derive it."""
```

Making the model re-derive arithmetic that is already written down is slower,
costlier and less reliable than a function that cites the clause. **Retrieval is
for the judgment-shaped parts — what the response should look like — not for
thresholds.**

## 3c. Constrain output vocabulary

International doctrine is in the corpus for **fire-behaviour reasoning**, not for
vocabulary. A plan saying "two Type 3 engines and a Type 1 hand crew" is unusable
by an Israeli dispatcher and unassignable by the allocator.

Constrain `resource_requests` to an enum of Israeli resource types drawn from the
Hebrew corpus (כבאית, מכלית, יחידת תגובה מהירה / יתמ, כיתת כוננות, …). Validate
at the schema level, not in the prompt.

## 3d. Every plan cites its sources

`protocol_citations` on the output, listing procedure number and clause path for
each decision. An unsourced recommendation fails validation.

## 3e. Handle the known gaps honestly

Where the corpus lacks coverage — wildland tactics, evacuation criteria, advisory
content — the plan must **say so** rather than confabulating a procedure. A field
like `coverage_gaps: list[str]` on the output.

This is better engineering and a far stronger position in the writeup than a plan
that invents Israeli doctrine that doesn't exist.

### ▶ STOP. Produce plans for three scenarios and show the citations: (1) wildfire approaching a town, (2) wildfire in open terrain with nothing nearby, (3) simultaneous incidents competing for resources.

---

## Out of scope

Do not build these yet:

- The allocator. The planner requests resource **types and counts**; choosing
  specific units from specific stations is a separate batch-assignment problem.
- The advisory planner (EA-341). No Israeli source material exists in this corpus.
- Any attempt to reconstruct the dispatch guidance table. It is not in these
  documents; note the gap rather than inventing thresholds.
- OCR. Not needed — all 84 extract as text.

---

## Open questions for the team

1. **Classification.** Can `בלמ"ס` material be used in a published demo, or only
   locally? Affects whether the corpus can ship with the repo.
2. **The dispatch table.** Is there any route to the שלהבת guidance table —
   through a contact, an FOI request, or a published derivative? It is the
   highest-value missing artifact.
3. **Wildland tactics.** Accept NWCG as the reasoning layer with the gap
   documented, or pursue Israeli wildland doctrine separately?
