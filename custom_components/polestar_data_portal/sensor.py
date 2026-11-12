"""Sensor platform."""

from __future__ import annotations

from datetime import date, datetime
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
from homeassistant.core import callback
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .catalog import (
    ACCOUNT_ENTITIES,
    DERIVED_SENSORS,
    SPECS,
    SPECS_BY_KEY,
    VEHICLE_LAST_UPDATE,
    MonthlyTracker,
    Spec,
    charge_end_time,
    charging_power_kw,
    derived_available,
    payload_timestamp,
    range_at_full,
)
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
            for key in DERIVED_SENSORS:
                uid = f"{vin}_{key}"
                if uid in known or not derived_available(key, data.get(vin, {})):
                    continue
                known.add(uid)
                if key == "odometer_month":
                    new.append(PolestarMonthlyDistanceSensor(coord, vin))
                else:
                    new.append(PolestarDerivedSensor(coord, vin, key))
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
        if self._spec.kind in ("enum", "warning"):
            attrs["raw_state"] = self._spec.raw(self._payload(self._spec.endpoint))
        if self._spec.kind == "count":
            raw = self._spec.raw(self._payload(self._spec.endpoint))
            # Only simple values: never expose lists of objects (e.g. coordinates).
            if isinstance(raw, dict):
                attrs["values"] = {k: v for k, v in raw.items() if isinstance(v, (str, int, float, bool))}
            elif isinstance(raw, list) and all(isinstance(i, str) for i in raw):
                attrs["items"] = raw
        return attrs or None


class PolestarDerivedSensor(PolestarVehicleEntity, SensorEntity):
    """Value calculated from several API fields (range at 100 %, charge end)."""

    def __init__(self, coordinator: PolestarCoordinator, vin: str, key: str) -> None:
        super().__init__(coordinator, vin, key)
        self._key = key
        if key == "charging_power_calc":
            self._attr_device_class = SensorDeviceClass.POWER
            self._attr_native_unit_of_measurement = "kW"
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_suggested_display_precision = 2
            self._attr_icon = "mdi:ev-station"
        elif key == "range_at_full":
            self._attr_device_class = SensorDeviceClass.DISTANCE
            self._attr_native_unit_of_measurement = "km"
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_suggested_display_precision = 0
            self._attr_icon = "mdi:battery-high"
        else:  # charge_end_time
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
            self._attr_icon = "mdi:battery-clock"

    def _battery(self) -> dict[str, Any] | None:
        return self._payload("battery")

    @property
    def native_value(self) -> Any:
        if self._key == "charging_power_calc":
            return charging_power_kw(self._battery())
        if self._key == "range_at_full":
            return range_at_full(self._battery())
        return charge_end_time(self._battery(), dt_util.utcnow())

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        battery = self._battery()
        if self._key == "charging_power_calc":
            reported = SPECS_BY_KEY["charging_power"].extract(battery)
            return {
                "voltage_v": SPECS_BY_KEY["charging_voltage"].extract(battery),
                "current_a": SPECS_BY_KEY["charging_current"].extract(battery),
                "reported_power_w": reported,
                "note": "Voltage x current. For three-phase AC this can read lower than the real power.",
            }
        if self._key == "range_at_full":
            return {
                "battery_level": SPECS_BY_KEY["battery_level"].extract(battery),
                "current_range_km": SPECS_BY_KEY["range"].extract(battery),
                "note": "Linear extrapolation of the current range to 100 %.",
            }
        minutes = SPECS_BY_KEY["time_to_full"].extract(battery)
        return {"minutes_remaining": minutes} if minutes is not None else None


class PolestarMonthlyDistanceSensor(PolestarVehicleEntity, SensorEntity):
    """Kilometres driven in the current calendar month (persisted baseline)."""

    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_native_unit_of_measurement = "km"
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:calendar-month"

    def __init__(self, coordinator: PolestarCoordinator, vin: str) -> None:
        super().__init__(coordinator, vin, "odometer_month")
        self._tracker = MonthlyTracker()
        self._value: float | None = None
        self._store = Store(coordinator.hass, 1, f"{DOMAIN}.{vin}.monthly_distance")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        stored = await self._store.async_load()
        if isinstance(stored, dict):
            self._tracker = MonthlyTracker.from_dict(stored)
        self._refresh()
        self.async_write_ha_state()

    def _refresh(self) -> None:
        odometer = SPECS_BY_KEY["odometer"].extract(self._payload("odometer"))
        if odometer is None:
            return
        now = dt_util.now()
        self._value = self._tracker.update(odometer, now.strftime("%Y-%m"), now.date().isoformat())
        self._store.async_delay_save(self._tracker.to_dict, 60)

    @callback
    def _handle_coordinator_update(self) -> None:
        self._refresh()
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> float | None:
        return self._value

    @property
    def last_reset(self) -> datetime | None:
        month = self._tracker.month
        if not month:
            return None
        year, mon = (int(part) for part in month.split("-"))
        return dt_util.start_of_local_day(date(year, mon, 1))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        t = self._tracker
        attrs: dict[str, Any] = {"tracking_since": t.tracking_since, "month": t.month}
        if t.previous_month_km is not None:
            attrs["previous_month"] = t.previous_month
            attrs["previous_month_km"] = t.previous_month_km
        return attrs


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
