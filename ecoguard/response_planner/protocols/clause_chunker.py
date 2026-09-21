"""Cut the procedures where they were already cut: on their clause numbering.

These documents are rigidly numbered — `1.`, `1.1`, `2.1.1`, `2.1.2` — and that
hierarchy is better than any sliding window, because it is the structure the
authors used to separate one rule from the next.

The case that settles it is `נוהל אירועים ארציים` (201.02.003 §2.1), which
lists when an event escalates to national level:

    2.1.5  participation of 10 teams or more
    2.1.6  danger to a settlement
    2.1.7  trapped or injured firefighter evacuated to hospital

Each is independently retrievable and each must still know it belongs to
"events with potential for national-level assistance". A fixed-size splitter
cuts that list somewhere arbitrary and destroys both properties at once.

Chunking at the second level
----------------------------
`2.1` is the unit, carrying its third-level children inline. Splitting at the
third level would make `2.1.6 danger to a settlement` a chunk of five words
with no context; keeping the first level would put the whole of section 2 in
one chunk and lose the ability to retrieve one criterion. The second level is
where a clause is both self-contained and still a rule.

On right-to-left text
---------------------
Hebrew extracts with reversed segments in places. It is left exactly as
extracted: embeddings handle it, and reordering risks corrupting content in a
document that tells somebody how to fight a fire. The clause *numbers* are
Latin digits and survive extraction intact, which is what makes this approach
work at all.
"""

from __future__ import annotations

import re
from typing import Any, Iterator

# A clause opener: `2.`, `2.1`, `2.1.6`, optionally followed by the text. Must
# be at a line start — a bare `2.1` mid-sentence is a cross-reference, not a
# new clause, and treating it as one shatters the paragraph that cites it.
CLAUSE = re.compile(r"^[ \t]*(\d{1,2}(?:\.\d{1,3}){0,3})[.)]?[ \t]+(.*)$")

# This service numbers its documents two different ways, and a reader of the
# build plan would expect only the first:
#
#   201.02.003              the dotted הוראה number — 13 of the 84 documents
#   5750-1116-2021-000761   the archival reference — most of the rest
#
# Matching only the dotted form left 71 of 84 documents with no identifier at
# all, which would have gutted the exact-lookup tool the planner depends on.
# Both are matched, and the dotted form wins where a document carries both,
# because that is the number by which one procedure cites another.
DOTTED_NUMBER = re.compile(r"\b(\d{3}\.\d{2,3}(?:\.\d{2,3})?)\b")
REFERENCE_NUMBER = re.compile(r"\b(\d{4}-\d{4}-\d{4}-\d{6})\b")

# The page-1 header block both divisions share. Each field is its own line and
# each is worth storing: classification decides what may be published, and the
# dates decide which of two superseding procedures is current.
CLASSIFICATION = re.compile(r"סיווג:\s*([^\n]{1,40})")
HEADER_DATE = re.compile(r"\b(\d{2}[./]\d{2}[./]\d{4})\b")

# Where documents list the procedures they depend on. Parsed into the
# reference graph so `get_related` can follow a citation rather than guess.
RELATED_HEADINGS = (
    "מסמכי קריאה קשורים",
    "מסמכים קשורים",
    "נהלים קשורים",
    "אסמכתאות",
)

# Below this a chunk is a heading or a stray line, not a rule. Merged forward
# into the next clause rather than stored, so a two-word heading never competes
# with a real clause for a retrieval slot.
#
# Set from the corpus rather than guessed: at a floor of 80 the median chunk
# came out at 208 characters, meaning half of every retrieval was spent on
# fragments. These procedures are terse, so the floor has to do real work.
MIN_CHUNK_CHARS = 300

# Above this, one clause is really a section. Split on paragraph breaks so a
# long procedure still fits an embedding window without cutting mid-sentence.
MAX_CHUNK_CHARS = 2_400


def procedure_number(text: str) -> str | None:
    """The document's own identifier, in whichever scheme it uses."""
    dotted = DOTTED_NUMBER.search(text)
    if dotted:
        return dotted.group(1)
    reference = REFERENCE_NUMBER.search(text)
    return reference.group(1) if reference else None


