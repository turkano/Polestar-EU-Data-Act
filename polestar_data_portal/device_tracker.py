"""Device tracker platform (vehicle location)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .catalog import get_path, payload_timestamp, to_float
from .coordinator import PolestarCoordinator
from .entity import PolestarVehicleEntity, async_setup_discovery


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the location tracker."""
    coordinator: PolestarCoordinator = entry.runtime_data
    known: set[str] = set()

    def factory(coord: PolestarCoordinator) -> list[Any]:
        new: list[Any] = []
        for vin in coord.vins:
            payload = (coord.data or {}).get(vin, {}).get("location")
            if vin not in known and _coords(payload) != (None, None):
                known.add(vin)
                new.append(PolestarTracker(coord, vin))
        return new

    entry.async_on_unload(async_setup_discovery(coordinator, async_add_entities, factory))


def _coords(payload: dict[str, Any] | None) -> tuple[float | None, float | None]:
    if not payload:
        return None, None
    return (
        to_float(get_path(payload, "coordinate.latitude")),
        to_float(get_path(payload, "coordinate.longitude")),
    )


class PolestarTracker(PolestarVehicleEntity, TrackerEntity):
    """GPS location of the vehicle."""

    _attr_source_type = SourceType.GPS
    _attr_icon = "mdi:car-electric"

    def __init__(self, coordinator: PolestarCoordinator, vin: str) -> None:
        super().__init__(coordinator, vin, "location")

    @property
    def latitude(self) -> float | None:
        return _coords(self._payload("location"))[0]

    @property
    def longitude(self) -> float | None:
        return _coords(self._payload("location"))[1]

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        payload = self._payload("location")
        if not payload:
            return None
        attrs: dict[str, Any] = {}
        for attr, path in (("altitude", "altitude"), ("heading", "heading"), ("speed_kmh", "speed")):
            value = to_float(get_path(payload, path))
            if value is not None:
                attrs[attr] = value
        reported = payload_timestamp(payload)
        if reported:
            attrs["reported_at"] = reported.isoformat()
        return attrs or None
