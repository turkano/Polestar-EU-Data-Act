"""Endpoint and entity catalog for the Polestar Data Portal API.

This module is deliberately free of Home Assistant imports so it can be unit
tested (and used by the translation builder) without Home Assistant installed.

Everything here is derived from the official Polestar Data Portal API
documentation ("M2M and Telemetry APIs"). All endpoints are read-only GETs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

BASE_URL = "https://pc-api.polestar.com/eu-north-1/data-portal/m2m"
TOKEN_URL = f"{BASE_URL}/token"
VEHICLES_URL = f"{BASE_URL}/v1/vehicles"

# The portal allows 10,000 calls per client per day.
DAILY_CALL_LIMIT = 10_000
# Keep a safety margin for token requests, vehicle listing and retries.
DAILY_CALL_BUDGET = 9_000


@dataclass(frozen=True)
class Endpoint:
    """One data-portal endpoint (per VIN)."""

    key: str
    path: str
    scope: str
    default: bool
    name_en: str
    name_es: str


ENDPOINTS: dict[str, Endpoint] = {
    e.key: e
    for e in (
        Endpoint("availability", "telemetry/availability", "pdp-telemetry/availability", True, "Availability", "Disponibilidad"),
        Endpoint("battery", "telemetry/battery", "pdp-telemetry/battery", True, "Battery and charging", "Batería y carga"),
        Endpoint("exterior", "telemetry/exterior", "pdp-telemetry/exterior", True, "Doors, windows and locks", "Puertas, ventanas y cierres"),
        Endpoint("health", "telemetry/health", "pdp-telemetry/health", True, "Health (service, tyres, warnings)", "Salud (servicio, neumáticos, avisos)"),
        Endpoint("location", "telemetry/location", "pdp-telemetry/location", True, "Location", "Ubicación"),
        Endpoint("odometer", "telemetry/odometer", "pdp-telemetry/odometer", True, "Odometer and trips", "Kilometraje y viajes"),
        Endpoint("target_soc", "charging/target-soc", "pdp-charging/targetSoc", True, "Charge target", "Objetivo de carga"),
        Endpoint("parking_climatization", "telemetry/parking-climatization", "pdp-telemetry/parkingClimatization", False, "Parking climatization", "Climatización en parado"),
        Endpoint("pre_cleaning", "telemetry/pre-cleaning", "pdp-telemetry/preCleaning", False, "Cabin pre-cleaning", "Limpieza previa del habitáculo"),
        Endpoint("amp_limit", "charging/amp-limit", "pdp-charging/ampLimit", False, "Charging current limit", "Límite de corriente de carga"),
        Endpoint("charge_now", "charging/charge-now", "pdp-charging/overrideChargeTimer", False, "Charge Now", "Carga inmediata"),
        Endpoint("global_charge_timer", "charging/global-charge-timer", "pdp-charging/globalChargeTimer", False, "Global charge timer", "Temporizador de carga global"),
        Endpoint("is_at_charge_location", "charging/is-at-charge-location", "pdp-charging/isAtChargeLocation", False, "At charge location", "En ubicación de carga"),
        Endpoint("charge_locations", "charging/charge-locations", "pdp-charging/chargeLocations", False, "Charge locations", "Ubicaciones de carga"),
    )
}

DEFAULT_ENDPOINTS = [k for k, e in ENDPOINTS.items() if e.default]
DEFAULT_SCAN_INTERVAL_MIN = 5
MIN_SCAN_INTERVAL_MIN = 1
MAX_SCAN_INTERVAL_MIN = 60


def estimate_daily_calls(interval_min: float, vehicles: int, endpoints: int) -> int:
    """Estimate API calls per day for a polling setup (incl. overhead)."""
    polls = 1440 / max(interval_min, 0.1)
    overhead = 1 + 48  # vehicle listing + token refreshes
    return int(polls * max(vehicles, 1) * endpoints + overhead)


# --------------------------------------------------------------------------
# Value helpers
# --------------------------------------------------------------------------


def get_path(data: Any, path: str) -> Any:
    """Return the value at a dotted path, or None."""
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def to_float(value: Any) -> float | None:
    """Convert numbers and numeric strings to float (bools are rejected)."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def proto_timestamp(value: Any) -> datetime | None:
    """Parse a protobuf-style {seconds, nanos} object or an ISO-8601 string."""
    if isinstance(value, dict):
        secs = to_float(value.get("seconds"))
        if secs is None:
            return None
        nanos = to_float(value.get("nanos")) or 0.0
        try:
            return datetime.fromtimestamp(secs + nanos / 1e9, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def hhmm(value: Any) -> str | None:
    """Format {hour, minute, ...} as HH:MM."""
    if not isinstance(value, dict):
        return None
    hour, minute = to_float(value.get("hour")), to_float(value.get("minute"))
    if hour is None:
        return None
    return f"{int(hour):02d}:{int(minute or 0):02d}"


def _tokens(value: Any) -> set[str]:
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(value))
    return {t for t in re.split(r"[^A-Za-z0-9]+", text.upper()) if t}


