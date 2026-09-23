"""Credential-safe HTTP client for IMS station observations.

The client only retrieves provider payloads. Station/channel interpretation,
timestamp correction, unit normalization, and evidence selection live in
``ims_wind_evidence_service`` so they can be tested without network access.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests


IMS_API_ROOT = "https://api.ims.gov.il/v1/envista"
IMS_TOKEN_ENVIRONMENT_VARIABLE = "IMS_API_TOKEN"
DEFAULT_TIMEOUT_SECONDS = 30.0


class IMSWindObservationError(RuntimeError):
    """A deliberately credential-free IMS request failure."""

    def __init__(self, category: str, *, transient: bool):
        """Build the client, or carry the category of a failure."""
        super().__init__(category)
        self.category = category
        self.transient = transient


@dataclass(frozen=True)
class IMSHTTPDiagnostic:
    """Sanitized response metadata for opt-in live troubleshooting."""

    operation: str
    request_url: str
    status_code: int | None = None
    final_url: str | None = None
    redirect_statuses: tuple[int, ...] = ()
    redirect_urls: tuple[str, ...] = ()
    content_type: str | None = None
    body_byte_length: int | None = None
    json_decoded: bool = False
    json_type: str | None = None
    top_level_keys: tuple[str, ...] = ()
    list_length: int | None = None
    first_item_type: str | None = None
    error_category: str | None = None

    def as_safe_dict(self) -> dict[str, object]:
        """The failure as plain fields, with nothing credential-bearing in it."""
        return asdict(self)


def _validated_station_id(station_id: object) -> str:
    """A station id as text, rejecting anything that is not one."""
    if isinstance(station_id, bool):
        raise ValueError("station_id must be a positive integer")
    value = str(station_id).strip()
    if not value.isdecimal() or int(value) <= 0:
        raise ValueError("station_id must be a positive integer")
    return value


class IMSWindObservationClient:
    """Small injectable client for the read-only IMS Observation API."""

    def __init__(
        self,
        *,
        api_token: str | None = None,
        session: Any | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        diagnostic_callback: Callable[[IMSHTTPDiagnostic], None] | None = None,
    ) -> None:
        """Build the client. Transport and the provider key are injectable for testing."""
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(float(timeout))
            or float(timeout) <= 0
        ):
            raise ValueError("timeout must be a positive finite number")
        token = api_token if api_token is not None else os.getenv(
            IMS_TOKEN_ENVIRONMENT_VARIABLE
        )
        if token is None or not token.strip():
            raise IMSWindObservationError("missing_api_token", transient=False)
        self._api_token = token.strip()
        self.session = session or requests.Session()
        self.timeout = float(timeout)
        self.diagnostic_callback = diagnostic_callback

    def _headers(self) -> dict[str, str]:
        """The request headers, including the provider key."""
        return {
            "Accept": "application/json",
            "Authorization": f"ApiToken {self._api_token}",
            "User-Agent": "EcoGuard-Agents ims-wind-adapter/1.0",
        }

    @staticmethod
    def _raise_for_status(response: Any) -> None:
        """Turn an error response into a typed failure with no secrets in it."""
        status = int(getattr(response, "status_code", 0))
        if 200 <= status < 300:
            return
        if status in {401, 403}:
            raise IMSWindObservationError("authentication_failed", transient=False)
        if status == 404:
            raise IMSWindObservationError("not_found", transient=False)
        raise IMSWindObservationError(
            "provider_http_error",
            transient=status == 429 or status >= 500,
        )

    @staticmethod
    def _body_byte_length(response: Any) -> int | None:
        """How large the response body was, when that is knowable."""
        content = getattr(response, "content", None)
        if isinstance(content, bytes):
            return len(content)
        if isinstance(content, str):
            return len(content.encode("utf-8", errors="replace"))
        return None

    @staticmethod
    def _response_json(response: Any, *, body_byte_length: int | None) -> Any:
        """The response as JSON, failing clearly when it is not."""
        if body_byte_length == 0:
            raise IMSWindObservationError("empty_response", transient=False)
        try:
            payload = response.json()
        except (TypeError, ValueError):
            raise IMSWindObservationError("invalid_json", transient=False) from None
        if not isinstance(payload, (dict, list)):
            raise IMSWindObservationError(
                "unsupported_response_shape", transient=False
            )
        return payload

    def _safe_url(self, value: object | None) -> str | None:
        """A URL with any credentials stripped, safe to log."""
        if value is None:
            return None
        sanitized = str(value).replace(self._api_token, "<redacted>")
        try:
            parts = urlsplit(sanitized)
            query = []
            for key, item_value in parse_qsl(parts.query, keep_blank_values=True):
                if any(marker in key.casefold() for marker in ("token", "auth", "key")):
                    item_value = "<redacted>"
                query.append((key, item_value))
            return urlunsplit(
                (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
            )
        except ValueError:
            return "<invalid-url>"

    def _safe_text(self, value: object | None) -> str | None:
        """Text trimmed and bounded, safe to log."""
        if value is None:
            return None
        return str(value).replace(self._api_token, "<redacted>")

    def _request_url(
        self, endpoint: str, params: Mapping[str, str] | None
    ) -> str:
        """The full URL for one provider endpoint."""
        prepared = requests.Request(
            "GET",
            f"{IMS_API_ROOT}/{endpoint}",
            params=dict(params or {}),
        ).prepare()
        return self._safe_url(prepared.url) or f"{IMS_API_ROOT}/{endpoint}"

    def _emit_diagnostic(self, diagnostic: IMSHTTPDiagnostic) -> None:
        """Record what one request did, without recording the key."""
        if self.diagnostic_callback is not None:
            self.diagnostic_callback(diagnostic)

    def _json_shape(self, payload: object) -> dict[str, object]:
        """A description of a payload's structure, for diagnosing odd responses."""
        if isinstance(payload, dict):
            return {
                "json_type": "dict",
                "top_level_keys": tuple(
                    sorted(self._safe_text(key) or "" for key in payload.keys())
                ),
            }
        assert isinstance(payload, list)
        return {
            "json_type": "list",
            "list_length": len(payload),
            "first_item_type": type(payload[0]).__name__ if payload else None,
        }

    def _get_json(
        self,
        endpoint: str,
        *,
        params: Mapping[str, str] | None = None,
        operation: str,
    ) -> Any:
        """Make one request and return its JSON, or raise a typed failure."""
        request_url = self._request_url(endpoint, params)
        try:
            response = self.session.get(
                f"{IMS_API_ROOT}/{endpoint}",
                params=dict(params or {}),
                headers=self._headers(),
                timeout=self.timeout,
                allow_redirects=True,
            )
            status_code = int(getattr(response, "status_code", 0))
            final_url = self._safe_url(getattr(response, "url", None)) or request_url
            history = tuple(getattr(response, "history", ()) or ())
            redirect_statuses = tuple(
                int(getattr(item, "status_code", 0)) for item in history
            )
            redirect_urls = tuple(
                self._safe_url(getattr(item, "url", None)) or "<unknown>"
                for item in history
            )
            headers = getattr(response, "headers", {}) or {}
            content_type = (
                headers.get("Content-Type")
                if isinstance(headers, Mapping)
                else None
            )
            body_length = self._body_byte_length(response)
            diagnostic_fields: dict[str, object] = {
                "operation": operation,
                "request_url": request_url,
                "status_code": status_code,
                "final_url": final_url,
                "redirect_statuses": redirect_statuses,
                "redirect_urls": redirect_urls,
                "content_type": self._safe_text(content_type),
                "body_byte_length": body_length,
            }
            try:
                self._raise_for_status(response)
                payload = self._response_json(
                    response, body_byte_length=body_length
                )
            except IMSWindObservationError as error:
                self._emit_diagnostic(
                    IMSHTTPDiagnostic(
                        **diagnostic_fields,
                        error_category=error.category,
                    )
                )
                raise
            self._emit_diagnostic(
                IMSHTTPDiagnostic(
                    **diagnostic_fields,
                    json_decoded=True,
                    **self._json_shape(payload),
                )
            )
            return payload
        except requests.Timeout:
            self._emit_diagnostic(
                IMSHTTPDiagnostic(
                    operation=operation,
                    request_url=request_url,
                    error_category="timeout",
                )
            )
            raise IMSWindObservationError("timeout", transient=True) from None
        except requests.RequestException:
            self._emit_diagnostic(
                IMSHTTPDiagnostic(
                    operation=operation,
                    request_url=request_url,
                    error_category="network_error",
                )
            )
            raise IMSWindObservationError("network_error", transient=True) from None

    def get_stations(self) -> Any:
        """Every weather station the provider lists."""
        return self._get_json("stations", operation="stations")

    def get_station(self, station_id: object) -> Any:
        """One station's description."""
        validated = _validated_station_id(station_id)
        return self._get_json(
            f"stations/{validated}", operation=f"station_metadata:{validated}"
        )

    def get_station_data_latest(self, station_id: object) -> Any:
        """One station's most recent readings."""
        validated = _validated_station_id(station_id)
        return self._get_json(
            f"stations/{validated}/data/latest",
            operation=f"station_latest:{validated}",
        )

    def get_station_data_daily(self, station_id: object, day: date) -> Any:
        """One station's readings for a given day."""
        if not isinstance(day, date):
            raise TypeError("day must be a date")
        validated = _validated_station_id(station_id)
        return self._get_json(
            "stations/"
            f"{validated}/data/daily/{day:%Y/%m/%d}",
            operation=f"station_daily:{validated}:{day.isoformat()}",
        )

    def get_station_data_range(
        self,
        station_id: object,
        start_date: date,
        end_date: date,
    ) -> Any:
        """One station's readings between two times."""
        if not isinstance(start_date, date) or not isinstance(end_date, date):
            raise TypeError("start_date and end_date must be dates")
        if end_date < start_date:
            raise ValueError("end_date cannot precede start_date")
        validated = _validated_station_id(station_id)
        return self._get_json(
            f"stations/{validated}/data",
            params={
                "from": start_date.strftime("%Y/%m/%d"),
                "to": end_date.strftime("%Y/%m/%d"),
            },
            operation=(
                f"station_range:{validated}:"
                f"{start_date.isoformat()}:{end_date.isoformat()}"
            ),
        )

    @staticmethod
    def station_data_reference(station_id: object) -> str:
        """Return a credential-free provenance URL for a station data resource."""

        return (
            f"{IMS_API_ROOT}/stations/{_validated_station_id(station_id)}/data"
        )
