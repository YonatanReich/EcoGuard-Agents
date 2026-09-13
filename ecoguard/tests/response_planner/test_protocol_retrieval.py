"""
Offline tests for the protocol retrieval service.

Covers three separable concerns: chunking the markdown corpus, BM25 ranking, and
citation verification. Nothing here touches the network or a language model.

The BM25 tests assert ranking *properties* rather than exact scores. Pinning
scores would make every future tuning change look like a regression; the
properties below are what the retriever actually has to get right.

Run with: pytest
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ecoguard.shared.protocols import (
    DEFAULT_PROTOCOLS_DIR,
    MIN_VERBATIM_SPAN_CHARS,
    ProtocolRetriever,
    normalize_for_match,
    slugify,
    tokenize,
    verify_citations,
)


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def write_corpus(directory: Path, documents: dict[str, str], manifest: dict | None = None) -> Path:
    """
    Write a throwaway corpus to a directory and return it.

    Args:
        directory (Path): Target directory, normally pytest's tmp_path.
        documents (dict): filename stem -> markdown body.
        manifest (dict | None): Optional manifest payload. Omitted entirely when
            None, which exercises the missing-manifest fallback.

    Returns:
        Path: The corpus directory.
    """
    directory.mkdir(parents=True, exist_ok=True)

    for stem, body in documents.items():
        (directory / f"{stem}.md").write_text(body, encoding="utf-8")

    if manifest is not None:
        (directory / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )

    return directory


@pytest.fixture()
def make_retriever(tmp_path: Path):
    """Build a ProtocolRetriever over a temporary corpus."""

    def factory(documents: dict[str, str], manifest: dict | None = None, **kwargs):
        corpus = write_corpus(tmp_path / "protocols", documents, manifest)
        return ProtocolRetriever(corpus_path=corpus, **kwargs)

    return factory


SIMPLE_DOC = """# Test Protocol

## Escape Routes

Firefighters must identify at least two reliable escape routes before engaging.
An escape route that has not been timed against expected fire behaviour is not a
route, it is an assumption. Reassess routes whenever the wind changes direction.

## Defensible Space

The minimum radius of defensible space around a structure should be thirty feet.
Expand defensible space on steeper slopes because flame lengths reach further
uphill. Stored firewood and fuel tanks inside that radius degrade it.
"""


# --------------------------------------------------------------------------
# Tokenizer
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Escape Routes", ["escape", "routes"]),
        ("THE fire AND a route", ["fire", "route"]),          # stopwords dropped
        ("a I x fire", ["fire"]),                              # single chars dropped
        # Numbers survive, but "3"/"0" fall to the single-character filter and
        # "to" is a stopword. Multi-digit thresholds are what matter.
        ("FWI 21.3 to 38.0", ["fwi", "21", "38"]),
        ("", []),
        ("!!! ??? ...", []),
    ],
)
def test_tokenize_normalizes_and_filters(text, expected):
    """Tokenizing lowercases, keeps alphanumerics, and drops noise."""
    assert tokenize(text) == expected


def test_tokenize_handles_none_safely():
    """A missing string must not raise — corpus fields can be absent."""
    assert tokenize(None) == []


@pytest.mark.parametrize(
    "heading,expected",
    [
        ("The Six Fire Danger Classes", "the-six-fire-danger-classes"),
        ("LCES: Lookouts, Communications", "lces-lookouts-communications"),
        ("2. Defensible Space", "2-defensible-space"),
        ("!!!", "section"),
    ],
)
def test_slugify_produces_readable_ids(heading, expected):
    """Slugs stay human-readable so a grader can verify a citation by eye."""
    assert slugify(heading) == expected


# --------------------------------------------------------------------------
# Chunking
# --------------------------------------------------------------------------


def test_chunks_split_on_headings(make_retriever):
    """Each level-2 heading opens its own chunk."""
    retriever = make_retriever({"test-doc": SIMPLE_DOC})

    slugs = [chunk["chunk_id"] for chunk in retriever.chunks]

    assert any("escape-routes" in slug for slug in slugs)
    assert any("defensible-space" in slug for slug in slugs)


def test_chunk_ids_are_unique_and_deterministic(make_retriever):
    """Ids must be unique — the model echoes them back as citation keys."""
    first = make_retriever({"test-doc": SIMPLE_DOC})
    second = make_retriever({"test-doc": SIMPLE_DOC})

    first_ids = [chunk["chunk_id"] for chunk in first.chunks]
    second_ids = [chunk["chunk_id"] for chunk in second.chunks]

    assert len(first_ids) == len(set(first_ids))
    assert first_ids == second_ids


def test_heading_path_is_a_breadcrumb(make_retriever):
    """Chunks carry their parent headings so citations read meaningfully."""
    retriever = make_retriever({"test-doc": SIMPLE_DOC})

    escape = next(c for c in retriever.chunks if "escape-routes" in c["chunk_id"])

    assert escape["heading_path"] == "Test Protocol > Escape Routes"


def test_heading_text_is_indexed_even_when_absent_from_the_body(make_retriever):
    """
    The breadcrumb is tokenized with the body.

    A query using the section's title should find it even when the body never
    repeats that wording.
    """
    document = """# Doc

