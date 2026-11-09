"""Smoke test of the Home Assistant platform code using minimal stubs.

This does NOT replace testing inside a real Home Assistant: the stubs only
check that every module imports, entity discovery runs and entities compute
their values from coordinator data without crashing.

Run:  python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import types
import unittest
from pathlib import Path

COMP = Path(__file__).resolve().parents[1] / "custom_components" / "polestar_data_portal"


class _Meta(type):
    def __getattr__(cls, name):  # Platform.SENSOR, EntityCategory.DIAGNOSTIC ...
        if name.startswith("__"):
            raise AttributeError(name)
        return f"{cls.__name__}.{name}"


class _Base(metaclass=_Meta):
    def __init__(self, *args, **kwargs):
        pass

    def __init_subclass__(cls, **kwargs):
        pass

    def __class_getitem__(cls, item):
        return cls


class _StubModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        value = _Meta(name, (_Base,), {})
        setattr(self, name, value)
        return value


def _install_stubs() -> None:
    names = [
        "voluptuous",
        "homeassistant",
        "homeassistant.config_entries",
        "homeassistant.const",
        "homeassistant.core",
        "homeassistant.exceptions",
        "homeassistant.components",
        "homeassistant.components.sensor",
        "homeassistant.components.binary_sensor",
        "homeassistant.components.device_tracker",
        "homeassistant.components.device_tracker.config_entry",
        "homeassistant.components.diagnostics",
        "homeassistant.helpers",
        "homeassistant.helpers.aiohttp_client",
        "homeassistant.helpers.device_registry",
        "homeassistant.helpers.entity_platform",
        "homeassistant.helpers.selector",
        "homeassistant.helpers.update_coordinator",
    ]
    for name in names:
        sys.modules.setdefault(name, _StubModule(name))
    # decorators / callables that must really work
    sys.modules["homeassistant.core"].callback = lambda f: f
    sys.modules["homeassistant.core"].HomeAssistant = object
    sys.modules["homeassistant.helpers.device_registry"].DeviceInfo = dict
    sys.modules["homeassistant.components.diagnostics"].async_redact_data = lambda d, keys: d


_install_stubs()

if "aiohttp" not in sys.modules:
    aio = types.ModuleType("aiohttp")
    aio.ClientError = type("ClientError", (Exception,), {})
    aio.ClientTimeout = lambda total=None: None
    aio.ClientResponse = object
    aio.ClientSession = object
    sys.modules["aiohttp"] = aio

pkg = types.ModuleType("pdp_ha")
pkg.__path__ = [str(COMP)]
sys.modules["pdp_ha"] = pkg

MODULES = [
    "catalog", "api", "const", "coordinator", "entity", "sensor",
    "binary_sensor", "device_tracker", "config_flow", "diagnostics", "__init__",
]


class PlatformSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mods = {}
        for name in MODULES:
            full = "pdp_ha" if name == "__init__" else f"pdp_ha.{name}"
            if name == "__init__":
                spec = importlib.util.spec_from_file_location(
                    "pdp_ha_init", COMP / "__init__.py", submodule_search_locations=[str(COMP)]
                )
                # Execute __init__ as part of a package named pdp_ha_init so
                # its relative imports resolve to the same files.
                mod = importlib.util.module_from_spec(spec)
                sys.modules["pdp_ha_init"] = mod
                spec.loader.exec_module(mod)
                cls.mods[name] = mod
            else:
                cls.mods[name] = importlib.import_module(full)

    def test_all_modules_import(self):
        self.assertEqual(len(self.mods), len(MODULES))

    def _fake_coordinator(self):
        battery = {
            "vin": "YSM123456",
            "timestamp": {"seconds": "1762730000", "nanos": 0},
            "batteryChargeLevelPercentage": 64,
            "chargingPowerWatts": 0,
        }
        exterior = {
            "centralLock": "LOCKED",
            "frontLeftDoor": "CLOSED",
            "hood": "SOMETHING_NEW",
        }
        location = {"coordinate": {"latitude": 28.1, "longitude": -15.4}, "speed": "0", "heading": 90}
        coord = types.SimpleNamespace(
            vins=["YSM123456"],
            data={"YSM123456": {"battery": battery, "exterior": exterior, "location": location}},
            endpoints=["battery", "exterior", "location"],
            client=types.SimpleNamespace(calls_today=7),
        )
        coord.async_add_listener = lambda cb: (lambda: None)
        return coord

    def _setup_platform(self, module_name):
        coord = self._fake_coordinator()
        added = []
        entry = types.SimpleNamespace(
            runtime_data=coord, entry_id="entry1", async_on_unload=lambda f: None
        )
        asyncio.run(self.mods[module_name].async_setup_entry(None, entry, added.extend))
        for ent in added:
            ent.coordinator = coord
        return coord, added

    def test_sensors_discovered_and_valued(self):
        _, added = self._setup_platform("sensor")
        by_uid = {e._attr_unique_id: e for e in added}
        self.assertEqual(by_uid["YSM123456_battery_level"].native_value, 64.0)
        self.assertEqual(by_uid["YSM123456_charging_power"].native_value, 0.0)
        self.assertEqual(by_uid["YSM123456_speed"].native_value, 0.0)
        self.assertNotIn("YSM123456_odometer", by_uid)  # endpoint not reported
        self.assertIn("YSM123456_last_update", by_uid)
        self.assertEqual(by_uid["YSM123456_battery_level"].extra_state_attributes["reported_at"][:4], "2025")
        self.assertEqual(by_uid["entry1_api_calls_today"].native_value, 7)
        self.assertEqual(by_uid["entry1_vehicle_count"].native_value, 1)

    def test_binary_sensors_keep_unknown_raw_values(self):
        _, added = self._setup_platform("binary_sensor")
        by_uid = {e._attr_unique_id: e for e in added}
        self.assertIs(by_uid["YSM123456_central_lock"].is_on, False)  # locked -> off
        self.assertIs(by_uid["YSM123456_front_left_door"].is_on, False)
        hood = by_uid["YSM123456_hood"]
        self.assertIsNone(hood.is_on)
        self.assertEqual(hood.extra_state_attributes["raw_state"], "SOMETHING_NEW")
        self.assertNotIn("YSM123456_sunroof", by_uid)

    def test_tracker(self):
        _, added = self._setup_platform("device_tracker")
        self.assertEqual(len(added), 1)
        tracker = added[0]
        self.assertEqual((tracker.latitude, tracker.longitude), (28.1, -15.4))
        self.assertEqual(tracker.extra_state_attributes["heading"], 90.0)

    def test_discovery_is_not_duplicated(self):
        coord = self._fake_coordinator()
        added = []
        entry = types.SimpleNamespace(runtime_data=coord, entry_id="e", async_on_unload=lambda f: None)
        captured = {}
        coord.async_add_listener = lambda cb: captured.setdefault("cb", cb) and (lambda: None)
        asyncio.run(self.mods["sensor"].async_setup_entry(None, entry, added.extend))
        first = len(added)
        captured["cb"]()  # simulate another coordinator refresh
        self.assertEqual(len(added), first)


if __name__ == "__main__":
    unittest.main()
