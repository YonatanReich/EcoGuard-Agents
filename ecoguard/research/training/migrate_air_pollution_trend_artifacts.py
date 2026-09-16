"""One-time migration of legacy ``__main__`` Trend ML joblib bundles.

This command never reads observations or fits a model.  Its only compatibility
scope is the legacy unpickling step; all written artifacts use stable shared
contract classes.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import pickle
import shutil
import subprocess
import sys
import tempfile
from dataclasses import fields
from pathlib import Path
from typing import Any, Iterator

import joblib
import numpy as np
from scipy import sparse

from ecoguard.paths import GENERATED
from ecoguard.shared.air_pollution_trend_model import (
    FinalSGDModelBundle as StableFinalSGDModelBundle,
    IdentityVocabulary as StableIdentityVocabulary,
)
from ecoguard.shared.air_pollution_trend_policy import (
    TREND_ARTIFACT_FILENAMES,
    UNAVAILABLE_TREND_POLLUTANTS,
)

DEFAULT_ARTIFACT_DIRECTORY = GENERATED / "ml" / "air_pollution_trend" / "final"
MIGRATION_VERSION = "air-pollution-trend-joblib-portability-v1"


class ArtifactMigrationError(RuntimeError):
    """The legacy artifacts cannot be migrated without changing model state."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _pickle_state_sha256(value: Any) -> str:
    return hashlib.sha256(pickle.dumps(value, protocol=5)).hexdigest()


def _assert_exact(left: Any, right: Any, path: str = "state") -> None:
    if type(left) is not type(right):
        raise ArtifactMigrationError(f"{path} type changed")
    if isinstance(left, np.ndarray):
        if left.dtype != right.dtype or left.shape != right.shape or not np.array_equal(
            left, right, equal_nan=True
        ):
            raise ArtifactMigrationError(f"{path} array changed")
        return
    if sparse.issparse(left):
        if left.getformat() != right.getformat() or left.shape != right.shape:
            raise ArtifactMigrationError(f"{path} sparse shape/format changed")
        _assert_exact(left.data, right.data, f"{path}.data")
        _assert_exact(left.indices, right.indices, f"{path}.indices")
        _assert_exact(left.indptr, right.indptr, f"{path}.indptr")
        return
    if isinstance(left, dict):
        if left.keys() != right.keys():
            raise ArtifactMigrationError(f"{path} keys changed")
        for key in left:
            _assert_exact(left[key], right[key], f"{path}.{key}")
        return
    if isinstance(left, (tuple, list)):
        if len(left) != len(right):
            raise ArtifactMigrationError(f"{path} length changed")
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            _assert_exact(left_item, right_item, f"{path}[{index}]")
        return
    if hasattr(left, "__dict__"):
        _assert_exact(left.__dict__, right.__dict__, f"{path}.__dict__")
        return
    if type(left).__module__ == "_loss" and not hasattr(type(left), "__slots__"):
        # scikit-learn recreates this stateless Cython loss helper when an SGD
        # estimator is unpickled.  Its concrete type, rather than object
        # identity, is the complete observable serialization contract.
        return
    if isinstance(left, float) and np.isnan(left) and np.isnan(right):
        return
    if left != right:
        raise ArtifactMigrationError(f"{path} changed")


def _assert_bundle_exact(
    before: StableFinalSGDModelBundle,
    after: StableFinalSGDModelBundle,
) -> None:
    for field in fields(StableFinalSGDModelBundle):
        _assert_exact(
            getattr(before, field.name),
            getattr(after, field.name),
            field.name,
        )


@contextlib.contextmanager
def _legacy_main_contracts() -> Iterator[None]:
    """Expose exactly the two known legacy globals during legacy loading only."""

    main = sys.modules["__main__"]
    missing = object()
    previous = {
        "FinalSGDModelBundle": getattr(main, "FinalSGDModelBundle", missing),
        "IdentityVocabulary": getattr(main, "IdentityVocabulary", missing),
    }
    main.FinalSGDModelBundle = StableFinalSGDModelBundle
    main.IdentityVocabulary = StableIdentityVocabulary
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is missing:
                delattr(main, name)
            else:
                setattr(main, name, value)


def _fresh_process_load(path: Path) -> dict[str, str]:
    code = (
        "import joblib,sys; "
        "value=joblib.load(sys.argv[1]); "
        "print(value.__class__.__module__+'|'+value.__class__.__name__+'|'+value.pollutant)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code, str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise ArtifactMigrationError(
            f"fresh-process load failed for {path.name}: {completed.stderr.strip()}"
        )
    module, class_name, pollutant = completed.stdout.strip().split("|")
    if (
        module != "ecoguard.shared.air_pollution_trend_model"
        or class_name != "FinalSGDModelBundle"
    ):
        raise ArtifactMigrationError(f"unexpected portable type for {path.name}")
    return {"module": module, "class": class_name, "pollutant": pollutant}


