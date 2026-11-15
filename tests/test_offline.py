"""Offline tests: no Home Assistant and no network needed.

Run:  python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

COMP = Path(__file__).resolve().parents[1] / "custom_components" / "polestar_data_portal"

# --- minimal aiohttp stub (only what api.py touches) ----------------------
if "aiohttp" not in sys.modules:
    stub = types.ModuleType("aiohttp")

    class ClientError(Exception):
        pass

    class ClientTimeout:
        def __init__(self, total=None):
            self.total = total

    stub.ClientError = ClientError
    stub.ClientTimeout = ClientTimeout
    stub.ClientResponse = object
    stub.ClientSession = object
    sys.modules["aiohttp"] = stub
import aiohttp  # noqa: E402

# --- load modules without executing the package __init__ (needs HA) ------
pkg = types.ModuleType("pdp")
pkg.__path__ = [str(COMP)]
sys.modules["pdp"] = pkg
catalog = importlib.import_module("pdp.catalog")
api = importlib.import_module("pdp.api")

BATTERY = {
    "vin": "YSMXXXXXXXXXXXXXX",
    "timestamp": {"seconds": "1762730000", "nanos": 0},
    "batteryChargeLevelPercentage": 72,
    "chargingStatusV2": "CHARGING_STATUS_CHARGING",
    "chargingPowerWatts": 7200,
    "estimatedDistanceToEmptyKm": 310,
    "averageEnergyConsumptionKwhPer100Km": 17.4,
    "manualPreconditioning": {"preconditioningStatus": "OFF"},
}


class CatalogTests(unittest.TestCase):
    def spec(self, key):
        return catalog.SPECS_BY_KEY[key]

    def test_every_spec_has_known_endpoint_and_unique_key(self):
        keys = [s.key for s in catalog.SPECS]
        self.assertEqual(len(keys), len(set(keys)))
        for s in catalog.SPECS:
            self.assertIn(s.endpoint, catalog.ENDPOINTS, s.key)
            self.assertIn(s.platform, {"sensor", "binary_sensor"})

    def test_all_endpoints_have_scope_and_path(self):
        self.assertEqual(len(catalog.ENDPOINTS), 14)
        for e in catalog.ENDPOINTS.values():
            self.assertTrue(e.scope.startswith("pdp-"))
            self.assertTrue(e.path)

    def test_battery_values(self):
        self.assertEqual(self.spec("battery_level").extract(BATTERY), 72.0)
        self.assertEqual(self.spec("charging_power").extract(BATTERY), 7200.0)
        self.assertEqual(self.spec("range").extract(BATTERY), 310.0)
        self.assertEqual(self.spec("preconditioning_status").extract(BATTERY), "Off")
        self.assertEqual(self.spec("charging_status").extract(BATTERY), "Charging")

    def test_charging_status_falls_back_to_deprecated_field(self):
        data = {"chargingStatus": "OLD_VALUE"}
        self.assertEqual(self.spec("charging_status").extract(data), "Old value")

    def test_missing_values_are_none(self):
        self.assertIsNone(self.spec("battery_level").extract({}))
        self.assertIsNone(self.spec("battery_level").extract(None))
        self.assertIsNone(self.spec("battery_level").extract({"batteryChargeLevelPercentage": None}))

    def test_odometer_meters_to_km(self):
        self.assertAlmostEqual(self.spec("odometer").extract({"odometerMeters": 2485123}), 2485.123)

    def test_numeric_strings(self):
        loc = {"speed": "55.5", "altitude": "120"}
        self.assertEqual(self.spec("speed").extract(loc), 55.5)
        self.assertEqual(self.spec("altitude").extract(loc), 120.0)
        self.assertIsNone(self.spec("speed").extract({"speed": "n/a"}))
        self.assertIsNone(catalog.to_float(True))

    def test_nested_target_soc(self):
        data = {"targetSoc": {"batteryChargeTargetLevel": 80, "chargeTargetLevelSettingType": "DAILY"}}
        self.assertEqual(self.spec("target_soc").extract(data), 80.0)
        self.assertEqual(self.spec("target_soc_type").extract(data), "Daily")

    def test_opening_state_variants(self):
        f = catalog.opening_state
        self.assertTrue(f("OPEN"))
        self.assertTrue(f("DOOR_STATE_OPEN"))
        self.assertTrue(f("Open"))
        self.assertFalse(f("CLOSED"))
        self.assertFalse(f("DoorClosed"))
        self.assertIsNot(f("NOT_OPEN"), True)
        self.assertIsNone(f("SOMETHING_ELSE"))
        self.assertIsNone(f(""))

    def test_unlocked_state_variants(self):
        f = catalog.unlocked_state
        self.assertTrue(f("UNLOCKED"))
        self.assertTrue(f("CENTRAL_LOCK_UNLOCKED"))
        self.assertFalse(f("LOCKED"))
        self.assertFalse(f("Locked"))
        self.assertIsNone(f("UNKNOWN"))

    def test_binary_specs_keep_raw_value(self):
        spec = self.spec("front_left_door")
        data = {"frontLeftDoor": "OPEN"}
        self.assertTrue(spec.extract(data))
        self.assertEqual(spec.raw(data), "OPEN")
        self.assertIsNone(spec.extract({"frontLeftDoor": "WEIRD"}))
        self.assertEqual(spec.raw({"frontLeftDoor": "WEIRD"}), "WEIRD")

    def test_proto_timestamp(self):
        ts = catalog.proto_timestamp({"seconds": "1762730000", "nanos": 500_000_000})
        self.assertEqual(ts.tzinfo, timezone.utc)
        self.assertEqual(ts, datetime.fromtimestamp(1762730000.5, tz=timezone.utc))
        self.assertIsNone(catalog.proto_timestamp({}))
        iso = catalog.proto_timestamp("2026-11-10T10:00:00Z")
        self.assertEqual(iso, datetime(2026, 11, 10, 10, 0, tzinfo=timezone.utc))
        self.assertIsNone(catalog.proto_timestamp("garbage"))

    def test_hhmm_and_count(self):
        data = {"globalChargeTimer": {"start": {"hour": 23, "minute": 5}, "stop": {"hour": 6}, "activated": True}}
        self.assertEqual(self.spec("global_timer_start").extract(data), "23:05")
        self.assertEqual(self.spec("global_timer_stop").extract(data), "06:00")
        self.assertIs(self.spec("global_timer_active").extract(data), True)
        self.assertEqual(self.spec("charge_locations_count").extract({"chargeLocations": [{}, {}]}), 2)

    def test_payload_timestamp(self):
        self.assertEqual(
            catalog.payload_timestamp(BATTERY),
            datetime.fromtimestamp(1762730000, tz=timezone.utc),
        )
        self.assertIsNone(catalog.payload_timestamp({}))

    def test_call_budget(self):
        default = catalog.estimate_daily_calls(catalog.DEFAULT_SCAN_INTERVAL_MIN, 1, len(catalog.DEFAULT_ENDPOINTS))
        self.assertLess(default, catalog.DAILY_CALL_BUDGET)
        too_many = catalog.estimate_daily_calls(1, 1, len(catalog.DEFAULT_ENDPOINTS))
        self.assertGreater(too_many, catalog.DAILY_CALL_BUDGET)
        self.assertGreater(
            catalog.estimate_daily_calls(5, 3, len(catalog.ENDPOINTS)),
            catalog.estimate_daily_calls(5, 1, len(catalog.ENDPOINTS)),
        )


class ExtendedCatalogTests(unittest.TestCase):
    def spec(self, key):
        return catalog.SPECS_BY_KEY[key]

    def test_energy_breakdown(self):
        data = {
            "energyConsumptionWhSinceCharge": {"driving": 1200, "climate": 150, "battery": 20, "other": 5},
            "energyConsumptionPercentageSinceCharge": {"driving": 87.5},
        }
        self.assertEqual(self.spec("energy_since_charge_driving").extract(data), 1200.0)
        self.assertEqual(self.spec("energy_since_charge_climate").extract(data), 150.0)
        self.assertEqual(self.spec("energy_share_driving").extract(data), 87.5)
        self.assertIsNone(self.spec("energy_manual_driving").extract(data))
        self.assertTrue(self.spec("energy_since_charge_driving").enabled)
        self.assertFalse(self.spec("energy_manual_driving").enabled)
        self.assertEqual(len([k for k in catalog.GENERATED_NAMES]), 16)

    def test_count_accepts_dicts_and_lists(self):
        self.assertEqual(self.spec("light_warnings").extract({"lightWarnings": {"lowBeamLeft": "OK", "fogLightRear": "OK"}}), 2)
        self.assertEqual(self.spec("climate_errors").extract({"errors": ["E1"]}), 1)
        self.assertEqual(self.spec("climate_errors").extract({"errors": []}), 0)
        self.assertIsNone(self.spec("climate_errors").extract({"errors": "x"}))

    def test_discharge_and_seats(self):
        self.assertEqual(self.spec("discharge_power_limit").extract({"dischargeInfo": {"powerLimit": 3700}}), 3700.0)
        self.assertEqual(self.spec("climate_seat_front_left").extract({"requestedFrontLeftSeat": "LEVEL_2"}), "Level 2")

    def test_unmapped_fields(self):
        payload = {
            "vin": "V",
            "meta": {"x": 1},
            "metaReceivedAt": "2026-01-01T00:00:00Z",
            "timestamp": {"seconds": "1", "nanos": 0},
            "batteryChargeLevelPercentage": 50,
            "estimatedDistanceToEmptyMiles": 100,
            "brandNewField": 7,
            "nested": {"deep": {"leaf": 1}},
            "dischargeInfo": {"powerLimit": 1, "surprise": 2},
            "startedAt": {"seconds": "1", "nanos": 0},
        }
        self.assertEqual(
            catalog.unmapped_fields("battery", payload),
            ["brandNewField", "dischargeInfo.surprise", "nested.deep.leaf", "startedAt"],
        )
        self.assertEqual(catalog.unmapped_fields("battery", None), [])
        self.assertEqual(catalog.unmapped_fields("battery", {}), [])

    def test_tracker_coordinates_and_ids_are_not_reported(self):
        location = {"coordinate": {"latitude": 1.0, "longitude": 2.0}, "speed": 0, "id": "x"}
        self.assertEqual(catalog.unmapped_fields("location", location), [])
        target = {
            "id": "a",
            "targetSoc": {"batteryChargeTargetLevel": 80, "chargeTargetLevelSettingType": "DAILY", "id": "b", "source": "APP"},
        }
        self.assertEqual(catalog.unmapped_fields("target_soc", target), [])
        self.assertEqual(self.spec_for("target_soc_source").extract(target), "App")

    def spec_for(self, key):
        return catalog.SPECS_BY_KEY[key]

    def test_known_optional_fields_in_other_endpoints_are_mapped(self):
        self.assertEqual(
            catalog.unmapped_fields("parking_climatization", {"runningStatus": "ON", "errors": [], "requestedFrontLeftSeat": "OFF"}),
            [],
        )


class IdleZeroTests(unittest.TestCase):
    def test_zero_only_when_known_not_charging(self):
        spec = catalog.SPECS_BY_KEY["charging_voltage"]
        self.assertEqual(spec.current({"chargingStatusV2": "CHARGING_STATUS_V2_IDLE"}), 0.0)
        self.assertIsNone(spec.current({"chargingStatusV2": "CHARGING_STATUS_V2_CHARGING"}))
        self.assertIsNone(spec.current({"batteryChargeLevelPercentage": 50}))
        self.assertIsNone(spec.current(None))
        self.assertEqual(spec.current({"chargingVoltageVolts": 231}), 231.0)

    def test_other_specs_unaffected(self):
        spec = catalog.SPECS_BY_KEY["battery_level"]
        self.assertIsNone(spec.current({"chargingStatusV2": "CHARGING_STATUS_V2_IDLE"}))

    def test_calculated_power_zero_when_idle(self):
        self.assertEqual(catalog.charging_power_kw({"chargingStatusV2": "CHARGING_STATUS_V2_IDLE"}), 0.0)
        self.assertIsNone(catalog.charging_power_kw({}))


class TripTrackerTests(unittest.TestCase):
    T0 = datetime(2025, 11, 10, 8, 0, tzinfo=timezone.utc)

    def run_seq(self, tracker, seq):
        done = []
        for minutes, km, cons in seq:
            done.append(tracker.update(self.T0 + timedelta(minutes=minutes), km, cons))
        return done

    def test_drive_after_meter_reset(self):
        t = catalog.TripTracker()
        done = self.run_seq(t, [
            (0, 37.4, 15.6), (5, 37.4, 15.6),          # parked, old trip still shown
            (10, 0.8, 14.0), (15, 6.2, 14.5), (20, 12.0, 15.0),   # new drive, meter reset
            (25, 12.0, 15.0), (30, 12.0, 15.0), (35, 12.0, 15.0),  # stopped 15 min
        ])
        self.assertEqual(done, [False] * 7 + [True])
        self.assertEqual(t.last["distance_km"], 12.0)
        self.assertEqual(t.last["energy_kwh"], 1.8)
        self.assertEqual(t.last["consumption"], 15.0)

    def test_drive_without_reset_uses_differences(self):
        t = catalog.TripTracker()
        self.run_seq(t, [(0, 12.0, 15.0), (5, 12.0, 15.0), (10, 16.0, 16.0), (15, 20.0, 16.0),
                         (20, 20.0, 16.0), (25, 20.0, 16.0), (30, 20.0, 16.0), (35, 20.0, 16.0)])
        self.assertEqual(t.last["distance_km"], 8.0)
        self.assertEqual(t.last["energy_kwh"], 1.4)      # 3.2 - 1.8
        self.assertEqual(t.last["consumption"], 17.5)

    def test_tiny_movement_is_ignored(self):
        t = catalog.TripTracker()
        self.run_seq(t, [(0, 5.0, 15.0), (5, 5.2, 15.0), (10, 5.2, 15.0), (30, 5.2, 15.0)])
        self.assertIsNone(t.last)

    def test_missing_consumption_still_gives_distance(self):
        t = catalog.TripTracker()
        self.run_seq(t, [(0, 10.0, None), (5, 14.0, None), (10, 14.0, None), (30, 14.0, None)])
        self.assertEqual(t.last["distance_km"], 4.0)
        self.assertIsNone(t.last["consumption"])
        self.assertIsNone(t.last["energy_kwh"])

    def test_no_reading_is_ignored(self):
        self.assertFalse(catalog.TripTracker().update(self.T0, None, None))

    def test_restored_last_trip_survives(self):
        t = catalog.TripTracker({"distance_km": 3.0})
        self.assertEqual(t.last["distance_km"], 3.0)


class TripEnergyBreakdownTests(unittest.TestCase):
    T0 = datetime(2025, 11, 10, 8, 0, tzinfo=timezone.utc)

    def test_reported_energy_and_breakdown(self):
        t = catalog.TripTracker()
        bd0 = {"driving": 1000, "climate": 100, "battery": 0, "other": 0}
        bd1 = {"driving": 2500, "climate": 500, "battery": 50, "other": 50}
        seq = [(0, 10.0, 15.0, 5000, bd0), (5, 10.0, 15.0, 5000, bd0), (10, 20.0, 18.0, 5000 + 3000, bd1)]
        for m, km, c, wh, bd in seq:
            t.update(self.T0 + timedelta(minutes=m), km, c, wh, bd)
        done = [t.update(self.T0 + timedelta(minutes=m), 20.0, 18.0, 8000, bd1) for m in (15, 20, 25, 30, 35)]
        self.assertTrue(any(done))
        self.assertEqual(t.last["energy_kwh"], 3.0)
        self.assertEqual(t.last["energy_source"], "reported")
        self.assertEqual(t.last["consumption"], 30.0)
        self.assertEqual(t.last["breakdown_kwh"], {"driving": 1.5, "climate": 0.4, "battery": 0.05, "other": 0.05})

    def test_falls_back_to_estimate(self):
        t = catalog.TripTracker()
        for m, km in ((0, 5.0), (5, 5.0), (10, 15.0), (30, 15.0)):
            t.update(self.T0 + timedelta(minutes=m), km, 16.0)
        self.assertEqual(t.last["energy_source"], "estimated")
        self.assertIsNone(t.last["breakdown_kwh"])


class ChargeTrackerTests(unittest.TestCase):
    T0 = datetime(2025, 11, 10, 20, 0, tzinfo=timezone.utc)

    def feed(self, t, seq):
        out = []
        for m, charging, kw, soc, target in seq:
            out.append(t.update(self.T0 + timedelta(minutes=m), charging, kw, soc, target))
        return out

    def test_session_energy_and_target(self):
        t = catalog.ChargeTracker()
        done = self.feed(t, [(0, False, 0, 20, 90), (5, True, 7.0, 20, 90), (35, True, 7.0, 25, 90),
                             (65, True, 7.0, 30, 90), (70, False, 0, 30, 90)])
        self.assertEqual(done, [False, False, False, False, True])
        self.assertEqual(t.last["energy_kwh"], 7.0)   # 7 kW for 60 min
        self.assertEqual(t.last["duration_min"], 60)
        self.assertEqual((t.last["soc_start"], t.last["soc_end"]), (20, 30))
        self.assertTrue(t.last["below_target"])

    def test_reached_target(self):
        t = catalog.ChargeTracker()
        self.feed(t, [(0, True, 5.0, 80, 80), (30, True, 5.0, 80, 80), (35, False, 0, 80, 80)])
        self.assertFalse(t.last["below_target"])

    def test_unknown_state_does_not_end_session(self):
        t = catalog.ChargeTracker()
        self.feed(t, [(0, True, 5.0, 50, 80), (10, None, None, None, None), (20, True, 5.0, 55, 80)])
        self.assertTrue(t.active)

    def test_very_short_session_ignored(self):
        t = catalog.ChargeTracker()
        self.feed(t, [(0, True, 5.0, 50, 80), (1, False, 0, 50, 80)])
        self.assertIsNone(t.last)


class RangeLearnerTests(unittest.TestCase):
    def test_learns_km_per_percent(self):
        r = catalog.RangeLearner()
        r.update(1000, 80, False)
        self.assertFalse(r.update(1010, 78, False))          # drop too small
        self.assertTrue(r.update(1020, 70, False))           # 20 km / 10 % = 2.0? base was 80
        self.assertAlmostEqual(r.km_per_pct, 2.0)
        self.assertEqual(r.estimate(50, 300), 100)

    def test_charging_resets_window_and_fallback(self):
        r = catalog.RangeLearner()
        r.update(1000, 50, False)
        r.update(1000, 60, True)
        self.assertEqual(r.estimate(40, 250), 250)           # nothing learned yet: car's value
        self.assertTrue(r.update(1030, 56, False))           # window restarted at 60 %: 30 km / 4 %
        self.assertAlmostEqual(r.km_per_pct, 7.5)

    def test_implausible_sample_is_ignored_and_persists(self):
        r = catalog.RangeLearner()
        r.update(1000, 90, False)
        self.assertFalse(r.update(1006, 80, False))          # 0.6 km/% is nonsense
        self.assertIsNone(r.km_per_pct)
        r.km_per_pct, r.samples = 5.0, 3
        self.assertEqual(catalog.RangeLearner(r.to_dict()).km_per_pct, 5.0)


class WarningTextTests(unittest.TestCase):
    def test_humanize(self):
        self.assertEqual(catalog.humanize_warning("LOW_VOLTAGE_BATTERY_WARNING_NO_WARNING"), "No warning")
        self.assertEqual(catalog.humanize_warning("BRAKE_FLUID_LEVEL_WARNING_TOO_LOW"), "Too low")
        self.assertEqual(catalog.humanize_warning("NO_WARNING"), "No warning")
        self.assertEqual(catalog.humanize_warning("UNSPECIFIED"), "Unspecified")
        self.assertIsNone(catalog.humanize_warning("  "))

    def test_enum_prefix_removed(self):
        cases = [
            ("ALARM_STATUS_IDLE", "alarm", "Idle"),
            ("CHARGER_CONNECTION_STATUS_DISCONNECTED", "chargerConnectionStatus", "Disconnected"),
            ("AVAILABILITY_STATUS_AVAILABLE", "availabilityStatus", "Available"),
            ("CHARGING_STATUS_V2_IDLE", "chargingStatusV2", "Idle"),
            ("CHARGING_STATUS_CHARGING", "chargingStatusV2", "Charging"),
            ("CHARGER_POWER_STATUS_NO_POWER_AVAILABLE", "chargerPowerStatus", "No power available"),
            ("USAGE_MODE_ABANDONED", "usageMode", "Abandoned"),
            ("CHARGING_TYPE_NONE", "chargingType", "None"),
            ("CUSTOM", "chargeTargetLevelSettingType", "Custom"),
            ("TOTALLY_NEW_THING", "someField", "Totally new thing"),  # unknown pattern: prettified only
        ]
        for raw, field, want in cases:
            self.assertEqual(catalog.humanize_enum(raw, field), want, raw)

    def test_charging_still_detected_after_shortening(self):
        self.assertTrue(catalog.is_charging({"chargingStatusV2": "CHARGING_STATUS_V2_CHARGING"}))
        self.assertFalse(catalog.is_charging({"chargingStatusV2": "CHARGING_STATUS_V2_IDLE"}))

    def test_ids_are_not_humanised(self):
        spec = catalog.SPECS_BY_KEY["charge_location_id"]
        self.assertEqual(spec.extract({"locationId": "ABC_123"}), "ABC_123")

    def test_calculated_charging_power(self):
        self.assertEqual(catalog.charging_power_kw({"chargingVoltageVolts": 230, "chargingCurrentAmps": 16}), 3.68)
        self.assertEqual(catalog.charging_power_kw({"chargingVoltageVolts": 400, "chargingCurrentAmps": 0}), 0.0)
        self.assertIsNone(catalog.charging_power_kw({"chargingVoltageVolts": 230}))
        self.assertIsNone(catalog.charging_power_kw(None))

    def test_warning_specs_use_it(self):
        spec = catalog.SPECS_BY_KEY["brake_fluid_warning"]
        payload = {"brakeFluidLevelWarning": "BRAKE_FLUID_LEVEL_WARNING_NO_WARNING"}
        self.assertEqual(spec.extract(payload), "No warning")
        self.assertEqual(spec.raw(payload), "BRAKE_FLUID_LEVEL_WARNING_NO_WARNING")
        self.assertEqual(catalog.unmapped_fields("health", payload), [])


class TranslationTests(unittest.TestCase):
    """English is generated from catalog.py; other languages come from Crowdin.

    Crowdin files may be incomplete (HA falls back to English per key), so the
    other languages are only checked for stale keys and placeholders.
    """

    @classmethod
    def setUpClass(cls):
        import json

        tdir = COMP / "translations"
        cls.data = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(tdir.glob("*.json"))}
        cls.en = cls.data["en"]

    @staticmethod
    def leaves(node, prefix=""):
        out = {}
        for k, v in node.items():
            if isinstance(v, dict):
                out.update(TranslationTests.leaves(v, f"{prefix}{k}."))
            else:
                out[f"{prefix}{k}"] = v
        return out

    def test_expected_languages_present(self):
        for lang in ("en", "es", "fr", "de"):
            self.assertIn(lang, self.data)

    def test_every_entity_has_an_english_name(self):
        entity = self.en["entity"]
        for s in catalog.SPECS:
            self.assertTrue(entity[s.platform][s.key]["name"].strip(), s.key)
        for key in catalog.ACCOUNT_ENTITIES:
            self.assertTrue(entity["sensor"][key]["name"].strip(), key)
        self.assertTrue(entity["sensor"]["last_update"]["name"])
        self.assertTrue(entity["device_tracker"]["location"]["name"])

    def test_no_stale_keys_in_other_languages(self):
        reference = set(self.leaves(self.en))
        for lang, data in self.data.items():
            extra = set(self.leaves(data)) - reference
            self.assertFalse(extra, f"{lang}: keys not in English: {sorted(extra)[:5]}")

    def test_placeholders_preserved(self):
        import re

        ref = self.leaves(self.en)
        for lang, data in self.data.items():
            for key, text in self.leaves(data).items():
                want = set(re.findall(r"\{\w+\}", ref[key]))
                self.assertEqual(set(re.findall(r"\{\w+\}", text)), want, f"{lang}:{key}")

    def test_strings_json_matches_english(self):
        import json

        strings = json.loads((COMP / "strings.json").read_text(encoding="utf-8"))
        self.assertEqual(strings, self.en)


class BrandTests(unittest.TestCase):
    def test_icon_files_exist_with_expected_sizes(self):
        brand = COMP / "brand"
        sizes = {"icon.png": 256, "icon@2x.png": 512, "logo.png": 256, "logo@2x.png": 512}
        for name, size in sizes.items():
            data = (brand / name).read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n", name)
            width, height = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
            self.assertEqual((width, height), (size, size), name)


class FakeResp:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    async def json(self, content_type=None):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    def __init__(self, posts=(), gets=()):
        self._posts, self._gets = list(posts), list(gets)
        self.post_calls, self.get_calls = [], []

    def post(self, url, json=None, timeout=None):
        self.post_calls.append((url, json))
        item = self._posts.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def get(self, url, headers=None, timeout=None):
        self.get_calls.append((url, headers))
        item = self._gets.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def token(value="tok", expires=3600):
    return FakeResp(200, {"accessToken": value, "expiresIn": expires, "tokenType": "Bearer"})


def make_client(session):
    c = api.PolestarClient(session, "cid", "secret", "acct")
    c.set_endpoints(["battery", "location"])
    return c


class ApiTests(unittest.TestCase):
    def run_async(self, coro):
        return asyncio.run(coro)

    def test_vehicle_list_and_headers(self):
        s = FakeSession([token()], [FakeResp(200, {"data": ["ysmabc", "YSMDEF"], "meta": {"count": 2}})])
        vins = self.run_async(make_client(s).async_get_vehicles())
        self.assertEqual(vins, ["YSMABC", "YSMDEF"])
        url, headers = s.get_calls[0]
        self.assertTrue(url.endswith("/m2m/v1/vehicles"))
        self.assertEqual(headers["Authorization"], "Bearer tok")
        self.assertEqual(headers["x-client-id"], "acct")
        body = s.post_calls[0][1]
        self.assertEqual(body["clientId"], "cid")
        self.assertEqual(body["scope"], "pdp-telemetry/battery pdp-telemetry/location")

    def test_endpoint_url_and_payload(self):
        s = FakeSession([token()], [FakeResp(200, {"data": {"vin": "V", "batteryChargeLevelPercentage": 50}})])
        data = self.run_async(make_client(s).async_get_endpoint("YSM/1", "battery"))
        self.assertEqual(data["batteryChargeLevelPercentage"], 50)
        self.assertTrue(s.get_calls[0][0].endswith("/v1/vehicles/YSM%2F1/telemetry/battery"))

    def test_token_is_cached(self):
        s = FakeSession([token()], [FakeResp(200, {"data": {}}), FakeResp(200, {"data": {}})])
        c = make_client(s)

        async def go():
            await c.async_get_endpoint("V", "battery")
            await c.async_get_endpoint("V", "location")

        self.run_async(go())
        self.assertEqual(len(s.post_calls), 1)
        self.assertEqual(c.calls_today, 3)  # 1 token + 2 GET

    def test_401_refreshes_token_once(self):
        s = FakeSession(
            [token("old"), token("new")],
            [FakeResp(401, {}), FakeResp(200, {"data": {"vin": "V"}})],
        )
        data = self.run_async(make_client(s).async_get_endpoint("V", "battery"))
        self.assertEqual(data["vin"], "V")
        self.assertEqual(s.get_calls[1][1]["Authorization"], "Bearer new")

    def test_persistent_401_is_auth_error(self):
        s = FakeSession([token(), token()], [FakeResp(401, {}), FakeResp(401, {})])
        with self.assertRaises(api.PolestarAuthError):
            self.run_async(make_client(s).async_get_endpoint("V", "battery"))

    def test_error_mapping(self):
        cases = [
            (403, {"error": {"code": "AUTHZ_VIN_UNAUTHORIZED"}}, api.PolestarForbiddenError),
            (404, {"error": {"code": "DATA_NOT_AVAILABLE"}}, api.PolestarNotAvailableError),
            (429, {}, api.PolestarRateLimitError),
            (500, ValueError("html body"), api.PolestarApiError),
            (503, {"error": {"code": "X"}}, api.PolestarApiError),
        ]
        for status, body, exc in cases:
            with self.subTest(status=status):
                s = FakeSession([token()], [FakeResp(status, body)])
                with self.assertRaises(exc) as ctx:
                    self.run_async(make_client(s).async_get_endpoint("V", "battery"))
                self.assertEqual(ctx.exception.status, status)

    def test_forbidden_carries_code(self):
        s = FakeSession([token()], [FakeResp(403, {"error": {"code": "AUTHZ_VEHICLE_MARKET_NOT_ELIGIBLE"}})])
        with self.assertRaises(api.PolestarForbiddenError) as ctx:
            self.run_async(make_client(s).async_get_endpoint("V", "battery"))
        self.assertEqual(ctx.exception.code, "AUTHZ_VEHICLE_MARKET_NOT_ELIGIBLE")

    def test_bad_credentials(self):
        s = FakeSession([FakeResp(401, {"error": "invalid_client", "error_description": "bad"})])
        with self.assertRaises(api.PolestarAuthError):
            self.run_async(make_client(s).async_get_vehicles())

    def test_scope_rejection_retries_without_scope(self):
        s = FakeSession([FakeResp(400, {"error": "invalid_scope"}), token()], [FakeResp(200, {"data": ["V"]})])
        self.assertEqual(self.run_async(make_client(s).async_get_vehicles()), ["V"])
        self.assertIn("scope", s.post_calls[0][1])
        self.assertNotIn("scope", s.post_calls[1][1])

    def test_network_error_is_connection_error(self):
        s = FakeSession([token()], [aiohttp.ClientError("boom")])
        with self.assertRaises(api.PolestarConnectionError):
            self.run_async(make_client(s).async_get_endpoint("V", "battery"))

    def test_token_server_error_is_retryable_not_auth(self):
        s = FakeSession([FakeResp(503, {})])
        with self.assertRaises(api.PolestarApiError) as ctx:
            self.run_async(make_client(s).async_get_vehicles())
        self.assertNotIsInstance(ctx.exception, api.PolestarAuthError)

    def test_unexpected_vehicle_body(self):
        s = FakeSession([token()], [FakeResp(200, {"data": "nope"})])
        with self.assertRaises(api.PolestarApiError):
            self.run_async(make_client(s).async_get_vehicles())


if __name__ == "__main__":
    unittest.main()
