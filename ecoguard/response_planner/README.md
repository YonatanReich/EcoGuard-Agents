# response_planner/

Turns an assessment into a plan: which units do what, by when, grounded in
published protocol rather than invented.

`protocols/` is the RAG corpus, one directory per hazard, each with a manifest
carrying per-document sha256 and licence. It lives here rather than under
`data/` because the corpus and the agent citing it are one thing — a protocol
added without a planner change is invisible, and a planner change without the
corpus is ungrounded.

Retrieval itself is in `ecoguard/shared/protocols.py`, because analysis and the
plan judge read the corpus too.
