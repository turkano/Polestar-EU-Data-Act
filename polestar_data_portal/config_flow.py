"""Config flow for the Polestar Data Portal."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    PolestarApiError,
    PolestarAuthError,
    PolestarClient,
    PolestarForbiddenError,
)
from .catalog import (
    DAILY_CALL_BUDGET,
    DEFAULT_ENDPOINTS,
    DEFAULT_SCAN_INTERVAL_MIN,
    ENDPOINTS,
    MAX_SCAN_INTERVAL_MIN,
    MIN_SCAN_INTERVAL_MIN,
    estimate_daily_calls,
)
from .const import (
    CONF_ACCOUNT_ID,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_ENDPOINTS,
    CONF_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _user_schema(defaults: Mapping[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_CLIENT_ID, default=defaults.get(CONF_CLIENT_ID, "")): TextSelector(),
            vol.Required(CONF_CLIENT_SECRET): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
            vol.Required(CONF_ACCOUNT_ID, default=defaults.get(CONF_ACCOUNT_ID, "")): TextSelector(),
        }
    )


async def _validate(hass, data: Mapping[str, Any]) -> tuple[list[str], dict[str, str]]:
    """Validate credentials. Returns (vins, errors)."""
    client = PolestarClient(
        async_get_clientsession(hass),
        data[CONF_CLIENT_ID].strip(),
        data[CONF_CLIENT_SECRET].strip(),
        data[CONF_ACCOUNT_ID].strip(),
    )
    try:
        vins = await client.async_validate()
    except PolestarAuthError:
        return [], {"base": "invalid_auth"}
    except PolestarForbiddenError:
        return [], {"base": "no_vehicle_access"}
    except (PolestarApiError, aiohttp.ClientError, TimeoutError):
        return [], {"base": "cannot_connect"}
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Unexpected error validating Polestar Data Portal credentials")
        return [], {"base": "unknown"}
    if not vins:
        return [], {"base": "no_vehicles"}
    return vins, {}


class PolestarConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            vins, errors = await _validate(self.hass, user_input)
            if not errors:
                await self.async_set_unique_id(user_input[CONF_CLIENT_ID].strip().lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Polestar Data Portal",
                    data={
                        CONF_CLIENT_ID: user_input[CONF_CLIENT_ID].strip(),
                        CONF_CLIENT_SECRET: user_input[CONF_CLIENT_SECRET].strip(),
                        CONF_ACCOUNT_ID: user_input[CONF_ACCOUNT_ID].strip(),
                    },
                )
        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(user_input),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            data = {**entry.data, **user_input}
            _, errors = await _validate(self.hass, data)
            if not errors:
                return self.async_update_reload_and_abort(
                    entry,
                    data={
                        CONF_CLIENT_ID: data[CONF_CLIENT_ID].strip(),
                        CONF_CLIENT_SECRET: data[CONF_CLIENT_SECRET].strip(),
                        CONF_ACCOUNT_ID: data[CONF_ACCOUNT_ID].strip(),
                    },
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_user_schema(entry.data),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return PolestarOptionsFlow()


class PolestarOptionsFlow(OptionsFlow):
    """Polling interval and endpoint selection."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = self.config_entry.options
        vehicles = 1
        runtime = getattr(self.config_entry, "runtime_data", None)
        if runtime is not None and getattr(runtime, "vins", None):
            vehicles = len(runtime.vins)

        if user_input is not None:
            interval = int(user_input[CONF_SCAN_INTERVAL])
            endpoints = [e for e in user_input[CONF_ENDPOINTS] if e in ENDPOINTS]
            if not endpoints:
                errors["base"] = "no_endpoints"
            elif estimate_daily_calls(interval, vehicles, len(endpoints)) > DAILY_CALL_BUDGET:
                errors["base"] = "too_many_calls"
            else:
                return self.async_create_entry(
                    data={CONF_SCAN_INTERVAL: interval, CONF_ENDPOINTS: endpoints}
                )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=int((user_input or current).get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MIN)),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL_MIN,
                        max=MAX_SCAN_INTERVAL_MIN,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="min",
                    )
                ),
                vol.Required(
                    CONF_ENDPOINTS,
                    default=list((user_input or current).get(CONF_ENDPOINTS, DEFAULT_ENDPOINTS)),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=list(ENDPOINTS),
                        multiple=True,
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key="endpoints",
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
            description_placeholders={"vehicles": str(vehicles), "limit": str(DAILY_CALL_BUDGET)},
        )
