"""Diagnostics (redacted)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .catalog import SPECS
from .const import CONF_ACCOUNT_ID, CONF_CLIENT_ID, CONF_CLIENT_SECRET

TO_REDACT = {
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_ACCOUNT_ID,
    "vin",
    "latitude",
    "longitude",
    "locationAlias",
    "locationId",
    "coordinate",
    "id",
    "metaEventId",
}


def _redact_vin(vin: str) -> str:
    return f"...{vin[-4:]}"


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Return redacted diagnostics."""
    coordinator = entry.runtime_data
    data = coordinator.data or {}
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "vehicles": len(coordinator.vins),
        "enabled_endpoints": coordinator.endpoints,
        "api_calls_today": coordinator.client.calls_today,
        "payloads": {
            _redact_vin(vin): {ep: async_redact_data(payload, TO_REDACT) for ep, payload in eps.items()}
            for vin, eps in data.items()
        },
        "catalog_fields": len(SPECS),
    }