## Mutual Aid Agreements

Neighbouring brigades respond under standing arrangements when local capacity is
exceeded. Requests travel through the duty officer and are logged on the incident
record for later reconciliation and cost recovery between the participating bodies.
"""
    retriever = make_retriever({"doc": document})

    results = retriever.retrieve("mutual aid", top_k=3)

    assert results, "heading terms must be retrievable"
    assert "mutual-aid" in results[0]["chunk_id"]


def test_oversize_sections_split_with_overlap(make_retriever):
    """A long section splits into parts, and consecutive parts overlap."""
    paragraphs = "\n\n".join(
        f"Paragraph {i} about wildfire suppression tactics and crew safety." * 3
        for i in range(12)
    )
    document = f"# Doc\n\n## Long Section\n\n{paragraphs}\n"

    retriever = make_retriever(
        {"doc": document}, max_chunk_chars=600, chunk_overlap_chars=120
    )

    parts = [c for c in retriever.chunks if "long-section" in c["chunk_id"]]

    assert len(parts) > 1, "oversize section should split"
    assert parts[0]["chunk_id"].endswith("#0")
    assert parts[1]["chunk_id"].endswith("#1")

    tail = parts[0]["text"][-60:]
    assert tail in parts[1]["text"], "consecutive parts must overlap"


def test_small_sections_merge_forward(make_retriever):
    """A bare heading with one line must not become its own chunk."""
    document = """# Doc

## Tiny

One line.

## Substantial Section

This section carries enough text to stand on its own as a retrievable chunk, well
past the two hundred character minimum that governs whether a section is merged
into its successor or kept as an independent unit of retrieval in the index.
"""
    retriever = make_retriever({"doc": document})

    assert not any("#tiny#" in c["chunk_id"] for c in retriever.chunks)
    # The tiny section's content survives, folded into the next chunk.
    assert any("One line." in c["text"] for c in retriever.chunks)


def test_readme_is_excluded_from_the_corpus(make_retriever):
    """README documents the corpus; retrieving licence text would mislead."""
    retriever = make_retriever(
        {"test-doc": SIMPLE_DOC, "README": "# Corpus README\n\nLicence information here.\n"}
    )

    assert all(c["document_id"] != "README" for c in retriever.chunks)


# --------------------------------------------------------------------------
# Manifest and provenance
# --------------------------------------------------------------------------


def test_manifest_supplies_provenance(make_retriever):
    """Title, source URL and licence come from the manifest."""
    manifest = {
        "documents": [
            {
                "document_id": "test-doc",
                "title": "Human Readable Title",
                "source_url": "https://example.invalid/protocol",
                "license": "Public domain",
            }
        ]
    }
    retriever = make_retriever({"test-doc": SIMPLE_DOC}, manifest=manifest)

    chunk = retriever.chunks[0]

    assert chunk["document_title"] == "Human Readable Title"
    assert chunk["source_url"] == "https://example.invalid/protocol"


def test_missing_manifest_degrades_without_failing(make_retriever):
    """A corpus authoring mistake must not take retrieval down."""
    retriever = make_retriever({"test-doc": SIMPLE_DOC})

    assert retriever.available
    assert retriever.chunks[0]["document_title"] == "test-doc"
    assert retriever.chunks[0]["source_url"] is None


def test_malformed_manifest_degrades_without_failing(tmp_path: Path):
    """Invalid JSON is treated as an absent manifest, not an exception."""
    corpus = write_corpus(tmp_path / "protocols", {"test-doc": SIMPLE_DOC})
    (corpus / "manifest.json").write_text("{not json", encoding="utf-8")

    retriever = ProtocolRetriever(corpus_path=corpus)

    assert retriever.available


# --------------------------------------------------------------------------
# BM25 ranking properties
# --------------------------------------------------------------------------


def test_rare_terms_outrank_common_terms(make_retriever):
    """
    A term appearing in one chunk must weigh more than one appearing everywhere.

    This is the core of IDF and the main reason BM25 beats raw term counting.
    """
    shared = "wildfire suppression crews respond to the incident and report status. " * 4
    document = f"""# Doc

