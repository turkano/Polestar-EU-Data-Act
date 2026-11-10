"""Binary sensor platform."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .catalog import SPECS, Spec
from .coordinator import PolestarCoordinator
from .entity import PolestarSpecEntity, async_setup_discovery

_RAW_KINDS = {"opening", "unlocked"}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up binary sensors."""
    coordinator: PolestarCoordinator = entry.runtime_data
    known: set[str] = set()

    def factory(coord: PolestarCoordinator) -> list[Any]:
        new: list[Any] = []
        data = coord.data or {}
        for vin in coord.vins:
            for spec in SPECS:
                if spec.platform != "binary_sensor":
                    continue
                uid = f"{vin}_{spec.key}"
                if uid in known:
                    continue
                payload = data.get(vin, {}).get(spec.endpoint)
                # Create the entity as soon as the vehicle reports the field, even
                # if the raw string isn't recognised yet: the state stays unknown
                # and the raw value is visible in the ``raw_state`` attribute.
                if spec.raw(payload) is not None:
                    known.add(uid)
                    new.append(PolestarBinarySensor(coord, vin, spec))
        return new

    entry.async_on_unload(async_setup_discovery(coordinator, async_add_entities, factory))


class PolestarBinarySensor(PolestarSpecEntity, BinarySensorEntity):
    """A binary sensor backed by one API field."""

    def __init__(self, coordinator: PolestarCoordinator, vin: str, spec: Spec) -> None:
        super().__init__(coordinator, vin, spec)
        if spec.device_class:
            self._attr_device_class = BinarySensorDeviceClass(spec.device_class)

    @property
    def is_on(self) -> bool | None:
        return self._spec.extract(self._payload(self._spec.endpoint))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attrs = dict(super().extra_state_attributes or {})
        if self._spec.kind in _RAW_KINDS:
            raw = self._spec.raw(self._payload(self._spec.endpoint))
            if raw is not None:
                attrs["raw_state"] = raw
        return attrs or None
