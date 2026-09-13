"""Where things are on disk, resolved from this file rather than the shell.

Every path in the project used to be written relative to the *current working
directory* — so a script worked from the repository root and failed from
anywhere else, and the failure was a missing-file error that said nothing about
why. Eighty-odd such literals across thirty-one files all carried the same
hidden requirement.

Anchoring on `__file__` removes the requirement entirely. A collector run by
cron from `/`, a test invoked from a subdirectory and a notebook in a scratch
folder all resolve the same paths, because the answer depends on where this
module sits and not on where the process happens to have started.

The other reason this exists is that the layout moves. When `data/` relocated
under `ecoguard/`, one constant here changed and nothing else did.
"""

from __future__ import annotations

from pathlib import Path

# This file lives at ecoguard/paths.py, so its parent is the package root and
# the parent above that is the repository.
PACKAGE_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = PACKAGE_ROOT.parent

DATA = PACKAGE_ROOT / "data"

# Machine output and provider caches: rasters, SQLite caches, trained models,
# derived CSVs. Gitignored in its entirety — nothing in here is a source of
# truth, and everything in it can be rebuilt by some script in scripts/.
GENERATED = DATA / "generated"

# Committed reference data: the operational service-area polygon and the
# station rosters an alembic migration seeds from. Small, versioned, and read
# by production rather than by research.
REFERENCE = DATA / "reference"

# Hand-written evaluation cases. Committed inputs, not generated output, which
# is why they sit here rather than under GENERATED.
EVALUATION = DATA / "evaluation"

# The RAG corpus, one directory per hazard. It sits next to the planner that
# retrieves from it rather than under DATA, because the protocols and the agent
# that cites them are one thing: a protocol added without a planner change is
# invisible, and a planner change without the corpus is ungrounded.
PROTOCOLS = PACKAGE_ROOT / "response_planner" / "protocols"

# The predefined scan locations. A single committed file, read at startup.
ISRAEL_LOCATIONS = DATA / "israel_locations.json"


def generated(*parts: str) -> Path:
    """A path under GENERATED, creating parent directories on the way.

    Writers of derived artefacts want the directory to exist; readers do not
    care either way. Doing it here keeps `mkdir(parents=True, exist_ok=True)`
    out of a dozen call sites that each got it slightly differently.
    """
    path = GENERATED.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
