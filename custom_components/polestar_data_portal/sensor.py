"""Sensor platform."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .catalog import ACCOUNT_ENTITIES, SPECS, VEHICLE_LAST_UPDATE, Spec, payload_timestamp
from .const import DOMAIN
from .coordinator import PolestarCoordinator
from .entity import (
    PolestarSpecEntity,
    PolestarVehicleEntity,
    async_setup_discovery,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up sensors."""
    coordinator: PolestarCoordinator = entry.runtime_data
    known: set[str] = set()

    # Account-level diagnostics
    async_add_entities(
        [
            PolestarAccountSensor(coordinator, entry, "api_calls_today"),
            PolestarAccountSensor(coordinator, entry, "vehicle_count"),
            PolestarAccountSensor(coordinator, entry, "unmapped_fields"),
        ]
    )

    def factory(coord: PolestarCoordinator) -> list[Any]:
        new: list[Any] = []
        data = coord.data or {}
        for vin in coord.vins:
            uid = f"{vin}_last_update"
            if uid not in known and any(data.get(vin, {}).values()):
                known.add(uid)
                new.append(PolestarLastUpdateSensor(coord, vin))
            for spec in SPECS:
                if spec.platform != "sensor":
                    continue
                uid = f"{vin}_{spec.key}"
                if uid in known:
                    continue
                if spec.extract(data.get(vin, {}).get(spec.endpoint)) is not None:
                    known.add(uid)
                    new.append(PolestarSensor(coord, vin, spec))
        return new

    entry.async_on_unload(async_setup_discovery(coordinator, async_add_entities, factory))


class PolestarSensor(PolestarSpecEntity, SensorEntity):
    """A sensor backed by one API field."""

    def __init__(self, coordinator: PolestarCoordinator, vin: str, spec: Spec) -> None:
        super().__init__(coordinator, vin, spec)
        if spec.device_class:
            self._attr_device_class = SensorDeviceClass(spec.device_class)
        if spec.state_class:
            self._attr_state_class = SensorStateClass(spec.state_class)
        if spec.unit and spec.kind != "ts":
            self._attr_native_unit_of_measurement = spec.unit
        if spec.precision is not None:
            self._attr_suggested_display_precision = spec.precision

    @property
    def native_value(self) -> Any:
        return self._spec.extract(self._payload(self._spec.endpoint))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attrs = dict(super().extra_state_attributes or {})
        if self._spec.kind == "count":
            raw = self._spec.raw(self._payload(self._spec.endpoint))
            # Only simple values: never expose lists of objects (e.g. coordinates).
            if isinstance(raw, dict):
                attrs["values"] = {k: v for k, v in raw.items() if isinstance(v, (str, int, float, bool))}
            elif isinstance(raw, list) and all(isinstance(i, str) for i in raw):
                attrs["items"] = raw
        return attrs or None


class PolestarLastUpdateSensor(PolestarVehicleEntity, SensorEntity):
    """Newest data timestamp reported by any endpoint of this vehicle."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: PolestarCoordinator, vin: str) -> None:
        super().__init__(coordinator, vin, VEHICLE_LAST_UPDATE[0])

    @property
    def native_value(self) -> datetime | None:
        payloads = ((self.coordinator.data or {}).get(self._vin) or {}).values()
        stamps = [t for t in (payload_timestamp(p) for p in payloads) if t]
        return max(stamps) if stamps else None


class PolestarAccountSensor(CoordinatorEntity[PolestarCoordinator], SensorEntity):
    """Account-level diagnostics (API call budget, vehicle count)."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: PolestarCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer="Polestar",
            name="Polestar Data Portal",
        )
        if key == "api_calls_today":
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_icon = "mdi:counter"
        elif key == "unmapped_fields":
            self._attr_icon = "mdi:magnify-scan"

    @property
    def native_value(self) -> int:
        if self._key == "api_calls_today":
            return self.coordinator.client.calls_today
        if self._key == "unmapped_fields":
            return len(self.coordinator.unmapped())
        return len(self.coordinator.vins)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self._key == "api_calls_today":
            return {"daily_limit": 10000}
        if self._key == "unmapped_fields":
            return {"fields": self.coordinator.unmapped()}
        return None


assert set(ACCOUNT_ENTITIES) == {"api_calls_today", "vehicle_count", "unmapped_fields"}
