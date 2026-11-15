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
    COST_KEYS,
    AC_EFFICIENCY,
    CapacityLearner,
    ChargeTracker,
    MonthlyTracker,
    RangeLearner,
    Spec,
    TripTracker,
    is_charging,
    charge_end_time,
    charging_power_kw,
    derived_available,
    payload_timestamp,
    range_at_full,
)
from .const import CONF_CAPACITY, CONF_MIN_TRIP, CONF_PRICE, DEFAULT_MIN_TRIP_KM, DOMAIN
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

    price = float(entry.options.get(CONF_PRICE, 0) or 0)
    capacity = float(entry.options.get(CONF_CAPACITY, 0) or 0)
    min_trip = float(entry.options.get(CONF_MIN_TRIP, DEFAULT_MIN_TRIP_KM))

    # One recorder per vehicle: last drive, last charge session, learned range.
    coordinator.recorders = {}  # type: ignore[attr-defined]
    for vin in coordinator.vins:
        recorder = PolestarVehicleRecorder(coordinator, vin, capacity, min_trip)
        await recorder.async_load()
        coordinator.recorders[vin] = recorder  # type: ignore[attr-defined]
        entry.async_on_unload(coordinator.async_add_listener(recorder.handle_update))

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
                if spec.current(data.get(vin, {}).get(spec.endpoint)) is not None:
                    known.add(uid)
                    new.append(PolestarSensor(coord, vin, spec))
            for key in DERIVED_SENSORS:
                uid = f"{vin}_{key}"
                if uid in known or not derived_available(key, data.get(vin, {})):
                    continue
                if (key in COST_KEYS and price <= 0) or (key == "battery_soh" and capacity <= 0):
                    continue
                known.add(uid)
                if key == "odometer_month":
                    new.append(PolestarMonthlyDistanceSensor(coord, vin))
                elif key.startswith("last_trip_"):
                    new.append(PolestarLastTripSensor(coord, vin, key, price))
                elif key.startswith("last_charge_"):
                    new.append(PolestarLastChargeSensor(coord, vin, key, price))
                elif key in ("charge_capacity", "battery_soh"):
                    new.append(PolestarCapacitySensor(coord, vin, key, capacity))
                elif key == "range_learned":
                    new.append(PolestarLearnedRangeSensor(coord, vin))
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
        return self._spec.current(self._payload(self._spec.endpoint))

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


class PolestarVehicleRecorder:
    """Watches one vehicle: last drive, last charge session and learned range."""

    def __init__(self, coordinator: PolestarCoordinator, vin: str, capacity_kwh: float = 0.0, min_trip_km: float = DEFAULT_MIN_TRIP_KM
    ) -> None:
        self._coordinator = coordinator
        self._min_trip = min_trip_km
        self._vin = vin
        self._capacity = capacity_kwh or None
        self.capacity = CapacityLearner()
        self.trip = TripTracker(min_km=min_trip_km)
        self.charge = ChargeTracker()
        self.range = RangeLearner()
        self._store = Store(coordinator.hass, 1, f"{DOMAIN}.{vin}.recorder")
        self._legacy = Store(coordinator.hass, 1, f"{DOMAIN}.{vin}.last_trip")

    async def async_load(self) -> None:
        stored = await self._store.async_load()
        if not isinstance(stored, dict):
            stored = {}
            legacy = await self._legacy.async_load()  # v0.4.x stored only the last trip
            if isinstance(legacy, dict) and isinstance(legacy.get("last"), dict):
                stored["trip"] = legacy["last"]
        if isinstance(stored.get("trip"), dict):
            self.trip = TripTracker(stored["trip"], self._min_trip)
        if isinstance(stored.get("charge"), dict):
            self.charge = ChargeTracker(stored["charge"])
        if isinstance(stored.get("capacity"), dict):
            self.capacity = CapacityLearner(stored["capacity"])
        if isinstance(stored.get("range"), dict):
            self.range = RangeLearner(stored["range"])

    def _data(self) -> dict[str, Any]:
        return {"trip": self.trip.last, "charge": self.charge.last, "range": self.range.to_dict(),
                "capacity": self.capacity.to_dict()}

    @callback
    def handle_update(self) -> None:
        vehicle = (self._coordinator.data or {}).get(self._vin) or {}
        battery, odometer = vehicle.get("battery"), vehicle.get("odometer")
        now = dt_util.utcnow()
        changed = False

        energy_wh = SPECS_BY_KEY["total_energy_automatic"].extract(battery)
        breakdown = {
            cat: v
            for cat in ("driving", "climate", "battery", "other")
            if (v := SPECS_BY_KEY[f"energy_automatic_{cat}"].extract(battery)) is not None
        }
        changed |= self.trip.update(
            now,
            SPECS_BY_KEY["trip_automatic"].extract(odometer),
            SPECS_BY_KEY["consumption_automatic"].extract(battery),
            energy_wh,
            breakdown or None,
            SPECS_BY_KEY["battery_level"].extract(battery),
            self._capacity,
        )

        charging = is_charging(battery)
        power = charging_power_kw(battery)
        reported = SPECS_BY_KEY["charging_power"].extract(battery)
        if reported is not None:
            power = reported / 1000.0
        soc = SPECS_BY_KEY["battery_level"].extract(battery)
        target = SPECS_BY_KEY["target_soc"].extract(vehicle.get("target_soc"))
        if self.charge.update(now, charging, power, soc, target):
            changed = True
            self.capacity.add(self.charge.last)

        changed |= self.range.update(SPECS_BY_KEY["odometer"].extract(odometer), soc, charging)
        if changed:
            self._store.async_delay_save(self._data, 5)


