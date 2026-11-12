"""Async client for the Polestar Data Portal M2M API.

No Home Assistant imports here, so it can be tested on its own.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import aiohttp

from .catalog import ENDPOINTS, TOKEN_URL, VEHICLES_URL, BASE_URL

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)
TOKEN_REFRESH_MARGIN = 120  # seconds before expiry to refresh


class PolestarApiError(Exception):
    """Generic API error (retryable: 5xx and unexpected responses)."""

    def __init__(self, message: str, status: int | None = None, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class PolestarConnectionError(PolestarApiError):
    """Network problem or timeout."""


class PolestarAuthError(PolestarApiError):
    """Invalid client credentials (401) or rejected token request."""


class PolestarForbiddenError(PolestarApiError):
    """403: missing scope, VIN not authorised, or market not eligible."""


class PolestarNotAvailableError(PolestarApiError):
    """404: the vehicle has no data for this domain (model-specific)."""


class PolestarRateLimitError(PolestarApiError):
    """429: too many requests."""


def _error_code(body: Any) -> str | None:
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            return err.get("code")
        if isinstance(err, str):
            return err
    return None


async def _read_json(resp: aiohttp.ClientResponse) -> Any:
    try:
        return await resp.json(content_type=None)
    except (ValueError, aiohttp.ClientError):
        return {}


class PolestarClient:
    """Client using the OAuth2 client-credentials grant."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        client_id: str,
        client_secret: str,
        account_id: str,
    ) -> None:
        self._session = session
        self._client_id = client_id
        self._client_secret = client_secret
        self._account_id = account_id
        self._token: str | None = None
        self._token_expiry = 0.0
        self._token_scopes: frozenset[str] = frozenset()
        self._wanted_scopes: frozenset[str] = frozenset()
        self._lock = asyncio.Lock()
        self.calls_today = 0
        self._calls_day = None

    # -- bookkeeping --------------------------------------------------------

    def _count_call(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self._calls_day:
            self._calls_day = today
            self.calls_today = 0
        self.calls_today += 1

    def set_endpoints(self, endpoint_keys: list[str]) -> None:
        """Set which endpoints are used, so the token requests the right scopes."""
        self._wanted_scopes = frozenset(ENDPOINTS[k].scope for k in endpoint_keys if k in ENDPOINTS)

    # -- token --------------------------------------------------------------

    async def _request_token(self, scopes: frozenset[str]) -> tuple[int, Any]:
        body: dict[str, Any] = {"clientId": self._client_id, "clientSecret": self._client_secret}
        if scopes:
            body["scope"] = " ".join(sorted(scopes))
        self._count_call()
        try:
            async with self._session.post(TOKEN_URL, json=body, timeout=REQUEST_TIMEOUT) as resp:
                return resp.status, await _read_json(resp)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise PolestarConnectionError(f"Cannot reach token endpoint: {err}") from err

    async def async_get_token(self, force: bool = False) -> str:
        """Return a valid access token, refreshing it when needed."""
        async with self._lock:
            fresh = (
                self._token
                and time.monotonic() < self._token_expiry - TOKEN_REFRESH_MARGIN
                and self._token_scopes == self._wanted_scopes
            )
            if fresh and not force:
                return self._token  # type: ignore[return-value]

            scopes = self._wanted_scopes
            status, body = await self._request_token(scopes)
            if status == 400 and scopes:
                # Some credentials may not allow explicit scopes: retry without.
                _LOGGER.debug("Token request with scopes rejected (%s); retrying without scopes", _error_code(body))
                scopes = frozenset()
                status, body = await self._request_token(scopes)

            if status in (400, 401):
                raise PolestarAuthError("Invalid client credentials", status, _error_code(body))
            if status != 200 or not isinstance(body, dict) or "accessToken" not in body:
                raise PolestarApiError(f"Token request failed (HTTP {status})", status, _error_code(body))

            self._token = body["accessToken"]
            expires_in = body.get("expiresIn")
            try:
                ttl = float(expires_in)
            except (TypeError, ValueError):
                ttl = 3600.0
            self._token_expiry = time.monotonic() + ttl
            self._token_scopes = self._wanted_scopes
            return self._token

    # -- requests -----------------------------------------------------------

    async def _get(self, url: str, retry_auth: bool = True) -> Any:
        token = await self.async_get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "x-client-id": self._account_id,
            "Accept": "application/json",
        }
        self._count_call()
        try:
            async with self._session.get(url, headers=headers, timeout=REQUEST_TIMEOUT) as resp:
                status = resp.status
                body = await _read_json(resp)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise PolestarConnectionError(f"Cannot reach the data portal: {err}") from err

        if status == 200:
            return body
        code = _error_code(body)
        if status == 401:
            if retry_auth:
                await self.async_get_token(force=True)
                return await self._get(url, retry_auth=False)
            raise PolestarAuthError("Access token rejected", status, code)
        if status == 403:
            raise PolestarForbiddenError("Forbidden", status, code)
        if status == 404:
            raise PolestarNotAvailableError("No data for this endpoint", status, code)
        if status == 429:
            raise PolestarRateLimitError("Rate limited", status, code)
        raise PolestarApiError(f"HTTP {status}", status, code)

    async def async_get_vehicles(self) -> list[str]:
        """Return the VINs this credential can access."""
        body = await self._get(VEHICLES_URL)
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list):
            raise PolestarApiError("Unexpected vehicle list response")
        return [str(v).upper() for v in data]

    async def async_get_endpoint(self, vin: str, endpoint_key: str) -> dict[str, Any]:
        """Fetch one endpoint for one VIN and return its ``data`` object."""
        endpoint = ENDPOINTS[endpoint_key]
        url = f"{BASE_URL}/v1/vehicles/{quote(vin, safe='')}/{endpoint.path}"
        body = await self._get(url)
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            raise PolestarApiError("Unexpected endpoint response")
        return data

    async def async_validate(self) -> list[str]:
        """Check credentials and return the accessible VINs (used by the config flow)."""
        return await self.async_get_vehicles()
