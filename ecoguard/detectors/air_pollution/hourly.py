"""Pure national-v2-label-compatible live aggregation; no I/O or detection.

Input is shared observation row dictionaries (id/source/cell_id/observed_at/
ingested_at/payload). Explicit series and hour allow empty/missed-poll hours to
return insufficient_data. First_seen means earliest ingestion, then database ID;
it is NOT national-v2's last accepted duplicate timestamp-string policy.
"""
from datetime import datetime, timedelta, timezone
import math
from urllib.parse import quote

from ecoguard.shared.air_quality_schemas import LIVE_QUALITY_POLICY

PROVIDER_CLOCK = timezone(timedelta(hours=2), "Ministry winter time")
AGGREGATION_POLICY = "ecoguard-live-provider-hour-first-seen-v1"
CLOCK_POLICY = "ministry-winter-utc-plus02-national-v2-label-v1"


def _aware(value):
    """A datetime with a timezone, parsed from text if necessary."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("aware timestamp required")
    return value


def provider_clock(value):
    """Fixed +02:00, supported by Ministry documentation and winter/summer API samples."""
    return _aware(value).astimezone(PROVIDER_CLOCK)


def provider_hour_for_observation(observed_at, provider_timestamp):
    """Validate a provider timestamp and return its national-v2 hour label.

    Equality between aware datetimes establishes the same instant; the explicit
    offset check prevents a caller from silently relabelling through Jerusalem
    DST or another equivalent offset representation.
    """
    observed = _aware(observed_at).astimezone(timezone.utc)
    provider = _aware(provider_timestamp)
    if provider.utcoffset() != timedelta(hours=2) or provider != observed:
        raise ValueError("provider timestamp is incompatible with stored UTC")
    provider = provider_clock(observed)
    return provider.replace(minute=0, second=0, microsecond=0)


def aggregate_hour(observations, *, station_id, channel_id, pollutant,
                   measurement_unit, hour_start, as_of):
    """Aggregate exactly one series/provider-label hour, including empty hours.

    hour_start/as_of must be aware. No guessed offsets, snapping, interpolation,
    concentration conversions or anomaly thresholds. Only rows available as_of
    participate. Duplicates are resolved before validity/provenance filtering.
    """
    hour = provider_clock(hour_start)
    now = _aware(as_of)
    if hour.minute or hour.second or hour.microsecond:
        raise ValueError("hour_start must label an exact provider hour")
    if not all(isinstance(v, str) and v for v in (station_id, channel_id, pollutant, measurement_unit)):
        raise ValueError("explicit string series identity and actual unit required")
    end = hour + timedelta(hours=1)
    expected_cell = "ministry:" + ":".join(quote(v, safe="") for v in (station_id, channel_id, pollutant, measurement_unit))
    flags, candidates = [], []
    for row in observations:
        if not isinstance(row, dict):
            flags.append({"id": None, "reason": "malformed_row"})
            continue
        p = row.get("payload", {})
        if not isinstance(p, dict):
            flags.append({"id": row.get("id"), "reason": "malformed_payload"})
            continue
        if (p.get("provider_station_id"), p.get("provider_channel_id"), p.get("pollutant")) != (station_id, channel_id, pollutant):
            continue
        # A different known unit is a different series, not convertible here.
        if p.get("unit") is not None and p["unit"] != measurement_unit:
            continue
        try:
            observed = _aware(row["observed_at"]).astimezone(timezone.utc)
            ingested = _aware(row["ingested_at"])
            if not hour <= observed < end or ingested > now:
                continue
            if type(row.get("id")) is not int:
                raise ValueError("stored observation id required")
            candidates.append((ingested, row["id"], observed, row))
        except (ValueError, TypeError, KeyError):
            flags.append({"id": row.get("id"), "reason": "malformed_row"})
    seen, accepted = set(), []
    for ingested, row_id, observed, row in sorted(candidates, key=lambda r: (r[0], r[1])):
        p = row["payload"]
        def reject(reason):
            """Record why one row was excluded from the hour."""
            flags.append({"id": row_id, "reason": reason})
        # Unknown-unit rows occupy a DIFFERENT shared repository identity.
        # They must neither qualify nor shadow a verified-unit row's slot.
        if p.get("unit") is None:
            reject("unverified_measurement_unit")
            continue
        if row.get("source") != "air_pollution" or row.get("cell_id") != expected_cell:
            reject("identity_mismatch")
            continue
        if observed in seen:
            reject("duplicate_first_seen")
            continue
        seen.add(observed)
        local = provider_clock(observed)
        if local.minute % 5 or local.second or local.microsecond:
            reject("off_grid")
            continue
        if observed > now:
            reject("future_measurement")
            continue
        if p.get("unit_source") != "reading" or p.get("measurement_unit") != measurement_unit or not p.get("reading_unit"):
            reject("unverified_measurement_unit")
            continue
        try:
            provider = _aware(p["provider_timestamp"])
            if provider.utcoffset() != timedelta(hours=2) or provider != observed or _aware(p["observed_at"]) != observed:
                raise ValueError("clock mismatch")
        except (KeyError, TypeError, ValueError):
            reject("provider_clock_mismatch")
            continue
        value = p.get("value")
        if p.get("valid") is not True or type(value) not in (int, float) or not math.isfinite(value) or value == -9999:
            reject("invalid_measurement")
            continue
        if p.get("quality_policy") != LIVE_QUALITY_POLICY:
            reject("unverified_quality_policy")
            continue
        accepted.append({"id": row_id, "source": row["source"], "cell_id": row["cell_id"],
                         "observed_at": observed.isoformat(), "value": value,
                         "valid": p["valid"], "provider_status_id": p.get("provider_status_id"),
                         "provider_status": p.get("provider_status")})
    accepted.sort(key=lambda r: r["observed_at"])
    complete = now >= end
    status = "incomplete_hour" if not complete else "ready" if len(accepted) >= 9 else "insufficient_data"
    mean = None
    if status == "ready":
        # Scaling avoids overflowing an otherwise representable signed mean.
        try:
            mean = math.fsum(r["value"] / len(accepted) for r in accepted)
        except OverflowError:
            mean = float("inf")
        if not math.isfinite(mean):
            status = "invalid_aggregate"
            mean = None
    return {"station_id": station_id, "channel_id": channel_id, "pollutant": pollutant,
            "measurement_unit": measurement_unit, "provider_hour": hour.isoformat(),
            "month": hour.month, "hour": hour.hour, "status": status, "mean": mean,
            "sample_count": len(accepted), "expected_sample_count": 12,
            "contributing_observations": accepted, "flags": flags,
            "aggregation_policy": AGGREGATION_POLICY, "quality_policy": LIVE_QUALITY_POLICY,
            "clock_policy": CLOCK_POLICY, "duplicate_policy": "first_seen",
            "timeBeginning": False}
