"""The national air-quality monitoring network.

Roughly a thousand station-and-pollutant series, published every five minutes.
Stored as they arrive; deciding which readings are unusual is the detector's
job."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from ecoguard.collectors.base import BaseCollector
from ecoguard.shared.air_quality_schemas import AirQualityCollectionResult
from ecoguard.shared.ministry_air_quality_client import MinistryAirQualityClient

logger = logging.getLogger(__name__)


class AirPollutionCollector(BaseCollector):
    source = "air_pollution"

    def __init__(self, client=None, *, clock=None):
        """Build the collector. Client and clock are injectable for testing."""
        self.client = client if client is not None else MinistryAirQualityClient()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def fetch(self) -> list[dict[str, Any]]:
        """Every air-quality reading published since the last one stored."""
        # BaseCollector logs exception text and tracebacks. Keep unexpected
        # provider/validation exceptions (which may contain headers) private.
        try:
            result = self.client.collect_latest()
            result = AirQualityCollectionResult.model_validate(result.model_dump())
        except Exception:
            raise RuntimeError("air_pollution_collection_failed") from None
        if result.status == "failed":
            raise RuntimeError("air_pollution_collection_failed")

        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("collector clock must carry a UTC offset")
        cutoff = min(now.astimezone(timezone.utc), result.collected_at)
        records = []
        future_count = 0
        for observation in result.observations:
            # Honor the provider's explicit offset, never guess Jerusalem/DST.
            # A future reading is excluded, never shifted to make it fit.
            if observation.observed_at > cutoff:
                future_count += 1
                continue
            identity = ":".join(quote(part, safe="") for part in (
                observation.provider_station_id, observation.provider_channel_id,
                observation.pollutant, observation.unit or "__unknown_unit__",
            ))
            records.append({
                "cell_id": f"ministry:{identity}",
                "observed_at": observation.observed_at,
                "latitude": observation.location.latitude,
                "longitude": observation.location.longitude,
                "payload": {
                    **observation.model_dump(mode="json"),
                    "collected_at": result.collected_at.isoformat(),
                    "collection_status": result.status,
                },
            })
        # Do not log raw responses, error strings, tokens or station metadata.
        logger.info(
            "air_pollution: status=%s accepted=%s excluded=%s future=%s errors=%s",
            result.status, len(records), len(result.excluded), future_count,
            len(result.errors),
        )
        return records
