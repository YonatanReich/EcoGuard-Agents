"""Exact baseline lookup policy above the read-only database repository."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any, cast

from pydantic import ValidationError

from ecoguard.detectors.air_pollution.baseline_schemas import (
    BaselineBucketStatistics, BaselineIdentity, BaselineLookupRequest,
    BaselineLookupResult,
    BaselineVersionProvenance,
)

Reader = Callable[..., list[dict[str, Any]]]
BatchReader = Callable[..., list[dict[str, Any]]]


def _default_reader(**kwargs):
    """Read one baseline row, importing the database layer only when needed."""
    # Lazy import keeps schema/service unit tests and non-DB callers independent
    # of DATABASE_URL. This function itself remains SELECT-only.
    from ecoguard.database.repositories.air_pollution_baseline_lookup import (
        read_exact_baseline_candidates,
    )
    return read_exact_baseline_candidates(**kwargs)


def _default_batch_reader(**kwargs):
    """Read many baseline rows in one query."""
    # As above, delay DB configuration until a real lookup is executed.
    from ecoguard.database.repositories.air_pollution_baseline_lookup import (
        read_exact_baseline_candidates_batch,
    )
    return read_exact_baseline_candidates_batch(**kwargs)


def _catalog_evidence(rows: list[dict[str, Any]], pollutant: str):
    """The station's name, location and unit for this pollutant."""
    if not rows:
        return None, None, None
    station_name = rows[0].get("station_name")
    availability = rows[0].get("catalog_availability")
    if isinstance(availability, list):
        for item in availability:
            if isinstance(item, dict) and item.get("pollutant") == pollutant:
                return station_name, item.get("status"), item.get("reason")
    return station_name, None, None


def _version(row: dict[str, Any]) -> BaselineVersionProvenance:
    """Which published baseline version a row came from."""
    fields = (
        "baseline_version_id", "parent_version_id", "content_sha256",
        "coverage_status", "lifecycle_status", "schema_version", "method_version",
        "source_name", "source_version", "training_start", "training_end",
        "imported_at", "generated_at", "aggregation_policy_version",
        "quality_policy_version", "source_metadata", "aggregation_metadata",
        "quality_metadata", "coverage_metadata",
    )
    return BaselineVersionProvenance.model_validate({field: row.get(field) for field in fields})


def _bucket(row: dict[str, Any]) -> BaselineBucketStatistics:
    """One month-and-hour bucket's statistics, including its p95."""
    return BaselineBucketStatistics(
        status=row["bucket_status"], sample_count=row["sample_count"],
        distinct_days=row["distinct_days"], distinct_years=row["distinct_years"],
        years_present=row["years_present"], mean=row["mean"], median=row["median"],
        std=row["std"], mad=row["mad"], p05=row["p05"], p25=row["p25"],
        p75=row["p75"], p95=row["p95"],
    )


