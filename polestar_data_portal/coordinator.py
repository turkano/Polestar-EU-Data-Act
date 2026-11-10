"""Data update coordinator for the Polestar Data Portal."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    PolestarApiError,
    PolestarAuthError,
    PolestarClient,
    PolestarForbiddenError,
    PolestarNotAvailableError,
    PolestarRateLimitError,
)
from .catalog import DEFAULT_ENDPOINTS, DEFAULT_SCAN_INTERVAL_MIN, ENDPOINTS, unmapped_fields
from .const import (
    CONF_ENDPOINTS,
    CONF_SCAN_INTERVAL,
    DOMAIN,
    MAX_CONCURRENCY,
    UNAVAILABLE_RETRY_SECONDS,
    VEHICLE_REFRESH_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

# {vin: {endpoint_key: payload}}
PolestarData = dict[str, dict[str, dict[str, Any]]]


class PolestarCoordinator(DataUpdateCoordinator[PolestarData]):
    """Polls the enabled endpoints for every accessible vehicle."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: PolestarClient) -> None:
        interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MIN))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=interval),
        )
        self.client = client
        self.endpoints: list[str] = [
            k for k in entry.options.get(CONF_ENDPOINTS, DEFAULT_ENDPOINTS) if k in ENDPOINTS
        ]
        self.client.set_endpoints(self.endpoints)
        self.vins: list[str] = []
        self._vins_checked = 0.0
        # (vin, endpoint) -> monotonic time until which the endpoint is skipped
        self._skip_until: dict[tuple[str, str], float] = {}
        self._logged_skips: set[tuple[str, str]] = set()

    def unmapped(self) -> list[str]:
        """Fields the vehicles report that no entity reads yet ("endpoint.path")."""
        found: set[str] = set()
        for endpoints in (self.data or {}).values():
            for endpoint, payload in endpoints.items():
                found.update(f"{endpoint}.{path}" for path in unmapped_fields(endpoint, payload))
        return sorted(found)

    async def _async_refresh_vehicles(self) -> None:
        now = time.monotonic()
        if self.vins and now - self._vins_checked < VEHICLE_REFRESH_SECONDS:
            return
        try:
            self.vins = await self.client.async_get_vehicles()
        except PolestarAuthError as err:
            raise ConfigEntryAuthFailed("Invalid Polestar Data Portal credentials") from err
        except PolestarForbiddenError as err:
            raise UpdateFailed(f"Not authorised to list vehicles ({err.code})") from err
        except PolestarApiError as err:
            if self.vins:  # keep the previous list on transient errors
                return
            raise UpdateFailed(f"Cannot list vehicles: {err}") from err
        self._vins_checked = now

    def _mark_skipped(self, vin: str, endpoint: str, reason: str) -> None:
        self._skip_until[(vin, endpoint)] = time.monotonic() + UNAVAILABLE_RETRY_SECONDS
        if (vin, endpoint) not in self._logged_skips:
            self._logged_skips.add((vin, endpoint))
            _LOGGER.info(
                "Endpoint %s is not available for ...%s (%s); will retry in %d h",
                endpoint,
                vin[-4:],
                reason,
                UNAVAILABLE_RETRY_SECONDS // 3600,
            )

    async def _async_update_data(self) -> PolestarData:
        await self._async_refresh_vehicles()

        previous = self.data or {}
        result: PolestarData = {vin: dict(previous.get(vin, {})) for vin in self.vins}
        semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
        now = time.monotonic()
        stats = {"ok": 0, "failed": 0, "attempted": 0}

        async def fetch(vin: str, endpoint: str) -> None:
            if self._skip_until.get((vin, endpoint), 0) > now:
                return
            async with semaphore:
                stats["attempted"] += 1
                try:
                    payload = await self.client.async_get_endpoint(vin, endpoint)
                except PolestarAuthError as err:
                    raise ConfigEntryAuthFailed("Invalid Polestar Data Portal credentials") from err
                except PolestarNotAvailableError:
                    result[vin].pop(endpoint, None)
                    self._mark_skipped(vin, endpoint, "no data for this vehicle")
                except PolestarForbiddenError as err:
                    result[vin].pop(endpoint, None)
                    self._mark_skipped(vin, endpoint, f"forbidden: {err.code}")
                except (PolestarRateLimitError, PolestarApiError) as err:
                    stats["failed"] += 1
                    _LOGGER.debug("Fetching %s for ...%s failed: %s", endpoint, vin[-4:], err)
                else:
                    stats["ok"] += 1
                    result[vin][endpoint] = payload
                    self._logged_skips.discard((vin, endpoint))

        await asyncio.gather(*(fetch(vin, ep) for vin in self.vins for ep in self.endpoints))

        if stats["attempted"] and stats["ok"] == 0 and stats["failed"] == stats["attempted"]:
            raise UpdateFailed("The Polestar Data Portal did not answer any request")
        return result