def header_metadata(text: str) -> dict[str, Any]:
    """Classification and dates from the page-1 header block.

    `publish_date` is the latest date on the first page. These headers carry a
    drafting date, an approval date and sometimes a revision date, and which
    label sits beside which varies between the two divisions — but the newest
    is the one that decides precedence between superseding procedures, whatever
    it is called.
    """
    classification = CLASSIFICATION.search(text)
    dates = HEADER_DATE.findall(text[:1500])

    def as_date(value: str) -> str:
        day, month, year = re.split(r"[./]", value)
        return f"{year}-{month}-{day}"

    return {
        "classification": (
            classification.group(1).strip() if classification else "unrestricted"
        ),
        "publish_date": max((as_date(value) for value in dates), default=None),
    }


def related_procedures(text: str) -> list[str]:
    """Procedure numbers this document explicitly cites as related.

    Read from the whole text rather than only the cross-reference section: the
    headings vary between the two divisions and a citation in the body is still
    a citation. Self-references are dropped.
    """
    own = procedure_number(text)
    found = []
    for candidate in DOTTED_NUMBER.findall(text):
        if candidate != own and candidate not in found:
            found.append(candidate)
    return found


def _level(clause_path: str) -> int:
    return clause_path.count(".") + 1


def _split_oversize(body: str) -> list[str]:
    """A clause too long to embed, cut on paragraph breaks rather than length."""
    if len(body) <= MAX_CHUNK_CHARS:
        return [body]
    parts, current = [], ""
    for paragraph in re.split(r"\n\s*\n", body):
        if current and len(current) + len(paragraph) > MAX_CHUNK_CHARS:
            parts.append(current.strip())
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current.strip():
        parts.append(current.strip())
    return parts


def chunk(text: str, *, title: str) -> list[dict[str, Any]]:
    """One document's text as second-level clause chunks.

    Args:
        text: the document as extracted, RTL artefacts and all.
        title: the document's real Hebrew title, carried onto every chunk as
            context so a retrieved clause knows which procedure it came from.

    Returns:
        list of dicts with `clause_path`, `heading` (the parent clause's own
        text) and `content`. A document with no clause numbering at all comes
        back as one chunk rather than none — some of these are one-page
        notices, and dropping them because they are not numbered would lose
        them silently.
    """
    lines = text.splitlines()
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    parents: dict[int, str] = {}

    for line in lines:
        match = CLAUSE.match(line)
        if match:
            path, remainder = match.group(1), match.group(2).strip()
            level = _level(path)
            parents[level] = remainder

            if level <= 2:
                # A new second-level clause: this is a chunk boundary.
                if current is not None:
                    sections.append(current)
                current = {
                    "clause_path": path,
                    "heading": " / ".join(
                        parents[depth] for depth in sorted(parents)
                        if depth <= level and parents.get(depth)
                    ),
                    "lines": [line.strip()] if remainder else [],
                }
                continue

        if current is None:
            # Preamble before the first numbered clause — the document header,
            # which carries the procedure number and the date.
            current = {"clause_path": None, "heading": "header", "lines": []}
        current["lines"].append(line.rstrip())

    if current is not None:
        sections.append(current)

    return list(_finalise(sections, title))


def _finalise(sections: list[dict[str, Any]], title: str) -> Iterator[dict[str, Any]]:
    """Merge the scraps, split the giants, and attach the document context."""
    pending = ""
    for section in sections:
        body = "\n".join(section["lines"]).strip()
        if not body:
            continue
        if pending:
            body = f"{pending}\n{body}"
            pending = ""
        if len(body) < MIN_CHUNK_CHARS:
            # Too small to stand alone; carry it into the next clause so a
            # bare heading never occupies a retrieval slot of its own.
            pending = body
            continue

        for part in _split_oversize(body):
            yield {
                "clause_path": section["clause_path"],
                "heading": section["heading"] or title,
                # The title travels *inside* the embedded text. A clause
                # retrieved without knowing which procedure it belongs to is
                # a rule with no authority behind it.
                "content": f"{title}\n{part}",
            }

    if pending:
        yield {
            "clause_path": None,
            "heading": title,
            "content": f"{title}\n{pending}",
        }
