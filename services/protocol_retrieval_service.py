"""
Protocol Retrieval Service

Responsible for the retrieval half of the project's RAG pipeline: it loads the
committed fire-protocol corpus from data/protocols, splits it into chunks, and
ranks those chunks against a query using BM25.

This is what makes the risk and planning agents "protocol-grounded" rather than
reliant on the model's general knowledge. The agents may only cite text that
this service actually returned, and verify_citations() checks every citation the
model produces against the chunk it claims to quote.

Why BM25 by hand rather than a library or embeddings:
    The corpus is three documents. BM25 is roughly thirty lines of textbook
    arithmetic, is fully deterministic, needs no model download, no API key and
    no network, and runs in single-digit milliseconds. rank_bm25 would pull in
    numpy for the same result. Keyword overlap is genuinely effective here
    because protocol language is consistent and technical: a query mentioning
    "defensible space" or "escape route" matches the section that defines it.

Why no on-disk index:
    Deliberate. Chunking three markdown files takes a few milliseconds at
    import, so the process-lifetime in-memory index built in __init__ is
    sufficient. A SQLite index in data/generated/ would be ceremony. Revisit
    only if the corpus grows by an order of magnitude.

Swap seam:
    Anything exposing `.retrieve(query, top_k) -> list[dict]`, where the dicts
    carry chunk_id / text / document_title / score, can be injected into either
    agent in place of this class. Replacing BM25 with embeddings therefore
    touches this file alone; no abstract base class is needed.

Language:
    The corpus is English-only and the tokenizer matches ``[a-z0-9]+``. A Hebrew
    protocol document would tokenise to nothing and be silently unretrievable.
    Adding one requires extending TOKEN_PATTERN to cover ``\\u0590-\\u05FF``
    first, and revisiting the stopword list.

Consumed by: agents.risk_analysis_agent, agents.response_planning_agent
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

DEFAULT_PROTOCOLS_DIR = Path(__file__).resolve().parents[1] / "data" / "protocols"

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")

# Deliberately small. An aggressive stopword list would strip terms that carry
# real meaning in protocol text ("no", "not", "all", "before", "down").
STOPWORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is",
        "are", "be", "been", "was", "were", "that", "this", "these", "those",
        "it", "its", "as", "at", "by", "from", "with", "which", "than", "then",
        "there", "their", "they", "them", "has", "have", "had", "can", "may",
        "will", "would", "should", "must", "such", "into", "if", "but", "also",
    }
)

# Chunking thresholds, in characters. A chunk should be big enough to carry a
# complete idea a citation can quote from, and small enough that a top-5
# retrieval fits comfortably in a prompt.
DEFAULT_MAX_CHUNK_CHARS = 1200
DEFAULT_CHUNK_OVERLAP_CHARS = 150
MIN_CHUNK_CHARS = 200

# Standard BM25 parameters. k1 controls how fast term frequency saturates;
# b controls how strongly long chunks are penalised.
DEFAULT_K1 = 1.5
DEFAULT_B = 0.75

# Citation verification. A quote must either appear whole in the cited chunk, or
# share a contiguous span of at least this many characters with it. The span
# fallback tolerates minor whitespace and punctuation drift in the model's copy
# without tolerating paraphrase.
MIN_VERBATIM_SPAN_CHARS = 40


def tokenize(text: str) -> list[str]:
    """
    Split text into scoreable terms.

    Lowercases, keeps alphanumeric runs only, and drops stopwords and
    single-character tokens.

    Args:
        text (str): Raw text.

    Returns:
        list[str]: Tokens in order of appearance. Order does not affect BM25 but
            is preserved so the output is easy to inspect while debugging.
    """
    if not text:
        return []

    return [
        token
        for token in TOKEN_PATTERN.findall(text.lower())
        if len(token) > 1 and token not in STOPWORDS
    ]


def slugify(text: str) -> str:
    """
    Turn a heading into a short, stable, URL-safe id fragment.

    Args:
        text (str): Heading text.

    Returns:
        str: Lowercase hyphenated slug, or "section" when the heading has no
            usable characters.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    # Keep ids readable at a glance; the document id already disambiguates.
    slug = "-".join(slug.split("-")[:6])
    return slug or "section"


