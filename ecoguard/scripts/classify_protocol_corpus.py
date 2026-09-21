"""Assign `function` and `hazard` to each of the 84 procedures.

    python -m ecoguard.scripts.classify_protocol_corpus

Why this is a model pass and not a keyword rule
-----------------------------------------------
Because the titles do not say what the documents are for in any way a rule can
catch. `נוהל שתפ כבה - מי - פתיחת דלתות ופריצה למבנה` is an interface procedure
with the water utility; `מענה מבצעי לשריפות במערכות סולאריות` is tactical.
Nothing lexical separates those, and a wrong label here silently degrades every
retrieval afterwards — which is why the plan asks for a spot-check by hand
rather than trust.

Why the labels matter this much
-------------------------------
Measured on this corpus with the e5 embeddings: for the query "fire approaching
a settlement", high-rise structural tactics scores 0.804 against the correct
clause's 0.827. Two points of cosine. The filter on `function` and `hazard` is
what makes structural doctrine unreachable from a wildland question; the
embedding only makes it unlikely.

Cost
----
Batched twelve documents to a call on Haiku, title plus first page each. Seven
calls for the corpus, a few cents. Re-running is cheap enough that fixing a bad
label by editing the prompt and going again is the expected workflow.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field
from pypdf import PdfReader

from ecoguard.paths import PACKAGE_ROOT
from ecoguard.response_planner.protocols.corpus_schema import FUNCTIONS, HAZARDS
from ecoguard.shared.llm import ClaudeLLMService, build_system_blocks

RAW = PACKAGE_ROOT / "data" / "protocols" / "raw"
OUTPUT = RAW / "classification.json"

# Enough of page one to show what the document is; the header block and the
# purpose clause both sit in the first few hundred characters.
PAGE_ONE_CHARS = 700
BATCH = 12

# Classification is a labelling task with a fixed vocabulary and a short input.
# Sonnet would cost several times more and has nothing to add here.
MODEL = "claude-haiku-4-5-20251001"

SYSTEM = """\
You classify procedures of the Israeli Fire and Rescue Authority so a retrieval
system can filter them before ranking.

For each document you are given an index, its Hebrew title, and the beginning of
its first page. Return one classification per index.

`function` — what the document is FOR:
- escalation: when an event becomes a district or national matter; thresholds
  and criteria for calling in higher command
- dispatch: who and what gets sent; assistance requests; call handling
- command: incident command, roles, staging, on-scene organisation
- interface: working with another organisation — MDA, police, Health,
  Transport, Education, the Meteorological Service, KKL, utilities
- tactical: how to actually fight or handle a specific kind of incident
- investigation: after-action review, inquiry, reporting on what happened
- administrative: equipment maintenance, training, records, internal admin

`hazard` — what kind of incident it applies to:
- wildland: forest, brush, open-area fire
- structural: buildings, high-rise
- vehicle: cars, trains, aircraft, vessels
- hazmat: hazardous materials, chemical, radiological
- aerial: aircraft used for firefighting
- rescue: extrication, trapped persons, collapse, water rescue
- all: applies regardless of incident type

Keep `reason` under 25 words.

Choose the single best label for each. When a document covers several, choose
what it is PRIMARILY for. Prefer `all` for hazard only when the procedure
genuinely does not distinguish incident type.
"""


class DocumentClass(BaseModel):
    index: int
    function: Literal[FUNCTIONS]  # type: ignore[valid-type]
    hazard: Literal[HAZARDS]  # type: ignore[valid-type]
    confidence: Literal["high", "medium", "low"]
    # Diagnostic only — read during the hand spot-check, never by the planner.
    # Capped so a chatty justification cannot crowd out classifications later in
    # the batch, but generously: a 200-character cap failed validation on the
    # second document of the first batch.
    reason: str = Field(max_length=400)


class Batch(BaseModel):
    classifications: list[DocumentClass]


def first_page(path) -> str:
    try:
        return (PdfReader(path).pages[0].extract_text() or "")[:PAGE_ONE_CHARS]
    except Exception:
        return ""


def run() -> dict:
    manifest = json.loads((RAW / "manifest.json").read_text(encoding="utf-8"))
    documents = [
        {"key": key, "title": meta["title"], "opening": first_page(RAW / key)}
        for key, meta in manifest.items()
    ]

    service = ClaudeLLMService(model=MODEL, effort="low")
    if not service.available:
        raise SystemExit("ANTHROPIC_API_KEY is not usable; cannot classify")

    results: dict[str, dict] = {}
    for start in range(0, len(documents), BATCH):
        window = documents[start:start + BATCH]
        listing = "\n\n".join(
            f"[{start + offset}] {item['title']}\n{item['opening']}"
            for offset, item in enumerate(window)
        )
        parsed = service.parse_structured(
            system_blocks=build_system_blocks(SYSTEM),
            user_text=f"Classify these {len(window)} documents.\n\n{listing}",
            output_format=Batch,
        )
        for entry in parsed.classifications:
            offset = entry.index - start
            if 0 <= offset < len(window):
                results[window[offset]["key"]] = entry.model_dump(mode="json")
        print(f"  classified {min(start + BATCH, len(documents))}/{len(documents)}")

    missing = [item["key"] for item in documents if item["key"] not in results]
    if missing:
        print(f"  WARNING: {len(missing)} documents unclassified: {missing[:5]}")
    return results


def main() -> None:
    results = run()
    OUTPUT.write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    from collections import Counter
    functions = Counter(item["function"] for item in results.values())
    hazards = Counter(item["hazard"] for item in results.values())
    low = [key for key, item in results.items() if item["confidence"] == "low"]

    print(f"\n{len(results)} classified -> {OUTPUT}")
    print("function:", dict(functions))
    print("hazard:  ", dict(hazards))
    if low:
        print(f"low confidence, check by hand ({len(low)}): {low}")


if __name__ == "__main__":
    main()
