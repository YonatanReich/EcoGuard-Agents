"""The table the protocol passages are stored in.

Passages are filtered by what they are about before they are ranked, which is
where most of the quality comes from: for "fire approaching a settlement",
high-rise building tactics scores almost as well as the correct clause, so
ranking alone would surface the wrong doctrine whenever the wording tilted. A
filter makes that impossible; a better model only makes it unlikely.

The publication date is stored because these procedures replace each other, and
a 2016 document outranking its 2025 replacement is a correctness bug wearing
the costume of a ranking preference."""

from __future__ import annotations

# The embedding model, and the single place it is named. Changing it is a
# re-ingest, not a rewrite: the dimension below must match, and every stored
# vector must be rebuilt, because two models do not share a vector space.
#
# e5-large is 2.24 GB. If the deployment target cannot hold it, the same
# pipeline runs with `sentence-transformers/paraphrase-multilingual-mpnet-base-v2`
# at 768 dimensions and 1.0 GB — change both constants and re-run ingestion.
EMBEDDING_MODEL = "intfloat/multilingual-e5-large"
EMBEDDING_DIMENSIONS = 1024

# e5 models are trained with these prefixes and lose accuracy without them.
# A stored passage and a live query are embedded differently on purpose.
QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "

DDL = f"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS protocol_chunks (
  id                 bigserial PRIMARY KEY,
  document_key       text        NOT NULL,
  procedure_number   text,
  title              text        NOT NULL,
  division           text,
  classification     text        NOT NULL DEFAULT 'unrestricted',
  external_pub_ok    boolean     NOT NULL DEFAULT true,
  publish_date       date,
  supersedes         text,
  doctrine_layer     text        NOT NULL DEFAULT 'israeli',
  function           text,
  hazard             text,
  clause_path        text,
  heading            text,
  content            text        NOT NULL,
  content_tokens     integer     NOT NULL DEFAULT 0,
  embedding          vector({EMBEDDING_DIMENSIONS}),
  tsv                tsvector,
  ingested_at        timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT protocol_chunks_layer
    CHECK (doctrine_layer IN ('israeli', 'international'))
);

CREATE INDEX IF NOT EXISTS protocol_chunks_embedding
  ON protocol_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS protocol_chunks_tsv
  ON protocol_chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS protocol_chunks_filters
  ON protocol_chunks (function, hazard);
CREATE INDEX IF NOT EXISTS protocol_chunks_procedure
  ON protocol_chunks (procedure_number);
CREATE INDEX IF NOT EXISTS protocol_chunks_document
  ON protocol_chunks (document_key);

-- The cross-reference graph. `נוהל` documents cite each other explicitly under
-- מסמכי קריאה קשורים, and following a citation from escalation to dispatch is
-- the reasoning the planner's `get_related` tool exists to support.
CREATE TABLE IF NOT EXISTS protocol_references (
  from_procedure text NOT NULL,
  to_procedure   text NOT NULL,
  PRIMARY KEY (from_procedure, to_procedure)
);
"""

# The controlled vocabularies. Free text here would silently fragment the
# filter that carries most of the retrieval quality — 'wildland' and 'Wildland'
# and 'open_area' would be three buckets, and a filter on any one of them would
# quietly drop two thirds of the corpus.
FUNCTIONS = (
    "escalation",    # when an event becomes a district or national matter
    "dispatch",      # who and what is sent
    "command",       # incident command, roles, staging
    "interface",     # working with MDA, police, Health, Transport, KKL
    "tactical",      # how to fight it
    "investigation", # after the event
    "administrative",
)

HAZARDS = (
    "wildland",
    "structural",
    "vehicle",
    "hazmat",
    "aerial",
    "rescue",
    "all",
)