def normalize_for_match(text: str) -> str:
    """
    Normalize text for citation verification.

    Casefolds and collapses all whitespace runs to single spaces, so a quote
    that differs from the source only in line wrapping still matches.

    Args:
        text (str): Text to normalize.

    Returns:
        str: Normalized text.
    """
    return " ".join(text.casefold().split())


def _longest_common_span(needle: str, haystack: str) -> int:
    """
    Length of the longest contiguous substring of `needle` present in `haystack`.

    Used as the near-verbatim fallback in citation verification. Short-circuits
    as soon as a span of MIN_VERBATIM_SPAN_CHARS is confirmed, so the quadratic
    worst case is never reached for text that verifies.

    Args:
        needle (str): Normalized candidate quote.
        haystack (str): Normalized source chunk text.

    Returns:
        int: Longest matching span length, capped once the threshold is met.
    """
    if not needle or not haystack:
        return 0

    best = 0

    for start in range(len(needle)):
        # No remaining window can beat what we already have.
        if len(needle) - start <= best:
            break

        end = start + best + 1
        while end <= len(needle) and needle[start:end] in haystack:
            best = end - start
            if best >= MIN_VERBATIM_SPAN_CHARS:
                return best
            end += 1

    return best


def verify_citations(citations: list[dict], chunks: list[dict]) -> tuple[list[dict], int]:
    """
    Check that each citation quotes a chunk that was actually retrieved.

    This is the step that makes grounding real rather than requested. A language
    model can produce a plausible chunk id and a plausible quotation from
    memory; only comparing both against the retrieved text catches that.

    A citation survives when its chunk_id is in the retrieved set AND its
    quoted_text either appears in that chunk after normalization, or shares a
    contiguous span of at least MIN_VERBATIM_SPAN_CHARS with it.

    Surviving citations take their document_title and source_url from the
    retriever's own record, never from the model's self-report, so a citation
    cannot misattribute a real quote to the wrong document.

    Args:
        citations (list[dict]): Model-reported citations, each with chunk_id,
            quoted_text and supports.
        chunks (list[dict]): The chunks that were actually retrieved.

    Returns:
        tuple[list[dict], int]: Verified citations, and the number dropped.
    """
    chunks_by_id = {chunk["chunk_id"]: chunk for chunk in chunks}

    verified: list[dict] = []
    dropped = 0

    for citation in citations or []:
        chunk = chunks_by_id.get(citation.get("chunk_id"))

        if chunk is None:
            dropped += 1
            continue

        quote = normalize_for_match(citation.get("quoted_text", ""))
        source_text = normalize_for_match(chunk.get("text", ""))

        if not quote:
            dropped += 1
            continue

        if quote not in source_text:
            span = _longest_common_span(quote, source_text)
            if span < MIN_VERBATIM_SPAN_CHARS:
                dropped += 1
                continue

        verified.append(
            {
                "chunk_id": chunk["chunk_id"],
                "document_id": chunk["document_id"],
                # Trust the corpus, not the model, for provenance.
                "document_title": chunk["document_title"],
                "source_url": chunk["source_url"],
                "heading_path": chunk["heading_path"],
                "quoted_text": citation.get("quoted_text", "").strip(),
                "supports": citation.get("supports", "").strip(),
                "verified": True,
            }
        )

    return verified, dropped