def opening_state(value: Any) -> bool | None:
    """True if open, False if closed, None if the value is not understood.

    The API documents these fields as plain strings without listing the
    possible values, so this is deliberately tolerant. The raw value is always
    exposed as the ``raw_state`` attribute.
    """
    tokens = _tokens(value)
    if tokens & {"CLOSED", "CLOSE", "SHUT"}:
        return False
    if tokens & {"OPEN", "OPENED", "AJAR"} and "NOT" not in tokens:
        return True
    return None


def unlocked_state(value: Any) -> bool | None:
    """True if unlocked, False if locked, None if not understood."""
    tokens = _tokens(value)
    if tokens & {"UNLOCKED", "UNLOCK"}:
        return True
    if tokens & {"LOCKED", "LOCK"}:
        return False
    return None


# --------------------------------------------------------------------------
# Entity specs
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Spec:
    """Describes one entity derived from one field of one endpoint."""

    key: str
    endpoint: str
    platform: str  # "sensor" | "binary_sensor"
    paths: tuple[str, ...]  # first path with a value wins
    kind: str  # num | text | ts | m_to_km | hhmm | bool | opening | unlocked | count
    name_en: str
    name_es: str
    device_class: str | None = None
    unit: str | None = None
    state_class: str | None = None
    category: str | None = None  # "diagnostic"
    enabled: bool = True
    icon: str | None = None
    precision: int | None = None

    def extract(self, data: dict[str, Any] | None) -> Any:
        """Extract and convert the value from an endpoint payload."""
        if not data:
            return None
        raw = None
        for path in self.paths:
            raw = get_path(data, path)
            if raw is not None:
                break
        if raw is None:
            return None
        kind = self.kind
        if kind == "num":
            return to_float(raw)
        if kind == "m_to_km":
            val = to_float(raw)
            return None if val is None else val / 1000.0
        if kind == "text":
            if isinstance(raw, (dict, list)):
                return None
            return str(raw)
        if kind == "ts":
            return proto_timestamp(raw)
        if kind == "hhmm":
            return hhmm(raw)
        if kind == "bool":
            return raw if isinstance(raw, bool) else None
        if kind == "opening":
            return opening_state(raw)
        if kind == "unlocked":
            return unlocked_state(raw)
        if kind == "count":
            return len(raw) if isinstance(raw, list) else None
        return None

    def raw(self, data: dict[str, Any] | None) -> Any:
        """Return the unconverted value (used for the raw_state attribute)."""
        if not data:
            return None
        for path in self.paths:
            value = get_path(data, path)
            if value is not None:
                return value
        return None


def _s(key, endpoint, paths, name_en, name_es, kind="num", platform="sensor", **kw) -> Spec:
    if isinstance(paths, str):
        paths = (paths,)
    return Spec(key, endpoint, platform, tuple(paths), kind, name_en, name_es, **kw)


DIAG = "diagnostic"
M = "measurement"