def _currency(coordinator: PolestarCoordinator) -> str | None:
    return getattr(getattr(coordinator.hass, "config", None), "currency", None)


def _recorder(entity: PolestarVehicleEntity) -> PolestarVehicleRecorder | None:
    return getattr(entity.coordinator, "recorders", {}).get(entity._vin)


class PolestarLastTripSensor(PolestarVehicleEntity, SensorEntity):
    """Distance, consumption, energy (total and by category), cost or end time of the last drive."""

    def __init__(self, coordinator: PolestarCoordinator, vin: str, key: str, price: float = 0.0) -> None:
        super().__init__(coordinator, vin, key)
        self._key = key
        self._price = price
        if key == "last_trip_distance":
            self._attr_device_class = SensorDeviceClass.DISTANCE
            self._attr_native_unit_of_measurement = "km"
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_suggested_display_precision = 1
            self._attr_icon = "mdi:map-marker-path"
        elif key == "last_trip_consumption":
            self._attr_native_unit_of_measurement = "kWh/100km"
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_suggested_display_precision = 1
            self._attr_icon = "mdi:lightning-bolt"
        elif key == "last_trip_energy" or key.startswith("last_trip_energy_"):
            self._attr_device_class = SensorDeviceClass.ENERGY
            self._attr_native_unit_of_measurement = "kWh"
            self._attr_suggested_display_precision = 2 if key != "last_trip_energy" else 1
        elif key == "last_trip_cost":
            self._attr_device_class = SensorDeviceClass.MONETARY
            self._attr_native_unit_of_measurement = _currency(coordinator)
            self._attr_suggested_display_precision = 2
        else:
            self._attr_device_class = SensorDeviceClass.TIMESTAMP

    def _last(self) -> dict[str, Any] | None:
        recorder = _recorder(self)
        return recorder.trip.last if recorder else None

    @property
    def native_value(self) -> Any:
        last = self._last()
        if not last:
            return None
        key = self._key
        if key == "last_trip_distance":
            return last.get("distance_km")
        if key == "last_trip_consumption":
            return last.get("consumption")
        if key == "last_trip_energy":
            return last.get("energy_kwh")
        if key == "last_trip_cost":
            energy = last.get("energy_kwh")
            return round(energy * self._price, 2) if energy is not None else None
        if key.startswith("last_trip_energy_"):
            return (last.get("breakdown_kwh") or {}).get(key.removeprefix("last_trip_energy_"))
        return dt_util.parse_datetime(last["ended"]) if last.get("ended") else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        last = self._last()
        if not last or self._key == "last_trip_end":
            return None
        attrs: dict[str, Any] = {"started": last.get("started"), "ended": last.get("ended")}
        if self._key == "last_trip_energy":
            attrs["source"] = last.get("energy_source")
            if last.get("breakdown_kwh"):
                attrs["breakdown_kwh"] = last["breakdown_kwh"]
        if self._key == "last_trip_cost":
            attrs["price_per_kwh"] = self._price
        return attrs


