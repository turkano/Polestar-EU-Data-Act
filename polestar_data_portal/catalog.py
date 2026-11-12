"""Endpoint and entity catalog for the Polestar Data Portal API.

This module is deliberately free of Home Assistant imports so it can be unit
tested (and used by the translation builder) without Home Assistant installed.

Everything here is derived from the official Polestar Data Portal API
documentation ("M2M and Telemetry APIs"). All endpoints are read-only GETs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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


def _snake_upper(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).upper()


def humanize_enum(value: Any, field: str | None = None) -> str | None:
    """Short readable form of an enum string such as ``CHARGING_TYPE_NONE``.

    The API prefixes every value with the name of the enum type, which is
    usually the field name in UPPER_SNAKE_CASE (``chargingType`` ->
    ``CHARGING_TYPE_``). Removing that prefix leaves the part that carries the
    information (``NONE``), shown as ``None``. Warnings repeat the field name
    in a longer form (``LOW_VOLTAGE_BATTERY_WARNING_NO_WARNING``), so the text
    after the last ``_WARNING_`` is used when no prefix matched. Values that
    do not follow either pattern are only prettified, never dropped.
    """
    text = str(value).strip()
    if not text:
        return None
    stripped = False
    if field:
        base = _snake_upper(field)
        bases = [base]
        unversioned = re.sub(r"_V\d+$", "", base)  # chargingStatusV2 may use CHARGING_STATUS_
        if unversioned != base:
            bases.append(unversioned)
        prefixes = [b + suffix for b in bases for suffix in ("_STATUS_", "_")]
        for prefix in prefixes:  # alarm -> ALARM_STATUS_
            if text.startswith(prefix) and len(text) > len(prefix):
                text, stripped = text[len(prefix):], True
                break
    if not stripped and "_WARNING_" in text:
        text = text.rsplit("_WARNING_", 1)[1]
    text = text.replace("_", " ").strip().lower()
    return text[:1].upper() + text[1:] if text else None


def humanize_warning(value: Any) -> str | None:
    """Kept for compatibility: enum text without a known field name."""
    return humanize_enum(value)


@dataclass(frozen=True)
class Spec:
    """Describes one entity derived from one field of one endpoint."""

    key: str
    endpoint: str
    platform: str  # "sensor" | "binary_sensor"
    paths: tuple[str, ...]  # first path with a value wins
    kind: str  # num | text | enum | warning | ts | m_to_km | hhmm | bool | opening | unlocked | count
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
        used = self.paths[0]
        for path in self.paths:
            raw = get_path(data, path)
            if raw is not None:
                used = path
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
        if kind in ("enum", "warning"):
            return None if isinstance(raw, (dict, list)) else humanize_enum(raw, used.rsplit(".", 1)[-1])
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
            return len(raw) if isinstance(raw, (list, dict)) else None
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
    _s("availability_status", "availability", "availabilityStatus", "Availability", "Disponibilidad", "enum", icon="mdi:cloud-check"),
    _s("usage_mode", "availability", "usageMode", "Usage mode", "Modo de uso", "enum", icon="mdi:car-cog"),
    _s("unavailable_reason", "availability", "unavailableReason", "Unavailable reason", "Motivo de no disponibilidad", "enum", category=DIAG),
    # ---- battery ---------------------------------------------------------
    _s("battery_level", "battery", "batteryChargeLevelPercentage", "Battery", "Batería", device_class="battery", unit="%", state_class=M),
    _s("range", "battery", "estimatedDistanceToEmptyKm", "Range", "Autonomía", device_class="distance", unit="km", state_class=M, precision=0),
    _s("charging_status", "battery", ("chargingStatusV2", "chargingStatus"), "Charging status", "Estado de carga", "enum", icon="mdi:ev-station"),
    _s("charger_connection_status", "battery", "chargerConnectionStatus", "Charger connection", "Conexión del cargador", "enum", icon="mdi:ev-plug-type2"),
    _s("charger_power_status", "battery", "chargerPowerStatus", "Charger power status", "Estado de potencia del cargador", "enum"),
    _s("charging_type", "battery", "chargingType", "Charging type", "Tipo de carga", "enum"),
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
    _s("preconditioning_status", "battery", "manualPreconditioning.preconditioningStatus", "Preconditioning", "Preacondicionamiento", "enum", icon="mdi:air-conditioner"),
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
    _s("alarm", "exterior", "alarm", "Alarm", "Alarma", "enum", icon="mdi:alarm-light"),
    # ---- health ----------------------------------------------------------
    _s("days_to_service", "health", "daysToService", "Days to service", "Días hasta el servicio", device_class="duration", unit="d", state_class=M),
    _s("distance_to_service", "health", "distanceToServiceKm", "Distance to service", "Distancia hasta el servicio", device_class="distance", unit="km", state_class=M, precision=0),
    _s("engine_hours_to_service", "health", "engineHoursToService", "Engine hours to service", "Horas de motor hasta el servicio", unit="h", state_class=M, enabled=False),
    _s("service_warning", "health", "serviceWarning", "Service warning", "Aviso de servicio", "warning", icon="mdi:wrench-clock"),
    _s("brake_fluid_warning", "health", "brakeFluidLevelWarning", "Brake fluid warning", "Aviso líquido de frenos", "warning", category=DIAG),
    _s("coolant_warning", "health", "engineCoolantLevelWarning", "Coolant warning", "Aviso refrigerante", "warning", category=DIAG),
    _s("oil_warning", "health", "oilLevelWarning", "Oil level warning", "Aviso nivel de aceite", "warning", category=DIAG, enabled=False),
    _s("washer_fluid_warning", "health", "washerFluidLevelWarning", "Washer fluid warning", "Aviso líquido lavaparabrisas", "warning", category=DIAG),
    _s("low_voltage_battery_warning", "health", "lowVoltageBatteryWarning", "12 V battery warning", "Aviso batería de 12 V", "warning", category=DIAG),
    _s("tyre_pressure_front_left", "health", "frontLeftTyrePressureKpa", "Tyre pressure front left", "Presión neumático delantero izq.", device_class="pressure", unit="kPa", state_class=M, precision=0),
    _s("tyre_pressure_front_right", "health", "frontRightTyrePressureKpa", "Tyre pressure front right", "Presión neumático delantero der.", device_class="pressure", unit="kPa", state_class=M, precision=0),
    _s("tyre_pressure_rear_left", "health", "rearLeftTyrePressureKpa", "Tyre pressure rear left", "Presión neumático trasero izq.", device_class="pressure", unit="kPa", state_class=M, precision=0),
    _s("tyre_pressure_rear_right", "health", "rearRightTyrePressureKpa", "Tyre pressure rear right", "Presión neumático trasero der.", device_class="pressure", unit="kPa", state_class=M, precision=0),
    _s("tyre_reference_front", "health", "frontTyresReferencePressureKpa", "Front tyre reference pressure", "Presión recomendada eje delantero", device_class="pressure", unit="kPa", state_class=M, category=DIAG, precision=0),
    _s("tyre_reference_rear", "health", "rearTyresReferencePressureKpa", "Rear tyre reference pressure", "Presión recomendada eje trasero", device_class="pressure", unit="kPa", state_class=M, category=DIAG, precision=0),
    _s("tyre_warning_front_left", "health", "frontLeftTyrePressureWarning", "Tyre warning front left", "Aviso neumático delantero izq.", "warning", category=DIAG),
    _s("tyre_warning_front_right", "health", "frontRightTyrePressureWarning", "Tyre warning front right", "Aviso neumático delantero der.", "warning", category=DIAG),
    _s("tyre_warning_rear_left", "health", "rearLeftTyrePressureWarning", "Tyre warning rear left", "Aviso neumático trasero izq.", "warning", category=DIAG),
    _s("tyre_warning_rear_right", "health", "rearRightTyrePressureWarning", "Tyre warning rear right", "Aviso neumático trasero der.", "warning", category=DIAG),
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
    _s("target_soc_type", "target_soc", "targetSoc.chargeTargetLevelSettingType", "Charge target type", "Tipo de objetivo de carga", "enum", category=DIAG),
    _s("target_soc_source", "target_soc", "targetSoc.source", "Charge target source", "Origen del objetivo de carga", "enum", category=DIAG, enabled=False),
    # ---- parking climatization ------------------------------------------
    _s("climate_running_status", "parking_climatization", "runningStatus", "Parking climate status", "Estado climatización en parado", "enum", icon="mdi:air-conditioner"),
    _s("climate_main_running_status", "parking_climatization", "mainClimateRunningStatus", "Main climate status", "Estado climatización principal", "enum"),
    _s("climate_ventilation", "parking_climatization", "ventilation", "Ventilation", "Ventilación", "enum"),
    _s("climate_current_temperature", "parking_climatization", "currentCompartmentTemperatureCelsius", "Cabin temperature", "Temperatura del habitáculo", device_class="temperature", unit="°C", state_class=M, precision=1),
    _s("climate_requested_temperature", "parking_climatization", "requestedCompartmentTemperatureCelsius", "Requested cabin temperature", "Temperatura solicitada", device_class="temperature", unit="°C", state_class=M, precision=1),
    _s("climate_started_at", "parking_climatization", "startedAt", "Climate started at", "Climatización iniciada", "ts", device_class="timestamp", category=DIAG),
    _s("climate_ending_at", "parking_climatization", "endingAt", "Climate ending at", "Climatización termina", "ts", device_class="timestamp", category=DIAG),
    _s("climate_start_reason", "parking_climatization", "startReason", "Climate start reason", "Motivo de inicio", "enum", category=DIAG),
    # ---- pre-cleaning ----------------------------------------------------
    _s("pre_cleaning_status", "pre_cleaning", "runningStatus", "Pre-cleaning status", "Estado limpieza previa", "enum", icon="mdi:air-filter"),
    _s("air_quality_index", "pre_cleaning", "measuredAirQualityIndex", "Air quality index", "Índice de calidad del aire", state_class=M, icon="mdi:air-filter"),
    _s("particulate_matter_25", "pre_cleaning", "measuredParticulateMatter25", "Particulate matter PM2.5", "Partículas PM2.5", state_class=M),
    _s("pre_cleaning_last_cycle", "pre_cleaning", "lastCycleCompleted", "Last pre-cleaning cycle", "Último ciclo de limpieza previa", "ts", device_class="timestamp", category=DIAG),
    _s("pre_cleaning_error", "pre_cleaning", "error", "Pre-cleaning error", "Error limpieza previa", "enum", category=DIAG),
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


_EXTRA_SPECS: tuple[Spec, ...] = (
    # ---- battery: discharge info (bidirectional charging; units not documented)
    _s("discharge_energy_available", "battery", "dischargeInfo.energyAvailable", "Discharge energy available", "Energía disponible para descarga", category=DIAG, enabled=False),
    _s("discharge_energy_increase", "battery", "dischargeInfo.energyAvailableIncrease", "Discharge energy increase", "Aumento de energía para descarga", category=DIAG, enabled=False),
    _s("discharge_power_limit", "battery", "dischargeInfo.powerLimit", "Discharge power limit", "Límite de potencia de descarga", category=DIAG, enabled=False),
    # ---- health: all light warnings summarised (raw values in attributes) -----
    _s("light_warnings", "health", "lightWarnings", "Light warnings reported", "Luces reportadas", "count", category=DIAG, enabled=False, icon="mdi:car-light-high"),
    # ---- parking climatization extras ------------------------------------
    _s("climate_seat_front_left", "parking_climatization", "requestedFrontLeftSeat", "Requested seat heating front left", "Calefacción asiento delantero izq. solicitada", "enum", enabled=False, icon="mdi:car-seat-heater"),
    _s("climate_seat_front_right", "parking_climatization", "requestedFrontRightSeat", "Requested seat heating front right", "Calefacción asiento delantero der. solicitada", "enum", enabled=False, icon="mdi:car-seat-heater"),
    _s("climate_seat_rear_left", "parking_climatization", "requestedRearLeftSeat", "Requested seat heating rear left", "Calefacción asiento trasero izq. solicitada", "enum", enabled=False, icon="mdi:car-seat-heater"),
    _s("climate_seat_rear_right", "parking_climatization", "requestedRearRightSeat", "Requested seat heating rear right", "Calefacción asiento trasero der. solicitada", "enum", enabled=False, icon="mdi:car-seat-heater"),
    _s("climate_steering_wheel", "parking_climatization", "requestedSteeringWheelHeating", "Requested steering wheel heating", "Calefacción del volante solicitada", "enum", enabled=False, icon="mdi:steering"),
    _s("climate_errors", "parking_climatization", "errors", "Parking climate errors", "Errores de climatización en parado", "count", category=DIAG),
    _s("climate_warnings", "parking_climatization", "warnings", "Parking climate warnings", "Avisos de climatización en parado", "count", category=DIAG),
)

# Energy consumption breakdown (battery endpoint), generated to avoid 16 near-identical lines.
_ENERGY_GROUPS = (
    # key, API suffix, label per language
    ("since_charge", "SinceCharge", {"en": "since charge", "es": "desde la carga", "fr": "depuis la charge", "de": "seit der Ladung"}),
    ("manual", "Manual", {"en": "manual trip", "es": "viaje manual", "fr": "trajet manuel", "de": "manuelle Fahrt"}),
    ("automatic", "Automatic", {"en": "automatic trip", "es": "viaje automático", "fr": "trajet automatique", "de": "automatische Fahrt"}),
)
_ENERGY_CATEGORIES = (
    ("driving", {"en": "driving", "es": "conducción", "fr": "conduite", "de": "Fahren"}),
    ("climate", {"en": "climate", "es": "climatización", "fr": "climatisation", "de": "Klima"}),
    ("battery", {"en": "battery", "es": "batería", "fr": "batterie", "de": "Batterie"}),
    ("other", {"en": "other", "es": "otros", "fr": "autres", "de": "Sonstiges"}),
)
_ENERGY_BASE = {"en": "Energy", "es": "Energía", "fr": "Énergie", "de": "Energie"}
_SHARE_BASE = {"en": "Energy share", "es": "Reparto de energía", "fr": "Part d'énergie", "de": "Energieanteil"}

# Names of generated specs in every language: {spec key: {lang: name}}
GENERATED_NAMES: dict[str, dict[str, str]] = {}


def _generated_energy_specs() -> tuple[Spec, ...]:
    out: list[Spec] = []
    for group, suffix, glabel in _ENERGY_GROUPS:
        for cat, clabel in _ENERGY_CATEGORIES:
            key = f"energy_{group}_{cat}"
            GENERATED_NAMES[key] = {
                lang: f"{_ENERGY_BASE[lang]} {glabel[lang]}: {clabel[lang]}" for lang in ("en", "es", "fr", "de")
            }
            out.append(
                _s(key, "battery", f"energyConsumptionWh{suffix}.{cat}",
                   GENERATED_NAMES[key]["en"], GENERATED_NAMES[key]["es"],
                   device_class="energy", unit="Wh", enabled=(group == "since_charge"), precision=0)
            )
    group, suffix, glabel = _ENERGY_GROUPS[0]
    for cat, clabel in _ENERGY_CATEGORIES:
        key = f"energy_share_{cat}"
        GENERATED_NAMES[key] = {
            lang: f"{_SHARE_BASE[lang]} {glabel[lang]}: {clabel[lang]}" for lang in ("en", "es", "fr", "de")
        }
        out.append(
            _s(key, "battery", f"energyConsumptionPercentageSinceCharge.{cat}",
               GENERATED_NAMES[key]["en"], GENERATED_NAMES[key]["es"],
               unit="%", state_class=M, enabled=False, precision=0)
        )
    return tuple(out)


SPECS = SPECS + _EXTRA_SPECS + _generated_energy_specs()

# --------------------------------------------------------------------------
# Unmapped-field discovery
# --------------------------------------------------------------------------

# Bookkeeping keys that never become entities.
_IGNORED_KEYS = {
    "vin", "meta", "metaReceivedAt", "metaEventId", "timestamp", "updatedAt",
    "updatedAtTimestamp", "sourceUpdatedAt", "sourceUpdatedAtTimestamp",
    "domain", "syncStatus", "utc0", "id",
    # skipped on purpose: duplicates of mapped metric fields / deprecated
    "estimatedDistanceToEmptyMiles", "runtimeLeftMinutes",
}


def _leaves(data: Any, prefix: str = "") -> list[str]:
    """Dotted paths of the deepest fields in a payload (lists count as leaves)."""
    paths: list[str] = []
    if not isinstance(data, dict):
        return paths
    for key, value in data.items():
        if key in _IGNORED_KEYS:
            continue
        path = f"{prefix}{key}"
        if isinstance(value, dict) and set(value) - {"seconds", "nanos"}:
            paths.extend(_leaves(value, f"{path}."))
        else:
            paths.append(path)
    return paths


# Fields read by platforms that are not catalog specs (the GPS device tracker).
_TRACKER_PATHS = {"location": ("coordinate.latitude", "coordinate.longitude")}


def unmapped_fields(endpoint: str, payload: dict[str, Any] | None) -> list[str]:
    """Fields present in a payload that no entity reads."""
    mapped = [p for s in SPECS if s.endpoint == endpoint for p in s.paths]
    mapped.extend(_TRACKER_PATHS.get(endpoint, ()))
    result = []
    for path in _leaves(payload):
        if any(path == m or path.startswith(m + ".") for m in mapped):
            continue
        result.append(path)
    return sorted(result)

SPECS_BY_KEY = {s.key: s for s in SPECS}
assert len(SPECS_BY_KEY) == len(SPECS), "duplicate spec key"
assert all(s.endpoint in ENDPOINTS for s in SPECS), "unknown endpoint in spec"

# Account-level diagnostic entities (not tied to a VIN)
ACCOUNT_ENTITIES = {
    "api_calls_today": ("API calls today", "Llamadas a la API hoy"),
    "vehicle_count": ("Vehicles", "Vehículos"),
    "unmapped_fields": ("Unmapped fields", "Campos sin mapear"),
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


# --------------------------------------------------------------------------
# Derived ("cooked") values: computed from several API fields
# --------------------------------------------------------------------------

# key: (en, es, fr, de)
DERIVED_NAMES = {
    "range_at_full": (
        "Estimated range at 100%",
        "Autonomía estimada al 100 %",
        "Autonomie estimée à 100 %",
        "Geschätzte Reichweite bei 100 %",
    ),
    "charge_end_time": (
        "Charge end time",
        "Fecha y hora de fin de carga",
        "Heure de fin de charge",
        "Ladeende",
    ),
    "charging_power_calc": (
        "Charging power (calculated)",
        "Potencia de carga (calculada)",
        "Puissance de charge (calculée)",
        "Ladeleistung (berechnet)",
    ),
    "odometer_month": (
        "Distance this month",
        "Kilometraje del mes",
        "Distance ce mois-ci",
        "Strecke diesen Monat",
    ),
}
IMAGE_NAMES = {  # key: (en, es, fr, de)
    "status": ("Vehicle status", "Estado del vehículo", "État du véhicule", "Fahrzeugstatus"),
}

# Below this battery level a linear extrapolation to 100 % is too noisy.
MIN_SOC_FOR_RANGE_ESTIMATE = 5.0

_NOT_CHARGING_TOKENS = {
    "NOT", "NO", "STOPPED", "STOP", "DONE", "COMPLETE", "COMPLETED", "IDLE",
    "ERROR", "FAULT", "SCHEDULED", "PAUSED", "UNSPECIFIED", "DISCONNECTED",
}


def _spec_value(key: str, payload: dict[str, Any] | None) -> Any:
    return SPECS_BY_KEY[key].extract(payload)


def range_at_full(battery: dict[str, Any] | None) -> float | None:
    """Range extrapolated linearly to a 100 % battery."""
    level = _spec_value("battery_level", battery)
    rng = _spec_value("range", battery)
    if level is None or rng is None or rng <= 0 or level < MIN_SOC_FOR_RANGE_ESTIMATE:
        return None
    return round(min(rng * 100.0 / level, 2000.0))


def is_charging(battery: dict[str, Any] | None) -> bool | None:
    """True/False when it can be told from the payload, else None.

    The charging power is the primary signal because the status strings are
    not documented; the status text is used only when no power is reported.
    """
    power = _spec_value("charging_power", battery)
    if power is not None:
        return power > 0
    status = _spec_value("charging_status", battery)
    if status is None:
        return None
    tokens = _tokens(status)
    return "CHARGING" in tokens and not tokens & _NOT_CHARGING_TOKENS


def charge_end_time(battery: dict[str, Any] | None, now: datetime) -> datetime | None:
    """Moment the charge is expected to finish (reported time + minutes left)."""
    minutes = _spec_value("time_to_full", battery)
    if minutes is None or minutes <= 0 or is_charging(battery) is not True:
        return None
    base = payload_timestamp(battery) or now
    end = (base + timedelta(minutes=minutes)).replace(second=0, microsecond=0)
    return end if end >= now - timedelta(minutes=1) else None


def charging_power_kw(battery: dict[str, Any] | None) -> float | None:
    """Charging power in kW from the reported voltage and current (V x A)."""
    volts = _spec_value("charging_voltage", battery)
    amps = _spec_value("charging_current", battery)
    if volts is None or amps is None or volts < 0 or amps < 0:
        return None
    return round(volts * amps / 1000.0, 2)


class MonthlyTracker:
    """Distance driven in the current calendar month, from odometer readings.

    The first reading ever seen is the baseline, so the first month only counts
    from when the integration started. State is persisted by the caller.
    """

    def __init__(self) -> None:
        self.month: str | None = None  # "YYYY-MM"
        self.start: float | None = None
        self.last: float | None = None
        self.previous_month: str | None = None
        self.previous_month_km: float | None = None
        self.tracking_since: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MonthlyTracker":
        tracker = cls()
        for field in ("month", "start", "last", "previous_month", "previous_month_km", "tracking_since"):
            setattr(tracker, field, data.get(field))
        return tracker

    def to_dict(self) -> dict[str, Any]:
        return {
            f: getattr(self, f)
            for f in ("month", "start", "last", "previous_month", "previous_month_km", "tracking_since")
        }

    def update(self, odometer_km: float, month: str, today: str) -> float:
        """Register a reading and return the km driven this month."""
        if self.month is None or self.start is None:
            self.month, self.start, self.tracking_since = month, odometer_km, today
        elif month != self.month:
            if self.last is not None:
                self.previous_month = self.month
                self.previous_month_km = round(self.last - self.start, 1)
            self.start = self.last if self.last is not None else odometer_km
            self.month = month
        if odometer_km < self.start:  # odometer replaced or glitch
            self.start = odometer_km
        self.last = odometer_km
        return round(odometer_km - self.start, 1)


DERIVED_SENSORS = tuple(DERIVED_NAMES)


def derived_available(key: str, vehicle_data: dict[str, Any]) -> bool:
    """Whether the inputs of a derived sensor are reported by this vehicle."""
    battery = vehicle_data.get("battery")
    if key == "range_at_full":
        return _spec_value("battery_level", battery) is not None and _spec_value("range", battery) is not None
    if key == "charge_end_time":
        return _spec_value("time_to_full", battery) is not None
    if key == "charging_power_calc":
        return charging_power_kw(battery) is not None
    if key == "odometer_month":
        return _spec_value("odometer", vehicle_data.get("odometer")) is not None
    return False