class AirPollutionBaselineLookupService:
    def __init__(
        self,
        reader: Reader = _default_reader,
        batch_reader: BatchReader = _default_batch_reader,
    ):
        """Build a lookup service. Readers are injectable so tests need no database."""
        self.reader = reader
        self.batch_reader = batch_reader

    def lookup(self, identity: BaselineIdentity | Mapping[str, Any], *, month: int, hour: int):
        """Operational lookup: active versions only, without an override flag."""
        return self._lookup(identity, month=month, hour=hour, mode="operational",
                            lifecycle_status="active", baseline_version_id=None)

    def lookup_draft_for_validation(
        self, identity: BaselineIdentity | Mapping[str, Any], *, month: int, hour: int,
        baseline_version_id: int | None = None,
    ):
        """Explicit non-operational draft inspection; ambiguous drafts fail closed."""
        return self._lookup(identity, month=month, hour=hour, mode="draft_validation",
                            lifecycle_status="draft", baseline_version_id=baseline_version_id)

    def lookup_batch(
        self, requests: Iterable[BaselineLookupRequest | Mapping[str, Any]],
    ) -> list[BaselineLookupResult]:
        """Operational active-only lookup with one result per ordered request."""
        return self._lookup_batch(
            requests, mode="operational", lifecycle_status="active",
            allow_version_id=False,
        )

    def lookup_draft_batch_for_validation(
        self, requests: Iterable[BaselineLookupRequest | Mapping[str, Any]],
    ) -> list[BaselineLookupResult]:
        """Explicit draft-only batch validation; never used operationally."""
        return self._lookup_batch(
            requests, mode="draft_validation", lifecycle_status="draft",
            allow_version_id=True,
        )

    def _lookup(self, identity, *, month, hour, mode, lifecycle_status, baseline_version_id):
        """Find the baseline for one reading's station, month and hour."""
        try:
            exact = BaselineIdentity.model_validate(identity)
            if type(month) is not int or not 1 <= month <= 12:
                raise ValueError("invalid month")
            if type(hour) is not int or not 0 <= hour <= 23:
                raise ValueError("invalid hour")
            if baseline_version_id is not None and (
                type(baseline_version_id) is not int or baseline_version_id <= 0
            ):
                raise ValueError("invalid baseline version id")
        except (ValidationError, ValueError, TypeError):
            return BaselineLookupResult(
                status="invalid_identity", reason="identity_or_bucket_invalid",
                mode=mode, identity=None,
            )

        rows = self.reader(
            **exact.model_dump(), month=month, hour=hour,
            lifecycle_status=lifecycle_status,
            baseline_version_id=baseline_version_id,
        )
        return self._result_from_rows(
            exact=exact, month=month, hour=hour, mode=mode, rows=rows,
            baseline_version_id=baseline_version_id,
        )

    def _lookup_batch(
        self, requests, *, mode, lifecycle_status, allow_version_id,
    ) -> list[BaselineLookupResult]:
        """Find baselines for many readings in one query."""
        supplied = list(requests)
        results: list[BaselineLookupResult | None] = [None] * len(supplied)
        valid: list[tuple[int, BaselineLookupRequest]] = []
        repository_requests: list[dict[str, Any]] = []

        for request_index, item in enumerate(supplied):
            try:
                request = BaselineLookupRequest.model_validate(item)
                if not allow_version_id and request.baseline_version_id is not None:
                    raise ValueError("operational lookup cannot pin a version")
            except (ValidationError, ValueError, TypeError):
                results[request_index] = BaselineLookupResult(
                    status="invalid_identity", reason="identity_or_bucket_invalid",
                    mode=mode, identity=None,
                )
                continue
            valid.append((request_index, request))
            repository_requests.append({
                "request_index": request_index,
                **request.identity.model_dump(),
                "month": request.month,
                "hour": request.hour,
                "baseline_version_id": request.baseline_version_id,
            })

        rows_by_index: dict[int, list[dict[str, Any]]] = {
            index: [] for index, _ in valid
        }
        if repository_requests:
            for row in self.batch_reader(
                requests=repository_requests,
                lifecycle_status=lifecycle_status,
            ):
                request_index = row.get("request_index")
                if request_index in rows_by_index:
                    rows_by_index[request_index].append(row)

        for request_index, request in valid:
            results[request_index] = self._result_from_rows(
                exact=request.identity,
                month=request.month,
                hour=request.hour,
                mode=mode,
                rows=rows_by_index[request_index],
                baseline_version_id=request.baseline_version_id,
            )
        if any(result is None for result in results):
            raise RuntimeError("baseline batch did not preserve every request")
        return cast(list[BaselineLookupResult], results)

    @staticmethod
    def _result_from_rows(
        *, exact, month, hour, mode, rows, baseline_version_id,
    ) -> BaselineLookupResult:
        """Turn returned rows into a result, or say why there is none."""
        # A VALUES-driven outer join emits one all-null catalog row for an
        # uncataloged station. Normalize it to the single-lookup empty-row
        # semantics before interpreting the result.
        if rows and "catalog_station_id" in rows[0] and all(
            row.get("catalog_station_id") is None for row in rows
        ):
            rows = []
        station_name, catalog_status, catalog_reason = _catalog_evidence(rows, exact.pollutant)
        # Catalog coverage was generated from completed-hour artifacts. Never
        # present it as evidence about a different baseline family.
        if exact.baseline_family != "completed_hour":
            catalog_status = catalog_reason = None
        common = dict(mode=mode, identity=exact, month=month, hour=hour,
                      station_name=station_name, catalog_status=catalog_status,
                      catalog_reason=catalog_reason)
        if not rows:
            return BaselineLookupResult(
                status="profile_unavailable", reason="station_not_cataloged", **common,
            )
        profile_rows = [row for row in rows if row.get("profile_id") is not None]
        if not profile_rows:
            reason = "exact_profile_not_found"
            if catalog_status in {"NOT_MEASURED", "EXCLUDED_MOBILE_OR_INACTIVE", "INSUFFICIENT_HISTORY"}:
                reason = "catalog_status:" + catalog_status
            return BaselineLookupResult(status="profile_unavailable", reason=reason, **common)
        version_rows = [row for row in profile_rows if row.get("baseline_version_id") is not None]
        if not version_rows:
            reason = ("no_active_version" if mode == "operational" else
                      "draft_version_not_found" if baseline_version_id else "no_draft_version")
            return BaselineLookupResult(status="baseline_unavailable", reason=reason, **common)
        version_ids = {row["baseline_version_id"] for row in version_rows}
        if len(version_ids) != 1:
            reason = "multiple_active_versions" if mode == "operational" else "ambiguous_draft_versions"
            return BaselineLookupResult(status="baseline_unavailable", reason=reason, **common)
        row = version_rows[0]
        provenance = _version(row)
        if row.get("bucket_id") is None:
            return BaselineLookupResult(
                status="bucket_unavailable", reason="exact_month_hour_bucket_not_found",
                version=provenance, **common,
            )
        bucket = _bucket(row)
        if bucket.status == "insufficient_history":
            return BaselineLookupResult(
                status="insufficient_history", reason="exact_bucket_insufficient_history",
                version=provenance, bucket=bucket, **common,
            )
        return BaselineLookupResult(
            status="available", reason="exact_baseline_available",
            version=provenance, bucket=bucket, **common,
        )
