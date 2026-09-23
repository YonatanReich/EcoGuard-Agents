"""Searching the protocol corpus, two ways at once.

Meaning-based search answers "what is this about", and is the only thing that
works on Hebrew here: a keyword matcher sees four spellings of the same word as
four unrelated words, and a test query returned nothing at all - not degraded,
blind.

Keyword search answers "find me exactly this", which meaning-based search is
bad at: a procedure number embeds as a smear of digits near every other
procedure number, and somebody asking for a procedure by number wants that
procedure.

Passages are filtered by subject before ranking, and the newer document wins a
tie."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Mapping, Sequence

from sqlalchemy import text

from ecoguard.database.engine import Session
from ecoguard.data.protocols.corpus_schema import (
    EMBEDDING_MODEL,
    QUERY_PREFIX,
)

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 8

# How far down each channel to look before fusing. Wider than top_k so a chunk
# that ranks fourth semantically and fortieth lexically can still surface.
CHANNEL_DEPTH = 40

# Reciprocal rank fusion's smoothing constant, at its usual value. Left
# unweighted between channels: the plan says not to tune the balance before
# measuring, and nothing here has been measured yet.
RRF_K = 60


@lru_cache(maxsize=1)
def _model():
    """The embedding model, loaded once per process.

    Loading takes a few seconds and the planner may retrieve several times in
    one incident, so this is cached — but deliberately lazily, so importing
    this module in a test that never searches costs nothing.
    """
    from fastembed import TextEmbedding

    return TextEmbedding(EMBEDDING_MODEL)


def embed_query(query: str) -> list[float]:
    """One query as a vector, with the prefix the model was trained on."""
    return next(iter(_model().embed([f"{QUERY_PREFIX}{query}"]))).tolist()


def search_protocols(
    query: str,
    *,
    function: str | Sequence[str] | None = None,
    hazard: str | Sequence[str] | None = None,
    doctrine_layer: str | None = None,
    top_k: int = DEFAULT_TOP_K,
) -> list[dict[str, Any]]:
    """Protocol chunks matching a query, filtered then ranked.

    Args:
        query: natural language, Hebrew or English.
        function: restrict to one or more of the `function` vocabulary. This is
            not optional performance tuning — it is what stops structural
            tactics answering a wildland question.
        hazard: likewise. Note that 58 of the 84 documents are `all`, so a
            hazard filter narrows far less than a function filter; passing a
            specific hazard includes `all` automatically, because a procedure
            that applies to every incident applies to this one.
        doctrine_layer: 'israeli' or 'international'.
        top_k: how many to return after fusion.

    Returns:
        Chunks with their scores and provenance, best first. An empty list
        means nothing matched the filters — which is an answer, and the caller
        must report it as a coverage gap rather than widening the filter and
        pretending the result is on point.
    """
    filters = ["embedding IS NOT NULL"]
    params: dict[str, Any] = {"depth": CHANNEL_DEPTH}

    if function:
        names = [function] if isinstance(function, str) else list(function)
        filters.append("function = ANY(:functions)")
        params["functions"] = names
    if hazard:
        names = [hazard] if isinstance(hazard, str) else list(hazard)
        # 'all' is always in scope: a procedure that does not distinguish
        # incident type applies to this incident too, and excluding it would
        # drop two thirds of the corpus from every filtered query.
        if "all" not in names:
            names = [*names, "all"]
        filters.append("hazard = ANY(:hazards)")
        params["hazards"] = names
    if doctrine_layer:
        filters.append("doctrine_layer = :layer")
        params["layer"] = doctrine_layer

    where = " AND ".join(filters)
    params["query_vector"] = str(embed_query(query))
    params["query_text"] = query
    params["top_k"] = top_k

    statement = text(f"""
        WITH semantic AS (
          SELECT id, row_number() OVER (
                   ORDER BY embedding <=> CAST(:query_vector AS vector),
                            publish_date DESC NULLS LAST
                 ) AS rank
          FROM protocol_chunks WHERE {where}
          ORDER BY embedding <=> CAST(:query_vector AS vector)
          LIMIT :depth
        ),
        lexical AS (
          SELECT id, row_number() OVER (
                   ORDER BY ts_rank(tsv, plainto_tsquery('simple', :query_text)) DESC,
                            publish_date DESC NULLS LAST
                 ) AS rank
          FROM protocol_chunks
          WHERE {where}
            AND tsv @@ plainto_tsquery('simple', :query_text)
          LIMIT :depth
        ),
        fused AS (
          SELECT COALESCE(s.id, l.id) AS id,
                 COALESCE(1.0 / ({RRF_K} + s.rank), 0)
               + COALESCE(1.0 / ({RRF_K} + l.rank), 0) AS score,
                 s.rank AS semantic_rank, l.rank AS lexical_rank
          FROM semantic s FULL OUTER JOIN lexical l ON s.id = l.id
        )
        SELECT c.id, c.procedure_number, c.title, c.division, c.classification,
               c.publish_date, c.doctrine_layer, c.function, c.hazard,
               c.clause_path, c.heading, c.content,
               f.score, f.semantic_rank, f.lexical_rank
        FROM fused f JOIN protocol_chunks c ON c.id = f.id
        ORDER BY f.score DESC, c.publish_date DESC NULLS LAST
        LIMIT :top_k
    """)

    with Session() as session:
        rows = session.execute(statement, params).mappings().all()
    return [dict(row) for row in rows]


def get_procedure(number: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """Every chunk of one procedure, by its number, in clause order.

    Exists because semantic search handles identifiers badly: `201.02.003`
    embedded sits near every other dotted number in the corpus. An operator or
    a planner asking for a procedure by number wants that procedure, not
    something that looks like it.
    """
    with Session() as session:
        rows = session.execute(
            text(
                """
                SELECT id, procedure_number, title, division, classification,
                       publish_date, function, hazard, clause_path, heading,
                       content
                FROM protocol_chunks
                WHERE procedure_number = :number
                ORDER BY clause_path NULLS FIRST, id
                LIMIT :limit
                """
            ),
            {"number": number, "limit": limit},
        ).mappings().all()
    return [dict(row) for row in rows]


# A quote shorter than this is not evidence. Matches the value the existing
# verifier uses on the English corpus: below roughly forty characters a span
# can coincide with unrelated text, especially in a corpus where every document
# repeats the same headers and authority names.
MIN_VERBATIM_SPAN_CHARS = 40


def verify_citations(
    citations: Sequence[Mapping[str, Any]],
    chunks: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Keep only citations whose quoted text is actually in what was retrieved.

    This is what makes grounding a property rather than a request. A model can
    produce a plausible procedure number and a plausible Hebrew quotation from
    memory, and the two together read exactly like a real citation. Only
    comparing the quote against the retrieved text catches it.

    Differs from `shared.protocols.verify_citations` in what it matches on.
    That one keys on a chunk id the model must carry correctly; this searches
    every retrieved chunk for the quote and then takes the provenance from
    whichever chunk actually contains it. The consequence is worth having: a
    model that quotes correctly but attributes it to the wrong procedure has
    its attribution **corrected** rather than its citation discarded, and a
    model that invents a quotation cannot be saved by naming a real procedure.

    Returns:
        (verified, dropped). Provenance on every surviving citation comes from
        the corpus, never from the model's self-report, so a real quote cannot
        be hung on the wrong document.
    """
    from ecoguard.shared.protocols import _longest_common_span, normalize_for_match

    prepared = [
        (chunk, normalize_for_match(chunk.get("content") or ""))
        for chunk in chunks
    ]

    verified: list[dict[str, Any]] = []
    dropped = 0

    for citation in citations or ():
        quote = normalize_for_match(str(citation.get("quoted_text") or ""))
        if len(quote) < MIN_VERBATIM_SPAN_CHARS:
            dropped += 1
            continue

        source = None
        for chunk, content in prepared:
            if quote in content:
                source = chunk
                break
        if source is None:
            # Not verbatim anywhere. Allow a long contiguous span, which
            # survives the line-wrapping and RTL segment reversal this corpus
            # extracts with, but not a paraphrase.
            best, best_chunk = 0, None
            for chunk, content in prepared:
                span = _longest_common_span(quote, content)
                if span > best:
                    best, best_chunk = span, chunk
            if best >= MIN_VERBATIM_SPAN_CHARS:
                source = best_chunk

        if source is None:
            dropped += 1
            continue

        verified.append({
            "procedure_number": source.get("procedure_number"),
            "document_title": source.get("title"),
            "clause_path": source.get("clause_path"),
            "division": source.get("division"),
            "publish_date": (
                source["publish_date"].isoformat()
                if source.get("publish_date") else None
            ),
            "quoted_text": str(citation.get("quoted_text") or "").strip(),
            "supports": str(citation.get("supports") or "").strip(),
            "verified": True,
        })

    return verified, dropped
