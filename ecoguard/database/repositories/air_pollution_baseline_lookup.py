"""Exact, read-only baseline lookup query. No fallback or lifecycle mutation."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    BigInteger,
    Integer,
    String,
    and_,
    cast,
    column,
    or_,
    select,
    values,
)

from ecoguard.database.engine import Session
from ecoguard.database.models import (
    AirPollutionBaselineBucket,
    AirPollutionBaselineProfile,
    AirPollutionBaselineVersion,
    AirPollutionStationCatalog,
)

ALLOWED_LOOKUP_LIFECYCLES = frozenset({"active", "draft"})
BATCH_CHUNK_SIZE = 1000


def _result_columns():
    """The columns a baseline lookup returns."""
    return (
        AirPollutionStationCatalog.station_id.label("catalog_station_id"),
        AirPollutionStationCatalog.station_name.label("station_name"),
        AirPollutionStationCatalog.availability.label("catalog_availability"),
        AirPollutionBaselineProfile.id.label("profile_id"),
        AirPollutionBaselineVersion.id.label("baseline_version_id"),
        AirPollutionBaselineVersion.parent_version_id,
        AirPollutionBaselineVersion.content_sha256,
        AirPollutionBaselineVersion.schema_version,
        AirPollutionBaselineVersion.method_version,
        AirPollutionBaselineVersion.source_name,
        AirPollutionBaselineVersion.source_version,
        AirPollutionBaselineVersion.training_start,
        AirPollutionBaselineVersion.training_end,
        AirPollutionBaselineVersion.imported_at,
        AirPollutionBaselineVersion.generated_at,
        AirPollutionBaselineVersion.aggregation_policy_version,
        AirPollutionBaselineVersion.quality_policy_version,
        AirPollutionBaselineVersion.coverage_status,
        AirPollutionBaselineVersion.lifecycle_status,
        AirPollutionBaselineVersion.source_metadata,
        AirPollutionBaselineVersion.aggregation_metadata,
        AirPollutionBaselineVersion.quality_metadata,
        AirPollutionBaselineVersion.coverage_metadata,
        AirPollutionBaselineBucket.id.label("bucket_id"),
        AirPollutionBaselineBucket.status.label("bucket_status"),
        AirPollutionBaselineBucket.sample_count,
        AirPollutionBaselineBucket.distinct_days,
        AirPollutionBaselineBucket.distinct_years,
        AirPollutionBaselineBucket.years_present,
        AirPollutionBaselineBucket.mean,
        AirPollutionBaselineBucket.median,
        AirPollutionBaselineBucket.std,
        AirPollutionBaselineBucket.mad,
        AirPollutionBaselineBucket.p05,
        AirPollutionBaselineBucket.p25,
        AirPollutionBaselineBucket.p75,
        AirPollutionBaselineBucket.p95,
    )


def exact_baseline_statement(
    *,
    provider: str,
    station_id: str,
    channel_id: str,
    pollutant: str,
    canonical_unit: str,
    baseline_family: str,
    month: int,
    hour: int,
    lifecycle_status: str = "active",
    baseline_version_id: int | None = None,
):
    """Build one exact catalog/profile/version/bucket query.

    Starting at the catalog preserves its explicit availability evidence even
    when the exact profile does not exist. All identity predicates are in the
    profile JOIN: none is relaxed or retried.
    """
    if lifecycle_status not in ALLOWED_LOOKUP_LIFECYCLES:
        raise ValueError("lookup lifecycle must be active or draft")

    version_join = [
        AirPollutionBaselineVersion.profile_id == AirPollutionBaselineProfile.id,
        AirPollutionBaselineVersion.lifecycle_status == lifecycle_status,
    ]

    if baseline_version_id is not None:
        version_join.append(
            AirPollutionBaselineVersion.id == baseline_version_id
        )

    return (
        select(*_result_columns())
        .select_from(AirPollutionStationCatalog)
        .outerjoin(
            AirPollutionBaselineProfile,
            and_(
                AirPollutionBaselineProfile.provider
                == AirPollutionStationCatalog.provider,
                AirPollutionBaselineProfile.station_id
                == AirPollutionStationCatalog.station_id,
                AirPollutionBaselineProfile.channel_id == channel_id,
                AirPollutionBaselineProfile.pollutant == pollutant,
                AirPollutionBaselineProfile.canonical_unit == canonical_unit,
                AirPollutionBaselineProfile.baseline_family == baseline_family,
            ),
        )
        .outerjoin(
            AirPollutionBaselineVersion,
            and_(*version_join),
        )
        .outerjoin(
            AirPollutionBaselineBucket,
            and_(
                AirPollutionBaselineBucket.baseline_version_id
                == AirPollutionBaselineVersion.id,
                AirPollutionBaselineBucket.month == month,
                AirPollutionBaselineBucket.hour == hour,
            ),
        )
        .where(
            AirPollutionStationCatalog.provider == provider,
            AirPollutionStationCatalog.station_id == station_id,
        )
        .order_by(AirPollutionBaselineVersion.id)
    )


def read_exact_baseline_candidates(**kwargs: Any) -> list[dict[str, Any]]:
    """Execute the exact SELECT in a short session; performs no writes."""
    statement = exact_baseline_statement(**kwargs)

    with Session() as session:
        return [
            dict(row)
            for row in session.execute(statement).mappings().all()
        ]


def batch_exact_baseline_statement(
    requests: list[dict[str, Any]],
    *,
    lifecycle_status: str,
):
    """Build one set-based exact lookup for an ordered request chunk."""

    if lifecycle_status not in ALLOWED_LOOKUP_LIFECYCLES:
        raise ValueError("lookup lifecycle must be active or draft")

    if not requests:
        raise ValueError("batch requests must not be empty")

    requested = (
        values(
            column("request_index", Integer),
            column("provider", String),
            column("station_id", String),
            column("channel_id", String),
            column("pollutant", String),
            column("canonical_unit", String),
            column("baseline_family", String),
            column("month", Integer),
            column("hour", Integer),
            # All entries are commonly NULL during unpinned draft validation.
            # Keep this as BIGINT to match AirPollutionBaselineVersion.id.
            column("baseline_version_id", BigInteger),
            name="requested_air_pollution_baselines",
        )
        .data(
            [
                (
                    item["request_index"],
                    item["provider"],
                    item["station_id"],
                    item["channel_id"],
                    item["pollutant"],
                    item["canonical_unit"],
                    item["baseline_family"],
                    item["month"],
                    item["hour"],
                    item.get("baseline_version_id"),
                )
                for item in requests
            ]
        )
    )

    return (
        select(
            requested.c.request_index,
            *_result_columns(),
        )
        .select_from(requested)
        .outerjoin(
            AirPollutionStationCatalog,
            and_(
                AirPollutionStationCatalog.provider
                == requested.c.provider,
                AirPollutionStationCatalog.station_id
                == requested.c.station_id,
            ),
        )
        .outerjoin(
            AirPollutionBaselineProfile,
            and_(
                AirPollutionBaselineProfile.provider
                == requested.c.provider,
                AirPollutionBaselineProfile.station_id
                == requested.c.station_id,
                AirPollutionBaselineProfile.channel_id
                == requested.c.channel_id,
                AirPollutionBaselineProfile.pollutant
                == requested.c.pollutant,
                AirPollutionBaselineProfile.canonical_unit
                == requested.c.canonical_unit,
                AirPollutionBaselineProfile.baseline_family
                == requested.c.baseline_family,
            ),
        )
        .outerjoin(
            AirPollutionBaselineVersion,
            and_(
                AirPollutionBaselineVersion.profile_id
                == AirPollutionBaselineProfile.id,
                AirPollutionBaselineVersion.lifecycle_status
                == lifecycle_status,
                or_(
                    requested.c.baseline_version_id.is_(None),
                    AirPollutionBaselineVersion.id
                    == cast(
                        requested.c.baseline_version_id,
                        BigInteger,
                    ),
                ),
            ),
        )
        .outerjoin(
            AirPollutionBaselineBucket,
            and_(
                AirPollutionBaselineBucket.baseline_version_id
                == AirPollutionBaselineVersion.id,
                AirPollutionBaselineBucket.month
                == requested.c.month,
                AirPollutionBaselineBucket.hour
                == requested.c.hour,
            ),
        )
        .order_by(
            requested.c.request_index,
            AirPollutionBaselineVersion.id,
        )
    )


def read_exact_baseline_candidates_batch(
    *,
    requests: list[dict[str, Any]],
    lifecycle_status: str,
    chunk_size: int = BATCH_CHUNK_SIZE,
) -> list[dict[str, Any]]:
    """Resolve a batch in one session and one SELECT per conservative chunk."""

    if not requests:
        return []

    if type(chunk_size) is not int or chunk_size < 1:
        raise ValueError("chunk_size must be a positive integer")

    rows: list[dict[str, Any]] = []

    with Session() as session:
        for start in range(0, len(requests), chunk_size):
            statement = batch_exact_baseline_statement(
                requests[start : start + chunk_size],
                lifecycle_status=lifecycle_status,
            )

            rows.extend(
                dict(row)
                for row in session.execute(statement).mappings().all()
            )

    return rows