SPECS: tuple[Spec, ...] = (
    # ---- availability ----------------------------------------------------
    _s("availability_status", "availability", "availabilityStatus", "Availability", "Disponibilidad", "text", icon="mdi:cloud-check"),
    _s("usage_mode", "availability", "usageMode", "Usage mode", "Modo de uso", "text", icon="mdi:car-cog"),
    _s("unavailable_reason", "availability", "unavailableReason", "Unavailable reason", "Motivo de no disponibilidad", "text", category=DIAG),
    # ---- battery ---------------------------------------------------------
    _s("battery_level", "battery", "batteryChargeLevelPercentage", "Battery", "Batería", device_class="battery", unit="%", state_class=M),
    _s("range", "battery", "estimatedDistanceToEmptyKm", "Range", "Autonomía", device_class="distance", unit="km", state_class=M, precision=0),
    _s("charging_status", "battery", ("chargingStatusV2", "chargingStatus"), "Charging status", "Estado de carga", "text", icon="mdi:ev-station"),
    _s("charger_connection_status", "battery", "chargerConnectionStatus", "Charger connection", "Conexión del cargador", "text", icon="mdi:ev-plug-type2"),
    _s("charger_power_status", "battery", "chargerPowerStatus", "Charger power status", "Estado de potencia del cargador", "text"),
    _s("charging_type", "battery", "chargingType", "Charging type", "Tipo de carga", "text"),
    _s("charging_power", "battery", "chargingPowerWatts", "Charging power", "Potencia de carga", device_class="power", unit="W", state_class=M),
    _s("charging_current", "battery", "chargingCurrentAmps", "Charging current", "Corriente de carga", device_class="current", unit="A", state_class=M),
    _s("charging_voltage", "battery", "chargingVoltageVolts", "Charging voltage", "Tensión de carga", device_class="voltage", unit="V", state_class=M),
    _s("time_to_full", "battery", "estimatedChargingTimeToFullMinutes", "Time to full charge", "Tiempo hasta carga completa", device_class="duration", unit="min", state_class=M),
    _s("time_to_target_distance", "battery", "estimatedChargingTimeMinutesToTargetDistance", "Time to target distance", "Tiempo hasta distancia objetivo", device_class="duration", unit="min", state_class=M, enabled=False),
    _s("time_to_minimum_soc", "battery", "estimatedChargingTimeMinutesToMinimumSoc", "Time to minimum charge", "Tiempo hasta carga mínima", device_class="duration", unit="min", state_class=M, enabled=False),
    _s("consumption_average", "battery", "averageEnergyConsumptionKwhPer100Km", "Average consumption", "Consumo medio", unit="kWh/100km", state_class=M, precision=1, icon="mdi:lightning-bolt"),
    _s("consumption_since_charge", "battery", "averageEnergyConsumptionKwhPer100KmSinceCharge", "Consumption since charge", "Consumo desde la última carga", unit="kWh/100km", state_class=M, precision=1, icon="mdi:lightning-bolt"),
    _s("consumption_automatic", "battery", "averageEnergyConsumptionKwhPer100KmAutomatic", "Consumption (automatic trip)", "Consumo (viaje automático)", unit="kWh/100km", state_class=M, precision=1, enabled=False, icon="mdi:lightning-bolt"),
    _s("total_energy_consumption", "battery", "totalEnergyConsumptionWh", "Total energy consumption", "Consumo total de energía", device_class="energy", unit="Wh", enabled=False),
    _s("preconditioning_status", "battery", "manualPreconditioning.preconditioningStatus", "Preconditioning", "Preacondicionamiento", "text", icon="mdi:air-conditioner"),
    # ---- exterior --------------------------------------------------------
    _s("central_lock", "exterior", "centralLock", "Central lock", "Cierre centralizado", "unlocked", "binary_sensor", device_class="lock"),
    _s("tailgate_lock", "exterior", "tailgateLock", "Tailgate lock", "Cierre del portón", "unlocked", "binary_sensor", device_class="lock"),
    _s("front_left_door", "exterior", "frontLeftDoor", "Front left door", "Puerta delantera izquierda", "opening", "binary_sensor", device_class="door"),
    _s("front_right_door", "exterior", "frontRightDoor", "Front right door", "Puerta delantera derecha", "opening", "binary_sensor", device_class="door"),
    _s("rear_left_door", "exterior", "rearLeftDoor", "Rear left door", "Puerta trasera izquierda", "opening", "binary_sensor", device_class="door"),
    _s("rear_right_door", "exterior", "rearRightDoor", "Rear right door", "Puerta trasera derecha", "opening", "binary_sensor", device_class="door"),
    _s("front_left_window", "exterior", "frontLeftWindow", "Front left window", "Ventana delantera izquierda", "opening", "binary_sensor", device_class="window"),
    _s("front_right_window", "exterior", "frontRightWindow", "Front right window", "Ventana delantera derecha", "opening", "binary_sensor", device_class="window"),
    _s("rear_left_window", "exterior", "rearLeftWindow", "Rear left window", "Ventana trasera izquierda", "opening", "binary_sensor", device_class="window"),
    _s("rear_right_window", "exterior", "rearRightWindow", "Rear right window", "Ventana trasera derecha", "opening", "binary_sensor", device_class="window"),
    _s("hood", "exterior", "hood", "Hood", "Capó", "opening", "binary_sensor", device_class="opening"),
    _s("tailgate", "exterior", "tailgate", "Tailgate", "Portón trasero", "opening", "binary_sensor", device_class="opening"),
    _s("tank_lid", "exterior", "tankLid", "Charge port / tank lid", "Tapa de carga / depósito", "opening", "binary_sensor", device_class="opening"),
    _s("sunroof", "exterior", "sunroof", "Sunroof", "Techo solar", "opening", "binary_sensor", device_class="opening"),
    _s("alarm", "exterior", "alarm", "Alarm", "Alarma", "text", icon="mdi:alarm-light"),
    # ---- health ----------------------------------------------------------
    _s("days_to_service", "health", "daysToService", "Days to service", "Días hasta el servicio", device_class="duration", unit="d", state_class=M),
    _s("distance_to_service", "health", "distanceToServiceKm", "Distance to service", "Distancia hasta el servicio", device_class="distance", unit="km", state_class=M, precision=0),
    _s("engine_hours_to_service", "health", "engineHoursToService", "Engine hours to service", "Horas de motor hasta el servicio", unit="h", state_class=M, enabled=False),
    _s("service_warning", "health", "serviceWarning", "Service warning", "Aviso de servicio", "text", icon="mdi:wrench-clock"),
    _s("brake_fluid_warning", "health", "brakeFluidLevelWarning", "Brake fluid warning", "Aviso líquido de frenos", "text", category=DIAG),
    _s("coolant_warning", "health", "engineCoolantLevelWarning", "Coolant warning", "Aviso refrigerante", "text", category=DIAG),
    _s("oil_warning", "health", "oilLevelWarning", "Oil level warning", "Aviso nivel de aceite", "text", category=DIAG, enabled=False),
    _s("washer_fluid_warning", "health", "washerFluidLevelWarning", "Washer fluid warning", "Aviso líquido lavaparabrisas", "text", category=DIAG),
    _s("low_voltage_battery_warning", "health", "lowVoltageBatteryWarning", "12 V battery warning", "Aviso batería de 12 V", "text", category=DIAG),
    _s("tyre_pressure_front_left", "health", "frontLeftTyrePressureKpa", "Tyre pressure front left", "Presión neumático delantero izq.", device_class="pressure", unit="kPa", state_class=M, precision=0),
    _s("tyre_pressure_front_right", "health", "frontRightTyrePressureKpa", "Tyre pressure front right", "Presión neumático delantero der.", device_class="pressure", unit="kPa", state_class=M, precision=0),
    _s("tyre_pressure_rear_left", "health", "rearLeftTyrePressureKpa", "Tyre pressure rear left", "Presión neumático trasero izq.", device_class="pressure", unit="kPa", state_class=M, precision=0),
    _s("tyre_pressure_rear_right", "health", "rearRightTyrePressureKpa", "Tyre pressure rear right", "Presión neumático trasero der.", device_class="pressure", unit="kPa", state_class=M, precision=0),
    _s("tyre_reference_front", "health", "frontTyresReferencePressureKpa", "Front tyre reference pressure", "Presión recomendada eje delantero", device_class="pressure", unit="kPa", state_class=M, category=DIAG, precision=0),
    _s("tyre_reference_rear", "health", "rearTyresReferencePressureKpa", "Rear tyre reference pressure", "Presión recomendada eje trasero", device_class="pressure", unit="kPa", state_class=M, category=DIAG, precision=0),
    _s("tyre_warning_front_left", "health", "frontLeftTyrePressureWarning", "Tyre warning front left", "Aviso neumático delantero izq.", "text", category=DIAG),
    _s("tyre_warning_front_right", "health", "frontRightTyrePressureWarning", "Tyre warning front right", "Aviso neumático delantero der.", "text", category=DIAG),
    _s("tyre_warning_rear_left", "health", "rearLeftTyrePressureWarning", "Tyre warning rear left", "Aviso neumático trasero izq.", "text", category=DIAG),
    _s("tyre_warning_rear_right", "health", "rearRightTyrePressureWarning", "Tyre warning rear right", "Aviso neumático trasero der.", "text", category=DIAG),
    # ---- location (speed/altitude/heading; the tracker is a separate platform)
    _s("speed", "location", "speed", "Speed", "Velocidad", device_class="speed", unit="km/h", state_class=M, precision=0),
    _s("altitude", "location", "altitude", "Altitude", "Altitud", device_class="distance", unit="m", state_class=M, precision=0, enabled=False),
    _s("heading", "location", "heading", "Heading", "Rumbo", unit="°", state_class=M, precision=0, enabled=False, icon="mdi:compass"),
    # ---- odometer --------------------------------------------------------
    _s("odometer", "odometer", "odometerMeters", "Odometer", "Kilometraje", "m_to_km", device_class="distance", unit="km", state_class="total_increasing", precision=0),
    _s("trip_manual", "odometer", "tripMeterManualKm", "Trip (manual)", "Viaje (manual)", device_class="distance", unit="km", state_class=M, precision=1),
    _s("trip_automatic", "odometer", "tripMeterAutomaticKm", "Trip (automatic)", "Viaje (automático)", device_class="distance", unit="km", state_class=M, precision=1),
    _s("trip_since_charge", "odometer", "tripMeterSinceChargeKm", "Distance since charge", "Distancia desde la última carga", device_class="distance", unit="km", state_class=M, precision=1),
    _s("average_speed_manual", "odometer", "averageSpeedKmPerHour", "Average speed (manual trip)", "Velocidad media (viaje manual)", device_class="speed", unit="km/h", state_class=M, precision=0, enabled=False),
    _s("average_speed_automatic", "odometer", "averageSpeedKmPerHourAutomatic", "Average speed (automatic trip)", "Velocidad media (viaje automático)", device_class="speed", unit="km/h", state_class=M, precision=0, enabled=False),
    _s("average_speed_since_charge", "odometer", "averageSpeedKmPerHourSinceCharge", "Average speed since charge", "Velocidad media desde la carga", device_class="speed", unit="km/h", state_class=M, precision=0, enabled=False),
    # ---- charge target ---------------------------------------------------
    _s("target_soc", "target_soc", "targetSoc.batteryChargeTargetLevel", "Charge target", "Objetivo de carga", unit="%", state_class=M, icon="mdi:battery-charging-high"),
    _s("target_soc_type", "target_soc", "targetSoc.chargeTargetLevelSettingType", "Charge target type", "Tipo de objetivo de carga", "text", category=DIAG),
    # ---- parking climatization ------------------------------------------
    _s("climate_running_status", "parking_climatization", "runningStatus", "Parking climate status", "Estado climatización en parado", "text", icon="mdi:air-conditioner"),
    _s("climate_main_running_status", "parking_climatization", "mainClimateRunningStatus", "Main climate status", "Estado climatización principal", "text"),
    _s("climate_ventilation", "parking_climatization", "ventilation", "Ventilation", "Ventilación", "text"),
    _s("climate_current_temperature", "parking_climatization", "currentCompartmentTemperatureCelsius", "Cabin temperature", "Temperatura del habitáculo", device_class="temperature", unit="°C", state_class=M, precision=1),
    _s("climate_requested_temperature", "parking_climatization", "requestedCompartmentTemperatureCelsius", "Requested cabin temperature", "Temperatura solicitada", device_class="temperature", unit="°C", state_class=M, precision=1),
    _s("climate_started_at", "parking_climatization", "startedAt", "Climate started at", "Climatización iniciada", "ts", device_class="timestamp", category=DIAG),
    _s("climate_ending_at", "parking_climatization", "endingAt", "Climate ending at", "Climatización termina", "ts", device_class="timestamp", category=DIAG),
    _s("climate_start_reason", "parking_climatization", "startReason", "Climate start reason", "Motivo de inicio", "text", category=DIAG),
    # ---- pre-cleaning ----------------------------------------------------
    _s("pre_cleaning_status", "pre_cleaning", "runningStatus", "Pre-cleaning status", "Estado limpieza previa", "text", icon="mdi:air-filter"),
    _s("air_quality_index", "pre_cleaning", "measuredAirQualityIndex", "Air quality index", "Índice de calidad del aire", state_class=M, icon="mdi:air-filter"),
    _s("particulate_matter_25", "pre_cleaning", "measuredParticulateMatter25", "Particulate matter PM2.5", "Partículas PM2.5", state_class=M),
    _s("pre_cleaning_last_cycle", "pre_cleaning", "lastCycleCompleted", "Last pre-cleaning cycle", "Último ciclo de limpieza previa", "ts", device_class="timestamp", category=DIAG),
    _s("pre_cleaning_error", "pre_cleaning", "error", "Pre-cleaning error", "Error limpieza previa", "text", category=DIAG),
    # ---- charging settings -----------------------------------------------
    _s("amp_limit", "amp_limit", "ampLimit.ampLimit", "Charging current limit", "Límite de corriente de carga", device_class="current", unit="A", state_class=M),
    _s("charge_now", "charge_now", "syncedOverrideChargeTimer.override", "Charge Now", "Carga inmediata", "bool", "binary_sensor", icon="mdi:flash"),
    _s("global_timer_active", "global_charge_timer", "globalChargeTimer.activated", "Global charge timer active", "Temporizador global activo", "bool", "binary_sensor", icon="mdi:timer-outline"),
    _s("global_timer_start", "global_charge_timer", "globalChargeTimer.start", "Global charge timer start", "Inicio temporizador global", "hhmm", icon="mdi:timer-play-outline"),
    _s("global_timer_stop", "global_charge_timer", "globalChargeTimer.stop", "Global charge timer stop", "Fin temporizador global", "hhmm", icon="mdi:timer-stop-outline"),
    _s("charge_location_id", "is_at_charge_location", "locationId", "Current charge location", "Ubicación de carga actual", "text", icon="mdi:map-marker"),
    _s("charge_location_arrived", "is_at_charge_location", "arrivedAtTimestamp", "Arrived at charge location", "Llegada a ubicación de carga", "ts", device_class="timestamp", category=DIAG),
    _s("charge_locations_count", "charge_locations", "chargeLocations", "Saved charge locations", "Ubicaciones de carga guardadas", "count", icon="mdi:map-marker-multiple", category=DIAG),
)

SPECS_BY_KEY = {s.key: s for s in SPECS}
assert len(SPECS_BY_KEY) == len(SPECS), "duplicate spec key"
assert all(s.endpoint in ENDPOINTS for s in SPECS), "unknown endpoint in spec"

# Account-level diagnostic entities (not tied to a VIN)
ACCOUNT_ENTITIES = {
    "api_calls_today": ("API calls today", "Llamadas a la API hoy"),
    "vehicle_count": ("Vehicles", "Vehículos"),
}
# Per-vehicle generic entities
VEHICLE_LAST_UPDATE = ("last_update", "Last update", "Última actualización")
TRACKER_NAME = ("Location", "Ubicación")


def payload_timestamp(payload: dict[str, Any] | None) -> datetime | None:
    """Best-known data timestamp of an endpoint payload."""
    if not payload:
        return None
    for key in ("timestamp", "updatedAtTimestamp", "metaReceivedAt", "updatedAt"):
        parsed = proto_timestamp(payload.get(key))
        if parsed:
            return parsed
    return None