def migrate(artifact_directory: Path) -> dict[str, Any]:
    directory = artifact_directory.resolve()
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("outer_2024_accessed") is not False
        or manifest.get("2025_accessed") is not False
        or manifest.get("unavailable_pollutants")
        != dict(UNAVAILABLE_TREND_POLLUTANTS)
        or set(manifest.get("models", {})) != set(TREND_ARTIFACT_FILENAMES)
    ):
        raise ArtifactMigrationError("manifest safety contract is not migratable")
    if "serialization_migration" in manifest:
        raise ArtifactMigrationError("manifest records an existing serialization migration")

    originals: dict[str, Path] = {}
    old_checksums: dict[str, str] = {}
    for pollutant, filename in TREND_ARTIFACT_FILENAMES.items():
        record = manifest["models"][pollutant]
        if record.get("path") != filename:
            raise ArtifactMigrationError(f"unexpected path for {pollutant}")
        path = directory / filename
        checksum = _sha256(path)
        if checksum != record.get("sha256"):
            raise ArtifactMigrationError(f"pre-migration checksum mismatch for {pollutant}")
        if b"__main__" not in path.read_bytes():
            raise ArtifactMigrationError(f"{pollutant} is not a legacy __main__ artifact")
        originals[pollutant] = path
        old_checksums[pollutant] = checksum

    with tempfile.TemporaryDirectory(prefix=".trend-portability-", dir=directory) as raw:
        staging = Path(raw)
        backups = staging / "backups"
        backups.mkdir()
        staged_paths: dict[str, Path] = {}
        verification: dict[str, Any] = {}

        for pollutant, source in originals.items():
            shutil.copy2(source, backups / source.name)
            with _legacy_main_contracts():
                bundle = joblib.load(source)
            if not isinstance(bundle, StableFinalSGDModelBundle):
                raise ArtifactMigrationError(f"unexpected legacy bundle for {pollutant}")
            if bundle.pollutant != pollutant:
                raise ArtifactMigrationError(f"pollutant mismatch for {pollutant}")
            if not isinstance(bundle.identity_vocabulary, StableIdentityVocabulary):
                raise ArtifactMigrationError(
                    f"unexpected legacy identity vocabulary for {pollutant}"
                )

            scaler_state = _pickle_state_sha256(bundle.scaler)
            classifier_state = _pickle_state_sha256(bundle.classifier)
            target = staging / source.name
            joblib.dump(bundle, target)
            portable = joblib.load(target)
            if not isinstance(portable, StableFinalSGDModelBundle):
                raise ArtifactMigrationError(f"portable reload failed for {pollutant}")
            _assert_bundle_exact(bundle, portable)
            if (
                scaler_state != _pickle_state_sha256(portable.scaler)
                or classifier_state != _pickle_state_sha256(portable.classifier)
            ):
                raise ArtifactMigrationError(f"trained state digest changed for {pollutant}")
            staged_paths[pollutant] = target
            verification[pollutant] = {
                "source_sha256": old_checksums[pollutant],
                "portable_sha256": _sha256(target),
                "scaler_state_sha256": scaler_state,
                "classifier_state_sha256": classifier_state,
                "exact_value_comparison": "passed",
            }

        shutil.copy2(manifest_path, backups / manifest_path.name)
        for pollutant, record in verification.items():
            manifest["models"][pollutant]["sha256"] = record["portable_sha256"]
        manifest["serialization_migration"] = {
            "version": MIGRATION_VERSION,
            "legacy_globals": [
                "__main__.FinalSGDModelBundle",
                "__main__.IdentityVocabulary",
            ],
            "stable_module": "ecoguard.shared.air_pollution_trend_model",
            "retrained": False,
            "training_metadata_preserved": True,
            "safety_flags_preserved": {
                "outer_2024_accessed": manifest["outer_2024_accessed"],
                "2025_accessed": manifest["2025_accessed"],
            },
            "models": verification,
        }
        staged_manifest = staging / "manifest.json"
        staged_manifest.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        replaced: list[Path] = []
        try:
            for pollutant, target in staged_paths.items():
                destination = originals[pollutant]
                os.replace(target, destination)
                replaced.append(destination)
            os.replace(staged_manifest, manifest_path)
            replaced.append(manifest_path)
            fresh = {
                pollutant: _fresh_process_load(path)
                for pollutant, path in originals.items()
            }
        except Exception:
            for destination in reversed(replaced):
                backup = backups / destination.name
                if backup.exists():
                    os.replace(backup, destination)
            raise

    return {
        "migration_version": MIGRATION_VERSION,
        "retrained": False,
        "artifact_directory": str(directory),
        "models": verification,
        "fresh_process_loads": fresh,
        "outer_2024_accessed": manifest["outer_2024_accessed"],
        "2025_accessed": manifest["2025_accessed"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact-directory",
        type=Path,
        default=DEFAULT_ARTIFACT_DIRECTORY,
    )
    parser.add_argument(
        "--confirm-one-time-migration",
        action="store_true",
        help="Required guard; this rewrites only the four existing joblib bundles.",
    )
    args = parser.parse_args()
    if not args.confirm_one_time_migration:
        parser.error("--confirm-one-time-migration is required")
    print(json.dumps(migrate(args.artifact_directory), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
