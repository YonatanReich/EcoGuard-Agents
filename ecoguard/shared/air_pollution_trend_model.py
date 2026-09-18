"""Stable serialized contracts for Air Pollution Trend ML artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
from scipy import sparse
from sklearn.linear_model import SGDClassifier
from sklearn.preprocessing import StandardScaler

from ecoguard.shared.air_pollution_history import AirPollutionSeriesIdentity
from ecoguard.shared.air_pollution_trend_policy import (
    TREND_PREPROCESSING_VERSION,
)


@dataclass(frozen=True)
class IdentityVocabulary:
    """Training-only non-ordinal station/channel/series vocabulary."""

    station_ids: tuple[str, ...]
    channel_ids: tuple[str, ...]
    series_ids: tuple[tuple[str, str], ...]
    version: str = TREND_PREPROCESSING_VERSION

    @classmethod
    def fit(cls, identities: Iterable[AirPollutionSeriesIdentity]) -> "IdentityVocabulary":
        items = tuple(sorted(set(identities)))
        if not items:
            raise ValueError("identity vocabulary requires training identities")
        return cls(
            station_ids=tuple(sorted({item.station_id for item in items})),
            channel_ids=tuple(sorted({item.channel_id for item in items})),
            series_ids=tuple(
                sorted({(item.station_id, item.channel_id) for item in items})
            ),
        )

    @property
    def sparse_width(self) -> int:
        return len(self.station_ids) + len(self.channel_ids) + len(self.series_ids) + 3

    @property
    def feature_names(self) -> tuple[str, ...]:
        return (
            *(f"station={value}" for value in self.station_ids),
            "station=<UNKNOWN>",
            *(f"channel={value}" for value in self.channel_ids),
            "channel=<UNKNOWN>",
            *(f"series={station}:{channel}" for station, channel in self.series_ids),
            "series=<UNKNOWN>",
        )

    def _indexes(self, identity: AirPollutionSeriesIdentity) -> tuple[int, int, int]:
        stations = {value: index for index, value in enumerate(self.station_ids)}
        channels = {value: index for index, value in enumerate(self.channel_ids)}
        series = {value: index for index, value in enumerate(self.series_ids)}
        station = stations.get(identity.station_id, len(self.station_ids))
        channel_offset = len(self.station_ids) + 1
        channel = channel_offset + channels.get(
            identity.channel_id, len(self.channel_ids)
        )
        series_offset = channel_offset + len(self.channel_ids) + 1
        pair = (identity.station_id, identity.channel_id)
        series_index = series_offset + series.get(pair, len(self.series_ids))
        return station, channel, series_index

    def sparse_one_hot(
        self, identity: AirPollutionSeriesIdentity, rows: int
    ) -> sparse.csr_matrix:
        indexes = self._indexes(identity)
        row = np.repeat(np.arange(rows, dtype=np.int64), 3)
        column = np.tile(np.asarray(indexes, dtype=np.int64), rows)
        data = np.ones(rows * 3, dtype=np.float64)
        return sparse.csr_matrix(
            (data, (row, column)), shape=(rows, self.sparse_width)
        )

    def categorical_codes(
        self, identity: AirPollutionSeriesIdentity, rows: int
    ) -> np.ndarray:
        """Dense categorical codes for HistGB; unknown categories are missing."""

        stations = {value: index for index, value in enumerate(self.station_ids)}
        channels = {value: index for index, value in enumerate(self.channel_ids)}
        series = {value: index for index, value in enumerate(self.series_ids)}
        values = (
            stations.get(identity.station_id),
            channels.get(identity.channel_id),
            series.get((identity.station_id, identity.channel_id)),
        )
        codes = np.asarray([np.nan if value is None else value for value in values])
        return np.repeat(codes[np.newaxis, :], rows, axis=0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "station_categories": len(self.station_ids),
            "channel_categories": len(self.channel_ids),
            "series_categories": len(self.series_ids),
            "fit_scope": "inner training 2021-2022 only",
            "sgd_unseen_behavior": "dedicated UNKNOWN one-hot feature",
            "histgb_unseen_behavior": "missing categorical value",
            "non_ordinal": True,
        }


@dataclass
class FinalSGDModelBundle:
    """Complete stable preprocessing and classifier state for one pollutant."""

    artifact_version: str
    model_version: str
    pollutant: str
    training_start: str
    training_end: str
    feature_policy_version: str
    preprocessing_version: str
    epsilon_policy: dict[str, Any]
    configuration: dict[str, Any]
    feature_columns: tuple[str, ...]
    labels: tuple[str, ...]
    scaler: StandardScaler
    identity_vocabulary: IdentityVocabulary
    classifier: SGDClassifier

    def transform(
        self,
        values: np.ndarray,
        identity: AirPollutionSeriesIdentity,
    ) -> sparse.csr_matrix:
        numeric = self.scaler.transform(values)
        numeric = np.nan_to_num(numeric, nan=0.0, posinf=0.0, neginf=0.0)
        return sparse.hstack(
            (
                sparse.csr_matrix(numeric),
                self.identity_vocabulary.sparse_one_hot(identity, len(numeric)),
            ),
            format="csr",
        )

    def predict_proba(
        self,
        values: np.ndarray,
        identity: AirPollutionSeriesIdentity,
    ) -> np.ndarray:
        if identity.pollutant != self.pollutant:
            raise ValueError("model bundle pollutant identity mismatch")
        return self.classifier.predict_proba(self.transform(values, identity))
