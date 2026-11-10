"""Offline tests: no Home Assistant and no network needed.

Run:  python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import types
import unittest
from datetime import datetime, timezone
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
        self.assertEqual(self.spec("preconditioning_status").extract(BATTERY), "OFF")
        self.assertEqual(self.spec("charging_status").extract(BATTERY), "CHARGING_STATUS_CHARGING")

    def test_charging_status_falls_back_to_deprecated_field(self):
        data = {"chargingStatus": "OLD_VALUE"}
        self.assertEqual(self.spec("charging_status").extract(data), "OLD_VALUE")

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
        self.assertEqual(self.spec("target_soc_type").extract(data), "DAILY")

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
        self.assertEqual(self.spec("climate_seat_front_left").extract({"requestedFrontLeftSeat": "LEVEL_2"}), "LEVEL_2")

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
        self.assertEqual(self.spec_for("target_soc_source").extract(target), "APP")

    def spec_for(self, key):
        return catalog.SPECS_BY_KEY[key]

    def test_known_optional_fields_in_other_endpoints_are_mapped(self):
        self.assertEqual(
            catalog.unmapped_fields("parking_climatization", {"runningStatus": "ON", "errors": [], "requestedFrontLeftSeat": "OFF"}),
            [],
        )


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
