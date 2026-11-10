"""Polestar Data Portal (EU Data Act) integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PolestarClient
from .const import CONF_ACCOUNT_ID, CONF_CLIENT_ID, CONF_CLIENT_SECRET
from .coordinator import PolestarCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.DEVICE_TRACKER, Platform.IMAGE]

type PolestarConfigEntry = ConfigEntry[PolestarCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: PolestarConfigEntry) -> bool:
    """Set up from a config entry."""
    client = PolestarClient(
        async_get_clientsession(hass),
        entry.data[CONF_CLIENT_ID],
        entry.data[CONF_CLIENT_SECRET],
        entry.data[CONF_ACCOUNT_ID],
    )
    coordinator = PolestarCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: PolestarConfigEntry) -> None:
    """Reload when options (interval / endpoints) change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: PolestarConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
