"""Base entity and helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .catalog import Spec, payload_timestamp
from .const import DOMAIN
from .coordinator import PolestarCoordinator


def vehicle_device_info(vin: str) -> DeviceInfo:
    """Device info for one vehicle."""
    return DeviceInfo(
        identifiers={(DOMAIN, vin)},
        manufacturer="Polestar",
        name=f"Polestar ...{vin[-6:]}",
        serial_number=vin,
    )


class PolestarVehicleEntity(CoordinatorEntity[PolestarCoordinator]):
    """Entity tied to one vehicle."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PolestarCoordinator, vin: str, key: str) -> None:
        super().__init__(coordinator)
        self._vin = vin
        self._attr_unique_id = f"{vin}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = vehicle_device_info(vin)

    def _payload(self, endpoint: str) -> dict[str, Any] | None:
        return ((self.coordinator.data or {}).get(self._vin) or {}).get(endpoint)


class PolestarSpecEntity(PolestarVehicleEntity):
    """Entity driven by a catalog Spec."""

    def __init__(self, coordinator: PolestarCoordinator, vin: str, spec: Spec) -> None:
        super().__init__(coordinator, vin, spec.key)
        self._spec = spec
        if spec.category == "diagnostic":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_entity_registry_enabled_default = spec.enabled
        if spec.icon:
            self._attr_icon = spec.icon

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        payload = self._payload(self._spec.endpoint)
        reported = payload_timestamp(payload)
        return {"reported_at": reported.isoformat()} if reported else None


def async_setup_discovery(
    coordinator: PolestarCoordinator,
    async_add_entities: AddEntitiesCallback,
    factory: Callable[[PolestarCoordinator], list[Any]],
) -> Callable[[], None]:
    """Add entities as soon as the data for them shows up.

    ``factory`` returns candidate entities not yet added; the integration only
    creates an entity once the vehicle actually reports its field, so a model
    without e.g. a sunroof does not get a permanently unknown sensor.
    """

    def _discover() -> None:
        new = factory(coordinator)
        if new:
            async_add_entities(new)

    _discover()
    return coordinator.async_add_listener(_discover)