class ProtocolRetriever:
    """
    Offline BM25 retrieval over the committed fire-protocol corpus.

    The corpus is loaded and indexed once, in __init__. Instances are stateless
    afterwards and safe to share across requests, which is how backend.main uses
    this class.

    Attributes:
        corpus_path (Path): Directory holding the protocol markdown and manifest.
        chunks (list[dict]): Every indexed chunk, in document order.
        documents (dict): Manifest metadata keyed by document_id.
    """

    def __init__(
        self,
        *,
        corpus_path: Path | str = DEFAULT_PROTOCOLS_DIR,
        k1: float = DEFAULT_K1,
        b: float = DEFAULT_B,
        max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
        chunk_overlap_chars: int = DEFAULT_CHUNK_OVERLAP_CHARS,
    ) -> None:
        self.corpus_path = Path(corpus_path)
        self.k1 = k1
        self.b = b
        self.max_chunk_chars = max_chunk_chars
        self.chunk_overlap_chars = chunk_overlap_chars

        self.documents = self.load_manifest()
        self.chunks = self.build_chunks()

        self._build_index()

    @property
    def available(self) -> bool:
        """True when the corpus loaded and produced at least one chunk."""
        return bool(self.chunks)

    def load_manifest(self) -> dict:
        """
        Read manifest.json into a mapping keyed by document_id.

        A missing or malformed manifest is not fatal: documents fall back to
        metadata derived from the filename, so retrieval still works and only
        provenance is degraded. That keeps a corpus authoring mistake from
        taking the whole API down.

        Returns:
            dict: document_id -> manifest entry.
        """
        manifest_path = self.corpus_path / "manifest.json"

        if not manifest_path.is_file():
            return {}

        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

        entries = data.get("documents", [])

        return {
            entry["document_id"]: entry
            for entry in entries
            if isinstance(entry, dict) and entry.get("document_id")
        }

    def document_metadata(self, document_id: str) -> dict:
        """
        Provenance for one document, falling back when the manifest lacks it.

        Args:
            document_id (str): Document id, derived from the filename stem.

        Returns:
            dict: title, source_url and license for the document.
        """
        entry = self.documents.get(document_id, {})

        return {
            "document_title": entry.get("title", document_id),
            "source_url": entry.get("source_url"),
            "license": entry.get("license"),
        }

    def build_chunks(self) -> list[dict]:
        """
        Load every markdown document in the corpus and split it into chunks.

        README.md is skipped: it documents the corpus rather than being part of
        it, and retrieving licence text as if it were protocol guidance would be
        actively misleading.

        Returns:
            list[dict]: Chunks across all documents, in filename order.
        """
        if not self.corpus_path.is_dir():
            return []

        chunks: list[dict] = []

        for path in sorted(self.corpus_path.glob("*.md")):
            if path.name.lower() == "readme.md":
                continue

            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue

            chunks.extend(self.chunk_document(path.stem, text))

        return chunks

    def chunk_document(self, document_id: str, text: str) -> list[dict]:
        """
        Split one markdown document into retrievable chunks.

        Sections are cut on `##` and `###` headings, which is why heading
        quality in the corpus directly determines retrieval quality. Oversize
        sections are re-split on paragraph boundaries with overlap; undersize
        sections are merged forward so a bare heading never becomes a chunk.

        Args:
            document_id (str): Document id, used as the chunk id prefix.
            text (str): Full markdown source.

        Returns:
            list[dict]: Chunks with ids, heading paths and provenance.
        """
        sections = self._split_sections(text)
        sections = self._merge_small_sections(sections)

        metadata = self.document_metadata(document_id)

        chunks: list[dict] = []

        for section in sections:
            parts = self._split_oversize(section["body"])

            for part_index, part in enumerate(parts):
                heading_path = section["heading_path"]

                # Prepend the breadcrumb before tokenising so section titles
                # contribute to the score — a query for "defensible space" should
                # match the section named that even if the body says "the space".
                indexed_text = f"{heading_path}\n\n{part}" if heading_path else part

                chunks.append(
                    {
                        "chunk_id": f"{document_id}#{section['slug']}#{part_index}",
                        "document_id": document_id,
                        "document_title": metadata["document_title"],
                        "source_url": metadata["source_url"],
                        "license": metadata["license"],
                        "heading_path": heading_path,
                        "text": part,
                        "tokens": tokenize(indexed_text),
                    }
                )

        return chunks

    def _split_sections(self, text: str) -> list[dict]:
        """
        Cut markdown into sections on `##` and `###` headings.

        Maintains a heading stack so each section carries the breadcrumb of its
        parents, e.g. "Structure Triage > Firefighter Safety Governs the
        Decision".

        Args:
            text (str): Full markdown source.

        Returns:
            list[dict]: Sections with heading_path, slug and body.
        """
        sections: list[dict] = []

        # Heading levels 1-3; index 0 is the document title.
        stack: list[str] = ["", "", ""]
        current_lines: list[str] = []
        current_path = ""
        current_slug = "preamble"

        def flush() -> None:
            body = "\n".join(current_lines).strip()
            if body:
                sections.append(
                    {
                        "heading_path": current_path,
                        "slug": current_slug,
                        "body": body,
                    }
                )

        for line in text.splitlines():
            match = re.match(r"^(#{1,3})\s+(.*\S)\s*$", line)

            if not match:
                current_lines.append(line)
                continue

            level = len(match.group(1))
            heading = match.group(2).strip()

            # A level-1 heading is the document title and does not open a chunk
            # of its own; levels 2 and 3 do.
            if level == 1:
                stack = [heading, "", ""]
                current_lines.append(line)
                continue

            flush()
            current_lines = []

            stack[level - 1] = heading
            for deeper in range(level, 3):
                stack[deeper] = ""

            current_path = " > ".join(part for part in stack if part)
            current_slug = slugify(heading)

        flush()

        return sections

    def _merge_small_sections(self, sections: list[dict]) -> list[dict]:
        """
        Fold sections shorter than MIN_CHUNK_CHARS into the following section.

        Without this, a heading with one line under it becomes a chunk that is
        too small to quote from meaningfully, and its terms are scored against
        an unrepresentatively short length.

        Args:
            sections (list[dict]): Sections in document order.

        Returns:
            list[dict]: Sections with small ones merged forward.
        """
        merged: list[dict] = []
        pending: dict | None = None

        for section in sections:
            if pending is not None:
                # The successor keeps its own heading_path and slug: it supplies
                # most of the merged text, so it is the honest label for a
                # citation. Taking the short section's identity instead would
                # file substantive content under a stub heading — which is what
                # collapsed every chunk into "#preamble#0" before this fix.
                section = {
                    "heading_path": section["heading_path"],
                    "slug": section["slug"],
                    "body": f"{pending['body']}\n\n{section['body']}",
                }
                pending = None

            if len(section["body"]) < MIN_CHUNK_CHARS:
                pending = section
                continue

            merged.append(section)

        # A trailing short section has nothing to merge into; keep it rather
        # than silently dropping content.
        if pending is not None:
            if merged:
                merged[-1]["body"] = f"{merged[-1]['body']}\n\n{pending['body']}"
            else:
                merged.append(pending)

        return merged

    def _split_oversize(self, body: str) -> list[str]:
        """
        Split a section body that exceeds max_chunk_chars on paragraph bounds.

        Consecutive parts overlap by chunk_overlap_chars so a passage spanning a
        split point is still quotable in full from at least one part.

        Args:
            body (str): Section body text.

        Returns:
            list[str]: One or more parts, each within the size budget where the
                paragraph structure allows it.
        """
        if len(body) <= self.max_chunk_chars:
            return [body]

        paragraphs = [p for p in re.split(r"\n\s*\n", body) if p.strip()]

        parts: list[str] = []
        current = ""

        for paragraph in paragraphs:
            candidate = f"{current}\n\n{paragraph}" if current else paragraph

            if len(candidate) <= self.max_chunk_chars or not current:
                current = candidate
                continue

            parts.append(current)

            overlap = current[-self.chunk_overlap_chars:] if self.chunk_overlap_chars else ""
            current = f"{overlap}\n\n{paragraph}" if overlap else paragraph

        if current:
            parts.append(current)

        return parts

    def _build_index(self) -> None:
        """
        Precompute the corpus statistics BM25 needs.

        Builds per-chunk term frequencies and lengths, corpus-wide document
        frequencies, and the average chunk length.
        """
        self._term_frequencies: list[Counter] = []
        self._lengths: list[int] = []
        document_frequency: Counter = Counter()

        for chunk in self.chunks:
            tokens = chunk["tokens"]
            frequencies = Counter(tokens)

            self._term_frequencies.append(frequencies)
            self._lengths.append(len(tokens))
            document_frequency.update(frequencies.keys())

        self._document_frequency = document_frequency
        self._chunk_count = len(self.chunks)
        self._average_length = (
            sum(self._lengths) / self._chunk_count if self._chunk_count else 0.0
        )

    def _idf(self, term: str) -> float:
        """
        Inverse document frequency for one term.

        Uses the ``log(1 + (N - df + 0.5) / (df + 0.5))`` form, which stays
        positive for every term. The classic BM25 IDF goes negative for terms
        appearing in more than half the corpus, which on a three-document corpus
        would let a common term actively subtract from a chunk's score.

        Args:
            term (str): Query term.

        Returns:
            float: IDF weight, always >= 0.
        """
        document_frequency = self._document_frequency.get(term, 0)

        if document_frequency == 0:
            return 0.0

        return math.log(
            1.0
            + (self._chunk_count - document_frequency + 0.5)
            / (document_frequency + 0.5)
        )

    def score_chunk(self, index: int, query_tokens: list[str]) -> float:
        """
        BM25 score for one chunk against the query.

        Args:
            index (int): Chunk index.
            query_tokens (list[str]): Tokenized query.

        Returns:
            float: Score. Zero means no query term occurs in the chunk.
        """
        frequencies = self._term_frequencies[index]
        length = self._lengths[index]

        if not length:
            return 0.0

        score = 0.0

        for term in query_tokens:
            term_frequency = frequencies.get(term, 0)

            if not term_frequency:
                continue

            denominator = term_frequency + self.k1 * (
                1.0 - self.b + self.b * length / self._average_length
            )

            score += self._idf(term) * (term_frequency * (self.k1 + 1.0)) / denominator

        return score

    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        """
        Return the highest-scoring protocol chunks for a query.

        Chunks scoring zero are filtered out rather than returned as weak
        matches. That distinction matters upstream: an empty list means "the
        corpus has nothing to say about this", which the agents treat as a
        reason to fail rather than to answer from general knowledge.

        Args:
            query (str): Free-text query, built by the calling agent from a
                detected event.
            top_k (int): Maximum chunks to return.

        Returns:
            list[dict]: Chunks sorted by score descending, each with chunk_id,
                document_id, document_title, source_url, license, heading_path,
                text, score and rank. Empty when the corpus is empty or nothing
                matches.
        """
        if not self.chunks or top_k <= 0:
            return []

        query_tokens = tokenize(query)

        if not query_tokens:
            return []

        scored = [
            (self.score_chunk(index, query_tokens), index)
            for index in range(self._chunk_count)
        ]

        matches = [pair for pair in scored if pair[0] > 0.0]

        # Sort by score descending, breaking ties on chunk order so results are
        # deterministic across runs.
        matches.sort(key=lambda pair: (-pair[0], pair[1]))

        results = []

        for rank, (score, index) in enumerate(matches[:top_k]):
            chunk = self.chunks[index]

            results.append(
                {
                    "chunk_id": chunk["chunk_id"],
                    "document_id": chunk["document_id"],
                    "document_title": chunk["document_title"],
                    "source_url": chunk["source_url"],
                    "license": chunk["license"],
                    "heading_path": chunk["heading_path"],
                    "text": chunk["text"],
                    "score": round(score, 4),
                    "rank": rank,
                }
            )

        return results
