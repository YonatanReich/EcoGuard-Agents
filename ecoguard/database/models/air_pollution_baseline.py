"""Compact, versioned air-pollution baselines (never raw historical readings)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger, CheckConstraint, Date, DateTime, Float, ForeignKey,
    ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ecoguard.database.models import Base


class AirPollutionStationCatalog(Base):
    __tablename__ = "air_pollution_station_catalog"
    __table_args__ = (
        CheckConstraint(
            "artifact_sha256 ~ '^[0-9a-f]{64}$'",
            name="air_pollution_station_catalog_hash_ck",
        ),
    )

    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    station_id: Mapped[str] = mapped_column(Text, primary_key=True)
    station_name: Mapped[str] = mapped_column(Text, nullable=False)
    availability: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AirPollutionBaselineProfile(Base):
    __tablename__ = "air_pollution_baseline_profiles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["provider", "station_id"],
            ["air_pollution_station_catalog.provider", "air_pollution_station_catalog.station_id"],
            name="air_pollution_baseline_profiles_station_fk",
        ),
        UniqueConstraint(
            "provider", "station_id", "channel_id", "pollutant", "canonical_unit",
            "baseline_family", name="air_pollution_baseline_profiles_identity_family",
        ),
        CheckConstraint(
            "baseline_family IN ('completed_hour','five_minute_observation')",
            name="air_pollution_baseline_profiles_family_ck",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    station_id: Mapped[str] = mapped_column(Text, nullable=False)
    channel_id: Mapped[str] = mapped_column(Text, nullable=False)
    pollutant: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_unit: Mapped[str] = mapped_column(Text, nullable=False)
    baseline_family: Mapped[str] = mapped_column(Text, nullable=False)


class AirPollutionBaselineVersion(Base):
    __tablename__ = "air_pollution_baseline_versions"
    __table_args__ = (
        UniqueConstraint("profile_id", "content_sha256", name="air_pollution_baseline_versions_content"),
        UniqueConstraint("id", "profile_id", name="air_pollution_baseline_versions_id_profile"),
        ForeignKeyConstraint(
            ["parent_version_id", "profile_id"],
            ["air_pollution_baseline_versions.id", "air_pollution_baseline_versions.profile_id"],
            name="air_pollution_baseline_versions_parent_fk", ondelete="RESTRICT",
        ),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="air_pollution_baseline_versions_hash_ck"),
        CheckConstraint("training_end >= training_start", name="air_pollution_baseline_versions_training_ck"),
        CheckConstraint(
            "coverage_status IN ('FULL_BASELINE','PARTIAL_BASELINE','INSUFFICIENT_HISTORY')",
            name="air_pollution_baseline_versions_coverage_ck",
        ),
        CheckConstraint(
            "lifecycle_status IN ('draft','active','superseded')",
            name="air_pollution_baseline_versions_lifecycle_ck",
        ),
        Index(
            "air_pollution_baseline_versions_one_active",
            "profile_id", unique=True,
            postgresql_where=text("lifecycle_status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("air_pollution_baseline_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    parent_version_id: Mapped[int | None] = mapped_column(BigInteger)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    method_version: Mapped[str | None] = mapped_column(Text)
    source_name: Mapped[str] = mapped_column(Text, nullable=False)
    source_version: Mapped[str | None] = mapped_column(Text)
    training_start: Mapped[date] = mapped_column(Date, nullable=False)
    training_end: Mapped[date] = mapped_column(Date, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    aggregation_policy_version: Mapped[str] = mapped_column(Text, nullable=False)
    quality_policy_version: Mapped[str] = mapped_column(Text, nullable=False)
    coverage_status: Mapped[str] = mapped_column(Text, nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    aggregation_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    quality_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    coverage_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class AirPollutionBaselineBucket(Base):
    __tablename__ = "air_pollution_baseline_buckets"
    __table_args__ = (
        UniqueConstraint(
            "baseline_version_id", "month", "hour",
            name="air_pollution_baseline_buckets_identity",
        ),
        CheckConstraint("month BETWEEN 1 AND 12", name="air_pollution_baseline_buckets_month_ck"),
        CheckConstraint("hour BETWEEN 0 AND 23", name="air_pollution_baseline_buckets_hour_ck"),
        CheckConstraint(
            "status IN ('ok','insufficient_history')",
            name="air_pollution_baseline_buckets_status_ck",
        ),
        CheckConstraint(
            "sample_count >= 0 AND distinct_days >= 0 AND distinct_years >= 0 "
            "AND distinct_days <= sample_count AND distinct_years <= distinct_days",
            name="air_pollution_baseline_buckets_counts_ck",
        ),
        CheckConstraint(
            "cardinality(years_present) = distinct_years",
            name="air_pollution_baseline_buckets_years_ck",
        ),
        CheckConstraint(
            "(sample_count = 0 AND mean IS NULL AND median IS NULL AND std IS NULL "
            "AND mad IS NULL AND p05 IS NULL AND p25 IS NULL AND p75 IS NULL AND p95 IS NULL) OR "
            "(sample_count > 0 AND mean IS NOT NULL AND median IS NOT NULL AND std IS NOT NULL "
            "AND mad IS NOT NULL AND p05 IS NOT NULL AND p25 IS NOT NULL AND p75 IS NOT NULL "
            "AND p95 IS NOT NULL)",
            name="air_pollution_baseline_buckets_statistics_presence_ck",
        ),
        CheckConstraint("std IS NULL OR std >= 0", name="air_pollution_baseline_buckets_std_ck"),
        CheckConstraint("mad IS NULL OR mad >= 0", name="air_pollution_baseline_buckets_mad_ck"),
        CheckConstraint(
            "p05 IS NULL OR (p05 <= p25 AND p25 <= median AND median <= p75 AND p75 <= p95)",
            name="air_pollution_baseline_buckets_quantiles_ck",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    baseline_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("air_pollution_baseline_versions.id", ondelete="RESTRICT"), nullable=False
    )
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    hour: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    distinct_days: Mapped[int] = mapped_column(Integer, nullable=False)
    distinct_years: Mapped[int] = mapped_column(Integer, nullable=False)
    years_present: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)
    mean: Mapped[float | None] = mapped_column(Float)
    median: Mapped[float | None] = mapped_column(Float)
    std: Mapped[float | None] = mapped_column(Float)
    mad: Mapped[float | None] = mapped_column(Float)
    p05: Mapped[float | None] = mapped_column(Float)
    p25: Mapped[float | None] = mapped_column(Float)
    p75: Mapped[float | None] = mapped_column(Float)
    p95: Mapped[float | None] = mapped_column(Float)