## Alpha

{shared} The pyrocumulonimbus column collapsed without warning during the burn.

## Beta

{shared} Routine mop-up continued through the afternoon without further incident.

## Gamma

{shared} Crews were released from the incident at the end of the operational period.
"""
    retriever = make_retriever({"doc": document})

    results = retriever.retrieve("pyrocumulonimbus wildfire", top_k=3)

    assert results
    assert "alpha" in results[0]["chunk_id"], "the rare term must dominate"


def test_term_frequency_saturates(make_retriever):
    """
    Ten occurrences must not score ten times one occurrence.

    Without saturation, keyword stuffing would beat relevance.
    """
    filler = "Operational context sentence providing surrounding narrative detail. " * 6

    once = f"# Doc\n\n## Once\n\nevacuation {filler}\n"
    many = "# Doc\n\n## Many\n\n" + ("evacuation " * 10) + filler + "\n"

    retriever_once = make_retriever({"a": once})
    retriever_many = make_retriever({"b": many})

    score_once = retriever_once.retrieve("evacuation", top_k=1)[0]["score"]
    score_many = retriever_many.retrieve("evacuation", top_k=1)[0]["score"]

    assert score_many > score_once, "more occurrences should still score higher"
    assert score_many < score_once * 10, "but the gain must saturate"


def test_longer_chunks_are_penalised_at_equal_term_frequency(make_retriever):
    """A term in a short chunk is more indicative than the same term buried in a long one."""
    short = "# Doc\n\n## Short\n\nevacuation of the affected residential area proceeded.\n"
    long_body = "Supplementary narrative describing unrelated logistics arrangements. " * 25
    long_doc = f"# Doc\n\n## Long\n\nevacuation {long_body}\n"

    retriever = make_retriever({"a": short, "b": long_doc})

    results = retriever.retrieve("evacuation", top_k=2)

    assert len(results) == 2
    assert "short" in results[0]["chunk_id"]


def test_results_are_sorted_and_bounded(make_retriever):
    """retrieve honours top_k, sorts descending, and returns rank metadata."""
    retriever = make_retriever({"test-doc": SIMPLE_DOC})

    results = retriever.retrieve("escape routes defensible space fire", top_k=1)

    assert len(results) == 1
    assert results[0]["rank"] == 0

    everything = retriever.retrieve("escape routes defensible space fire", top_k=10)
    scores = [item["score"] for item in everything]

    assert scores == sorted(scores, reverse=True)
    assert all(score > 0 for score in scores)


def test_no_match_returns_empty_list(make_retriever):
    """
    Zero-scoring chunks are filtered, not returned as weak matches.

    The agents treat an empty list as "the corpus has nothing to say", which is
    a reason to fail rather than answer from general knowledge.
    """
    retriever = make_retriever({"test-doc": SIMPLE_DOC})

    assert retriever.retrieve("quantum chromodynamics tensor", top_k=5) == []


def test_stopword_only_query_returns_empty(make_retriever):
    """A query that tokenizes to nothing cannot match anything."""
    retriever = make_retriever({"test-doc": SIMPLE_DOC})

    assert retriever.retrieve("the and of to", top_k=5) == []


def test_empty_corpus_is_unavailable(tmp_path: Path):
    """An empty directory yields no chunks and reports itself unavailable."""
    corpus = tmp_path / "empty"
    corpus.mkdir()

    retriever = ProtocolRetriever(corpus_path=corpus)

    assert retriever.available is False
    assert retriever.retrieve("anything", top_k=5) == []


def test_missing_corpus_directory_is_unavailable(tmp_path: Path):
    """A missing directory must not raise at construction."""
    retriever = ProtocolRetriever(corpus_path=tmp_path / "does-not-exist")

    assert retriever.available is False
    assert retriever.retrieve("anything", top_k=5) == []


def test_non_positive_top_k_returns_empty(make_retriever):
    """Guard against a caller passing zero or a negative top_k."""
    retriever = make_retriever({"test-doc": SIMPLE_DOC})

    assert retriever.retrieve("escape routes", top_k=0) == []


# --------------------------------------------------------------------------
# Citation verification — the step that makes grounding real
# --------------------------------------------------------------------------


CHUNKS = [
    {
        "chunk_id": "doc#section#0",
        "document_id": "doc",
        "document_title": "Real Title From Corpus",
        "source_url": "https://example.invalid/doc",
        "heading_path": "Doc > Section",
        "text": (
            "The minimum radius of defensible space should be 30 feet. "
            "Defensible space should be expanded to compensate for steeper slopes."
        ),
    }
]


def test_verbatim_citation_is_verified():
    """An exact quote from a retrieved chunk survives."""
    citations = [
        {
            "chunk_id": "doc#section#0",
            "document_title": "Whatever The Model Said",
            "quoted_text": "The minimum radius of defensible space should be 30 feet.",
            "supports": "Defensible space threshold",
        }
    ]

    verified, dropped = verify_citations(citations, CHUNKS)

    assert dropped == 0
    assert len(verified) == 1
    assert verified[0]["verified"] is True


def test_provenance_comes_from_the_corpus_not_the_model():
    """
    A citation cannot misattribute a real quote to the wrong document.

    Title and URL are overwritten from the retriever's record.
    """
    citations = [
        {
            "chunk_id": "doc#section#0",
            "document_title": "Fabricated Authoritative Sounding Source",
            "quoted_text": "The minimum radius of defensible space should be 30 feet.",
            "supports": "x",
        }
    ]

    verified, _ = verify_citations(citations, CHUNKS)

    assert verified[0]["document_title"] == "Real Title From Corpus"
    assert verified[0]["source_url"] == "https://example.invalid/doc"


def test_whitespace_differences_still_verify():
    """Line wrapping in the model's copy must not fail an honest citation."""
    citations = [
        {
            "chunk_id": "doc#section#0",
            "document_title": "t",
            "quoted_text": "The minimum radius\n  of defensible   space should be 30 feet.",
            "supports": "x",
        }
    ]

    verified, dropped = verify_citations(citations, CHUNKS)

    assert dropped == 0
    assert len(verified) == 1


