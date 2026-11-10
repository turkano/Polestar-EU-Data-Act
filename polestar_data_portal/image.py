"""Image platform: a top-down picture of the car with open doors, windows ...

The image is generated locally as an SVG from the ``exterior`` data; nothing
is downloaded. Show it with a picture-entity / picture card, e.g.::

    type: picture-entity
    entity: image.<your_vehicle>_vehicle_status
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .car_image import IMAGE_KEYS, exterior_states, open_parts, render_svg
from .coordinator import PolestarCoordinator
from .entity import PolestarVehicleEntity, async_setup_discovery


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up one status picture per vehicle that reports exterior data."""
    coordinator: PolestarCoordinator = entry.runtime_data
    known: set[str] = set()

    def factory(coord: PolestarCoordinator) -> list[Any]:
        new: list[Any] = []
        for vin in coord.vins:
            exterior = ((coord.data or {}).get(vin) or {}).get("exterior")
            if vin in known or not exterior:
                continue
            if any(v is not None for v in exterior_states(exterior).values()):
                known.add(vin)
                new.append(PolestarStatusImage(coord, vin))
        return new

    entry.async_on_unload(async_setup_discovery(coordinator, async_add_entities, factory))


class PolestarStatusImage(PolestarVehicleEntity, ImageEntity):
    """SVG showing which doors, windows, hood, tailgate ... are open."""

    _attr_content_type = "image/svg+xml"
    _attr_icon = "mdi:car-side"

    def __init__(self, coordinator: PolestarCoordinator, vin: str) -> None:
        PolestarVehicleEntity.__init__(self, coordinator, vin, "status")
        ImageEntity.__init__(self, coordinator.hass)
        self._svg = ""
        self._open: list[str] = []

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._refresh()
        self.async_write_ha_state()

    def _refresh(self) -> None:
        states = exterior_states(self._payload("exterior"))
        svg = render_svg(states)
        self._open = open_parts(states)
        if svg != self._svg:
            self._svg = svg
            # A new timestamp makes the frontend reload the picture.
            self._attr_image_last_updated = dt_util.utcnow()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._refresh()
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        if not self._svg:
            self._refresh()
        return self._svg.encode("utf-8") if self._svg else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return {"open_parts": list(self._open), "open_count": len(self._open)}


assert IMAGE_KEYS