class PolestarLastChargeSensor(PolestarVehicleEntity, SensorEntity):
    """Energy (estimated), duration, end time or cost of the last charging session."""

    def __init__(self, coordinator: PolestarCoordinator, vin: str, key: str, price: float = 0.0) -> None:
        super().__init__(coordinator, vin, key)
        self._key = key
        self._price = price
        if key == "last_charge_energy":
            self._attr_device_class = SensorDeviceClass.ENERGY
            self._attr_native_unit_of_measurement = "kWh"
            self._attr_suggested_display_precision = 1
        elif key == "last_charge_duration":
            self._attr_device_class = SensorDeviceClass.DURATION
            self._attr_native_unit_of_measurement = "min"
            self._attr_icon = "mdi:timer-outline"
        elif key == "last_charge_cost":
            self._attr_device_class = SensorDeviceClass.MONETARY
            self._attr_native_unit_of_measurement = _currency(coordinator)
            self._attr_suggested_display_precision = 2
        else:
            self._attr_device_class = SensorDeviceClass.TIMESTAMP

    def _last(self) -> dict[str, Any] | None:
        recorder = _recorder(self)
        return recorder.charge.last if recorder else None

    @property
    def native_value(self) -> Any:
        last = self._last()
        if not last:
            return None
        key = self._key
        if key == "last_charge_energy":
            return last.get("energy_kwh")
        if key == "last_charge_duration":
            return last.get("duration_min")
        if key == "last_charge_cost":
            energy = last.get("energy_kwh")
            return round(energy * self._price, 2) if energy is not None else None
        return dt_util.parse_datetime(last["ended"]) if last.get("ended") else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        last = self._last()
        if not last or self._key == "last_charge_end":
            return None
        attrs: dict[str, Any] = {
            "started": last.get("started"),
            "ended": last.get("ended"),
            "battery_start": last.get("soc_start"),
            "battery_end": last.get("soc_end"),
            "target": last.get("target"),
        }
        if self._key in ("last_charge_energy", "last_charge_cost"):
            attrs["note"] = "Integral of the reported charging power; energy stored in the battery, not drawn from the wall."
        if self._key == "last_charge_cost":
            attrs["price_per_kwh"] = self._price
        return attrs


class PolestarCapacitySensor(PolestarVehicleEntity, SensorEntity):
    """Battery capacity / health estimated from long AC charging sessions."""

    def __init__(self, coordinator: PolestarCoordinator, vin: str, key: str, nominal_kwh: float) -> None:
        super().__init__(coordinator, vin, key)
        self._key = key
        self._nominal = nominal_kwh
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_suggested_display_precision = 1
        if key == "charge_capacity":
            self._attr_device_class = SensorDeviceClass.ENERGY_STORAGE
            self._attr_native_unit_of_measurement = "kWh"
            self._attr_icon = "mdi:battery-heart-variant"
        else:
            self._attr_native_unit_of_measurement = "%"
            self._attr_icon = "mdi:battery-heart"

    @property
    def native_value(self) -> float | None:
        recorder = _recorder(self)
        if recorder is None:
            return None
        if self._key == "charge_capacity":
            return recorder.capacity.capacity_kwh()
        return recorder.capacity.soh(self._nominal)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        recorder = _recorder(self)
        if recorder is None:
            return None
        learner = recorder.capacity
        attrs: dict[str, Any] = {
            "samples": len(learner.samples),
            "needed": learner.MIN_SAMPLES,
            "note": "Median of the latest AC charges of at least 30 %, from the integrated charging power.",
        }
        if self._key == "battery_soh":
            attrs["nominal_capacity_kwh"] = self._nominal
            attrs["assumed_ac_efficiency"] = AC_EFFICIENCY
        return attrs


class PolestarLearnedRangeSensor(PolestarVehicleEntity, SensorEntity):
    """Range from the real km per 1 % learned while driving."""

    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_native_unit_of_measurement = "km"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    _attr_icon = "mdi:map-marker-distance"

    def __init__(self, coordinator: PolestarCoordinator, vin: str) -> None:
        super().__init__(coordinator, vin, "range_learned")

    @property
    def native_value(self) -> float | None:
        recorder = _recorder(self)
        battery = self._payload("battery")
        if recorder is None:
            return None
        return recorder.range.estimate(
            SPECS_BY_KEY["battery_level"].extract(battery), SPECS_BY_KEY["range"].extract(battery)
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        recorder = _recorder(self)
        if recorder is None:
            return None
        learner = recorder.range
        return {
            "km_per_percent": round(learner.km_per_pct, 2) if learner.km_per_pct else None,
            "samples": learner.samples,
            "car_range_km": SPECS_BY_KEY["range"].extract(self._payload("battery")),
            "note": "Until a few drives are recorded this shows the car's own estimate.",
        }


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