def test_fabricated_chunk_id_is_dropped():
    """A citation naming a chunk that was never retrieved cannot survive."""
    citations = [
        {
            "chunk_id": "doc#invented-section#0",
            "document_title": "t",
            "quoted_text": "The minimum radius of defensible space should be 30 feet.",
            "supports": "x",
        }
    ]

    verified, dropped = verify_citations(citations, CHUNKS)

    assert verified == []
    assert dropped == 1


def test_paraphrase_is_dropped():
    """
    Plausible wording that is not in the source is exactly what this catches.

    The claim is true and the chunk is real, but the model did not read it.
    """
    citations = [
        {
            "chunk_id": "doc#section#0",
            "document_title": "t",
            "quoted_text": "Homeowners ought to clear about ten metres of brush.",
            "supports": "x",
        }
    ]

    verified, dropped = verify_citations(citations, CHUNKS)

    assert verified == []
    assert dropped == 1


def test_near_verbatim_span_is_accepted():
    """
    A long shared span passes even with a trailing embellishment.

    Forgiving enough to avoid flaky demos, strict enough to prove the chunk was
    actually read.
    """
    citations = [
        {
            "chunk_id": "doc#section#0",
            "document_title": "t",
            "quoted_text": "minimum radius of defensible space should be 30 feet in all cases",
            "supports": "x",
        }
    ]

    verified, dropped = verify_citations(citations, CHUNKS)

    assert dropped == 0
    assert len(verified) == 1


def test_short_shared_span_is_dropped():
    """A few shared words are not evidence the source was read."""
    citations = [
        {
            "chunk_id": "doc#section#0",
            "document_title": "t",
            "quoted_text": "defensible space" + "!" * MIN_VERBATIM_SPAN_CHARS,
            "supports": "x",
        }
    ]

    verified, dropped = verify_citations(citations, CHUNKS)

    assert verified == []
    assert dropped == 1


