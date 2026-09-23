"""Loading the procedures into the database and making them searchable."""

from __future__ import annotations

import json

from pypdf import PdfReader
from sqlalchemy import text

from ecoguard.database.engine import Session
from ecoguard.paths import PACKAGE_ROOT
from ecoguard.data.protocols.clause_chunker import (
    chunk,
    header_metadata,
    procedure_number,
    related_procedures,
)
from ecoguard.data.protocols.corpus_schema import (
    DDL,
    EMBEDDING_MODEL,
    PASSAGE_PREFIX,
)

RAW = PACKAGE_ROOT / "data" / "protocols" / "raw"

# Chunks per embedding call. The model is local, so this is about memory rather
# than rate limits.
EMBED_BATCH = 32


def document_text(key: str) -> str:
    """One procedure's full text."""
    return "\n".join(
        (page.extract_text() or "")
        for page in PdfReader(RAW / key).pages
    )


def build_rows() -> tuple[list[dict], list[tuple[str, str]]]:
    """Every chunk of every document, plus the cross-reference edges."""
    manifest = json.loads((RAW / "manifest.json").read_text(encoding="utf-8"))
    classification_path = RAW / "classification.json"
    classification = (
        json.loads(classification_path.read_text(encoding="utf-8"))
        if classification_path.exists() else {}
    )
    if not classification:
        print("  WARNING: no classification.json — every chunk will be "
              "unfiltered, which is the single biggest retrieval-quality loss "
              "available. Run classify_protocol_corpus first.")

    rows: list[dict] = []
    edges: list[tuple[str, str]] = []

    for key, meta in manifest.items():
        body = document_text(key)
        if len(body.strip()) < 200:
            print(f"  skipped (no extractable text): {key}")
            continue

        number = procedure_number(body)
        header = header_metadata(body)
        labels = classification.get(key, {})

        for edge in related_procedures(body):
            if number:
                edges.append((number, edge))

        for piece in chunk(body, title=meta["title"]):
            rows.append({
                "document_key": key,
                "procedure_number": number,
                "title": meta["title"],
                "division": meta["division"],
                "classification": header["classification"],
                # Everything in this corpus was found publicly and may ship.
                # The marking is still recorded above rather than erased.
                "external_pub_ok": True,
                "publish_date": header["publish_date"],
                "doctrine_layer": "israeli",
                "function": labels.get("function"),
                "hazard": labels.get("hazard"),
                "clause_path": piece["clause_path"],
                "heading": piece["heading"][:500],
                "content": piece["content"],
                "content_tokens": len(piece["content"].split()),
            })

    return rows, edges


def embed(contents: list[str]) -> list[list[float]]:
    """Turn passages into the form the search compares against."""
    from fastembed import TextEmbedding

    model = TextEmbedding(EMBEDDING_MODEL)
    vectors: list[list[float]] = []
    prefixed = [f"{PASSAGE_PREFIX}{item}" for item in contents]
    for index, vector in enumerate(model.embed(prefixed, batch_size=EMBED_BATCH)):
        vectors.append(vector.tolist())
        if (index + 1) % 200 == 0:
            print(f"  embedded {index + 1}/{len(contents)}")
    return vectors


def store(rows: list[dict], edges: list[tuple[str, str]]) -> None:
    """Write the passages and their links to the database."""
    with Session() as session:
        for statement in DDL.split(";"):
            if statement.strip():
                session.execute(text(statement))
        session.commit()

        session.execute(text("TRUNCATE protocol_chunks"))
        session.execute(text("TRUNCATE protocol_references"))
        session.execute(
            text(
                """
                INSERT INTO protocol_chunks
                  (document_key, procedure_number, title, division,
                   classification, external_pub_ok, publish_date, doctrine_layer,
                   function, hazard, clause_path, heading, content,
                   content_tokens, embedding, tsv)
                VALUES
                  (:document_key, :procedure_number, :title, :division,
                   :classification, :external_pub_ok, CAST(:publish_date AS date),
                   :doctrine_layer, :function, :hazard, :clause_path, :heading,
                   :content, :content_tokens, CAST(:embedding AS vector),
                   to_tsvector('simple', :content))
                """
            ),
            rows,
        )
        if edges:
            session.execute(
                text(
                    "INSERT INTO protocol_references (from_procedure, to_procedure) "
                    "VALUES (:a, :b) ON CONFLICT DO NOTHING"
                ),
                [{"a": a, "b": b} for a, b in edges],
            )
        session.commit()


def main() -> None:
    """Load the corpus from the command line."""
    print("building chunks...")
    rows, edges = build_rows()
    print(f"  {len(rows)} chunks from {len({r['document_key'] for r in rows})} documents")

    print(f"embedding with {EMBEDDING_MODEL}...")
    vectors = embed([row["content"] for row in rows])
    for row, vector in zip(rows, vectors):
        row["embedding"] = str(vector)

    print("storing...")
    store(rows, edges)

    with Session() as session:
        total = session.execute(text("SELECT count(*) FROM protocol_chunks")).scalar()
        by_function = session.execute(
            text(
                "SELECT function, hazard, count(*) FROM protocol_chunks "
                "GROUP BY 1, 2 ORDER BY 3 DESC"
            )
        ).all()
        procedures = session.execute(
            text("SELECT count(DISTINCT procedure_number) FROM protocol_chunks")
        ).scalar()

    print(f"\n{total} chunks stored, {procedures} distinct procedure numbers")
    print("function / hazard:")
    for function, hazard, count in by_function[:12]:
        print(f"  {str(function):15} {str(hazard):12} {count}")


if __name__ == "__main__":
    main()