@pytest.mark.parametrize("citations", [None, [], [{}]])
def test_empty_and_malformed_citations_are_safe(citations):
    """Missing fields must drop the citation, never raise."""
    verified, _ = verify_citations(citations, CHUNKS)

    assert verified == []


def test_normalize_for_match_collapses_whitespace():
    """The normalizer used by verification is case- and whitespace-insensitive."""
    assert normalize_for_match("  The\tFIRE\n\n spread ") == "the fire spread"


# --------------------------------------------------------------------------
# The real committed corpus
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# Hazard selection
# --------------------------------------------------------------------------


def test_default_resolves_to_the_fire_corpus():
    """The no-argument constructor keeps working after the hazard move."""
    retriever = ProtocolRetriever()

    assert retriever.hazard == "fire"
    assert retriever.available
    assert len(retriever.chunks) > 20


def test_hazard_selects_the_corpus_directory():
    explicit = ProtocolRetriever(hazard="fire")
    default = ProtocolRetriever()

    assert [c["chunk_id"] for c in explicit.chunks] == [
        c["chunk_id"] for c in default.chunks
    ]


def test_missing_hazard_corpus_degrades_without_raising():
    """
    The forward-compatibility guarantee.

    A flood judge can be constructed today and will simply have nothing to say
    until data/protocols/flood exists. Constructing it must not raise, and it
    must not silently fall back to the fire corpus — answering flood questions
    from fire doctrine would be worse than answering nothing.
    """
    retriever = ProtocolRetriever(hazard="flood")

    assert retriever.available is False
    assert retriever.chunks == []
    assert retriever.retrieve("water rescue evacuation", top_k=5) == []


def test_explicit_corpus_path_overrides_hazard(make_retriever):
    """Tests point at a temporary corpus without inventing a hazard name."""
    retriever = make_retriever({"test-doc": SIMPLE_DOC}, hazard="flood")

    assert retriever.available is True
    assert any("escape-routes" in c["chunk_id"] for c in retriever.chunks)


def test_hazards_do_not_share_an_index():
    """
    Each hazard is its own BM25 index.

    A shared index would score fire queries against flood chunks and degrade
    IDF on a small corpus.
    """
    fire = ProtocolRetriever(hazard="fire")
    flood = ProtocolRetriever(hazard="flood")

    assert fire.corpus_path != flood.corpus_path
    assert fire.chunks and not flood.chunks


def test_real_corpus_loads_and_is_internally_consistent():
    """
    Guards the committed corpus itself.

    Catches a document added without a manifest entry, a duplicate chunk id, or
    a corpus that silently stopped loading.
    """
    retriever = ProtocolRetriever()

    assert retriever.available, "the committed corpus must load"
    assert len(retriever.chunks) > 20

    ids = [chunk["chunk_id"] for chunk in retriever.chunks]
    assert len(ids) == len(set(ids)), "chunk ids must be unique"

    for chunk in retriever.chunks:
        assert chunk["document_id"] in retriever.documents, (
            f"{chunk['document_id']} has no manifest entry"
        )
        assert chunk["source_url"], "every document needs an attributable source"
        assert chunk["license"], "every document needs a recorded licence"


def test_real_corpus_manifest_matches_files_on_disk():
    """Every manifest entry names a file that exists, and vice versa."""
    retriever = ProtocolRetriever()

    on_disk = {
        path.stem
        for path in DEFAULT_PROTOCOLS_DIR.glob("*.md")
        if path.name.lower() != "readme.md"
    }

    assert on_disk == set(retriever.documents)


@pytest.mark.parametrize(
    "query,expected_document",
    [
        ("very high extreme fire danger class index rating", "effis-fire-weather-index"),
        ("escape routes safety zones lookouts communications", "nwcg-standard-orders-watchouts"),
        ("structure triage defensible space which structures to defend", "usfa-structure-triage"),
    ],
)
def test_real_corpus_routes_queries_to_the_right_document(query, expected_document):
    """
    End-to-end relevance check on the committed corpus.

    Each of the three documents owns a distinct part of the reasoning; a query
    aimed at one must not surface another. This is the closest thing to an
    acceptance test for retrieval quality that runs offline.
    """
    retriever = ProtocolRetriever()

    results = retriever.retrieve(query, top_k=3)

    assert results, f"no protocol match for: {query}"
    assert results[0]["document_id"] == expected_document
