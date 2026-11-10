#!/usr/bin/env python3
"""Generate strings.json and translations/en.json from catalog.py.

Translations into other languages are managed in Crowdin (see crowdin.yml):
Crowdin takes translations/en.json as its source and opens pull requests with
the translated files. By default this script therefore writes ONLY the English
files and never touches es/fr/de/... so it cannot overwrite Crowdin's work.

The Spanish names live in catalog.py and the French/German tables below. They
are kept only to seed or rebuild those three languages:

    python3 tools/build_translations.py          # English only (normal use)
    python3 tools/build_translations.py --seed   # also es/fr/de (overwrites them!)

Run from the repository root.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / "custom_components" / "polestar_data_portal"
LANGS = ("en", "es", "fr", "de")  # languages --seed can build

# Load catalog.py without importing the package (which needs Home Assistant).
spec = importlib.util.spec_from_file_location("catalog", COMP / "catalog.py")
catalog = importlib.util.module_from_spec(spec)
sys.modules["catalog"] = catalog
spec.loader.exec_module(catalog)

# --------------------------------------------------------------------------
# Config flow / options texts
# --------------------------------------------------------------------------

_FIELDS = {
    "en": {"client_id": "Client ID", "client_secret": "Client secret", "account_id": "Account ID (x-client-id)"},
    "es": {"client_id": "Client ID", "client_secret": "Client secret", "account_id": "Account ID (x-client-id)"},
    "fr": {"client_id": "Client ID", "client_secret": "Client secret", "account_id": "Account ID (x-client-id)"},
    "de": {"client_id": "Client ID", "client_secret": "Client Secret", "account_id": "Account ID (x-client-id)"},
}

_TEXT = {
    "en": {
        "user_title": "Polestar Data Portal",
        "user_desc": "Create API credentials in the Polestar data portal (data-portal.polestar.com → Credential) and enter them here. The Account ID is shown on the API Documentation page (x-client-id).",
        "reauth_title": "Re-enter your API credentials",
        "reauth_desc": "The Polestar Data Portal rejected the stored credentials. Enter valid ones.",
        "invalid_auth": "The client ID or secret was rejected.",
        "cannot_connect": "Could not reach the Polestar Data Portal. Try again later.",
        "no_vehicle_access": "These credentials are not authorised to list vehicles. Check the Account ID.",
        "no_vehicles": "No vehicles are available for this account (only vehicles registered in an eligible EU/EEA market are listed).",
        "unknown": "Unexpected error. Check the Home Assistant log.",
        "already_configured": "These credentials are already configured.",
        "reauth_successful": "Credentials updated.",
        "opt_title": "Polling options",
        "opt_desc": "The portal allows 10,000 API calls per day. Each enabled endpoint costs one call per vehicle and poll. You have {vehicles} vehicle(s); the integration keeps the estimate under {limit} calls per day.",
        "opt_interval": "Polling interval (minutes)",
        "opt_endpoints": "Data to fetch",
        "no_endpoints": "Select at least one kind of data.",
        "too_many_calls": "This would exceed the daily API limit. Increase the interval or disable some data.",
    },
    "es": {
        "user_title": "Polestar Data Portal",
        "user_desc": "Crea credenciales de API en el portal de datos de Polestar (data-portal.polestar.com → Credential) e introdúcelas aquí. El Account ID aparece en la página API Documentation (x-client-id).",
        "reauth_title": "Vuelve a introducir las credenciales de API",
        "reauth_desc": "El portal rechazó las credenciales guardadas. Introduce unas válidas.",
        "invalid_auth": "Se rechazó el Client ID o el secreto.",
        "cannot_connect": "No se pudo conectar con el Polestar Data Portal. Inténtalo más tarde.",
        "no_vehicle_access": "Estas credenciales no pueden listar vehículos. Revisa el Account ID.",
        "no_vehicles": "No hay vehículos disponibles para esta cuenta (solo se listan los matriculados en un mercado UE/EEE elegible).",
        "unknown": "Error inesperado. Revisa el registro de Home Assistant.",
        "already_configured": "Estas credenciales ya están configuradas.",
        "reauth_successful": "Credenciales actualizadas.",
        "opt_title": "Opciones de sondeo",
        "opt_desc": "El portal permite 10.000 llamadas a la API al día. Cada tipo de dato activado cuesta una llamada por vehículo y sondeo. Tienes {vehicles} vehículo(s); la integración mantiene la estimación por debajo de {limit} llamadas al día.",
        "opt_interval": "Intervalo de sondeo (minutos)",
        "opt_endpoints": "Datos a consultar",
        "no_endpoints": "Selecciona al menos un tipo de dato.",
        "too_many_calls": "Esto superaría el límite diario de la API. Aumenta el intervalo o desactiva algunos datos.",
    },
    "fr": {
        "user_title": "Polestar Data Portal",
        "user_desc": "Créez des identifiants d'API dans le portail de données Polestar (data-portal.polestar.com → Credential) et saisissez-les ici. L'Account ID figure sur la page API Documentation (x-client-id).",
        "reauth_title": "Saisissez à nouveau vos identifiants d'API",
        "reauth_desc": "Le Polestar Data Portal a rejeté les identifiants enregistrés. Saisissez des identifiants valides.",
        "invalid_auth": "Le Client ID ou le secret a été rejeté.",
        "cannot_connect": "Impossible de joindre le Polestar Data Portal. Réessayez plus tard.",
        "no_vehicle_access": "Ces identifiants ne sont pas autorisés à lister les véhicules. Vérifiez l'Account ID.",
        "no_vehicles": "Aucun véhicule n'est disponible pour ce compte (seuls les véhicules immatriculés dans un marché UE/EEE éligible sont listés).",
        "unknown": "Erreur inattendue. Consultez le journal de Home Assistant.",
        "already_configured": "Ces identifiants sont déjà configurés.",
        "reauth_successful": "Identifiants mis à jour.",
        "opt_title": "Options d'interrogation",
        "opt_desc": "Le portail autorise 10 000 appels d'API par jour. Chaque type de données activé coûte un appel par véhicule et par interrogation. Vous avez {vehicles} véhicule(s) ; l'intégration maintient l'estimation sous {limit} appels par jour.",
        "opt_interval": "Intervalle d'interrogation (minutes)",
        "opt_endpoints": "Données à récupérer",
        "no_endpoints": "Sélectionnez au moins un type de données.",
        "too_many_calls": "Cela dépasserait la limite quotidienne de l'API. Augmentez l'intervalle ou désactivez certaines données.",
    },
    "de": {
        "user_title": "Polestar Data Portal",
        "user_desc": "Erstelle API-Zugangsdaten im Polestar-Datenportal (data-portal.polestar.com → Credential) und gib sie hier ein. Die Account ID steht auf der Seite API Documentation (x-client-id).",
        "reauth_title": "API-Zugangsdaten erneut eingeben",
        "reauth_desc": "Das Polestar Data Portal hat die gespeicherten Zugangsdaten abgelehnt. Gib gültige Zugangsdaten ein.",
        "invalid_auth": "Client ID oder Secret wurde abgelehnt.",
        "cannot_connect": "Das Polestar Data Portal ist nicht erreichbar. Versuche es später erneut.",
        "no_vehicle_access": "Diese Zugangsdaten dürfen keine Fahrzeuge auflisten. Prüfe die Account ID.",
        "no_vehicles": "Für dieses Konto sind keine Fahrzeuge verfügbar (es werden nur Fahrzeuge aufgelistet, die in einem berechtigten EU/EWR-Markt zugelassen sind).",
        "unknown": "Unerwarteter Fehler. Prüfe das Home-Assistant-Protokoll.",
        "already_configured": "Diese Zugangsdaten sind bereits eingerichtet.",
        "reauth_successful": "Zugangsdaten aktualisiert.",
        "opt_title": "Abfrageoptionen",
        "opt_desc": "Das Portal erlaubt 10.000 API-Aufrufe pro Tag. Jede aktivierte Datenart kostet einen Aufruf pro Fahrzeug und Abfrage. Du hast {vehicles} Fahrzeug(e); die Integration hält die Schätzung unter {limit} Aufrufen pro Tag.",
        "opt_interval": "Abfrageintervall (Minuten)",
        "opt_endpoints": "Abzurufende Daten",
        "no_endpoints": "Wähle mindestens eine Datenart aus.",
        "too_many_calls": "Das würde das tägliche API-Limit überschreiten. Erhöhe das Intervall oder deaktiviere einige Daten.",
    },
}

# --------------------------------------------------------------------------
# Names: endpoints, account entities, generic entities
# --------------------------------------------------------------------------

ENDPOINT_NAMES = {  # key: (fr, de)
    "availability": ("Disponibilité", "Verfügbarkeit"),
    "battery": ("Batterie et charge", "Batterie und Laden"),
    "exterior": ("Portes, vitres et verrouillage", "Türen, Fenster und Verriegelung"),
    "health": ("État (entretien, pneus, alertes)", "Zustand (Service, Reifen, Warnungen)"),
    "location": ("Position", "Standort"),
    "odometer": ("Kilométrage et trajets", "Kilometerstand und Fahrten"),
    "target_soc": ("Objectif de charge", "Ladeziel"),
    "parking_climatization": ("Climatisation à l'arrêt", "Standklimatisierung"),
    "pre_cleaning": ("Prépurification de l'habitacle", "Innenraum-Vorreinigung"),
    "amp_limit": ("Limite de courant de charge", "Ladestrombegrenzung"),
    "charge_now": ("Charge immédiate", "Sofort laden"),
    "global_charge_timer": ("Minuterie de charge globale", "Globaler Ladetimer"),
    "is_at_charge_location": ("Sur un lieu de charge", "An einem Ladeort"),
    "charge_locations": ("Lieux de charge", "Ladeorte"),
}

ACCOUNT_NAMES = {  # key: (fr, de)
    "api_calls_today": ("Appels API aujourd'hui", "API-Aufrufe heute"),
    "vehicle_count": ("Véhicules", "Fahrzeuge"),
    "unmapped_fields": ("Champs non mappés", "Nicht zugeordnete Felder"),
}
LAST_UPDATE = ("Dernière mise à jour", "Letzte Aktualisierung")
TRACKER = ("Position", "Standort")

SPEC_NAMES = {  # key: (fr, de)
    "availability_status": ("Disponibilité", "Verfügbarkeit"),
    "usage_mode": ("Mode d'utilisation", "Nutzungsmodus"),
    "unavailable_reason": ("Motif d'indisponibilité", "Grund der Nichtverfügbarkeit"),
    "battery_level": ("Batterie", "Batterie"),
    "range": ("Autonomie", "Reichweite"),
    "charging_status": ("État de charge", "Ladestatus"),
    "charger_connection_status": ("Connexion du chargeur", "Ladeverbindung"),
    "charger_power_status": ("État d'alimentation du chargeur", "Ladestromstatus"),
    "charging_type": ("Type de charge", "Ladeart"),
    "charging_power": ("Puissance de charge", "Ladeleistung"),
    "charging_current": ("Courant de charge", "Ladestrom"),
    "charging_voltage": ("Tension de charge", "Ladespannung"),
    "time_to_full": ("Temps avant charge complète", "Zeit bis voll geladen"),
    "time_to_target_distance": ("Temps avant l'autonomie cible", "Zeit bis zur Zielreichweite"),
    "time_to_minimum_soc": ("Temps avant la charge minimale", "Zeit bis zum Mindestladestand"),
    "consumption_average": ("Consommation moyenne", "Durchschnittsverbrauch"),
    "consumption_since_charge": ("Consommation depuis la dernière charge", "Verbrauch seit der letzten Ladung"),
    "consumption_automatic": ("Consommation (trajet automatique)", "Verbrauch (automatische Fahrt)"),
    "total_energy_consumption": ("Consommation d'énergie totale", "Gesamtenergieverbrauch"),
    "preconditioning_status": ("Préconditionnement", "Vorkonditionierung"),
    "central_lock": ("Verrouillage centralisé", "Zentralverriegelung"),
    "tailgate_lock": ("Verrouillage du hayon", "Heckklappenverriegelung"),
    "front_left_door": ("Porte avant gauche", "Tür vorne links"),
    "front_right_door": ("Porte avant droite", "Tür vorne rechts"),
    "rear_left_door": ("Porte arrière gauche", "Tür hinten links"),
    "rear_right_door": ("Porte arrière droite", "Tür hinten rechts"),
    "front_left_window": ("Vitre avant gauche", "Fenster vorne links"),
    "front_right_window": ("Vitre avant droite", "Fenster vorne rechts"),
    "rear_left_window": ("Vitre arrière gauche", "Fenster hinten links"),
    "rear_right_window": ("Vitre arrière droite", "Fenster hinten rechts"),
    "hood": ("Capot", "Motorhaube"),
    "tailgate": ("Hayon", "Heckklappe"),
    "tank_lid": ("Trappe de charge / réservoir", "Ladeklappe / Tankklappe"),
    "sunroof": ("Toit ouvrant", "Schiebedach"),
    "alarm": ("Alarme", "Alarmanlage"),
    "days_to_service": ("Jours avant l'entretien", "Tage bis zum Service"),
    "distance_to_service": ("Distance avant l'entretien", "Entfernung bis zum Service"),
    "engine_hours_to_service": ("Heures moteur avant l'entretien", "Motorstunden bis zum Service"),
    "service_warning": ("Alerte d'entretien", "Servicewarnung"),
    "brake_fluid_warning": ("Alerte liquide de frein", "Warnung Bremsflüssigkeit"),
    "coolant_warning": ("Alerte liquide de refroidissement", "Warnung Kühlmittel"),
    "oil_warning": ("Alerte niveau d'huile", "Warnung Ölstand"),
    "washer_fluid_warning": ("Alerte lave-glace", "Warnung Waschwasser"),
    "low_voltage_battery_warning": ("Alerte batterie 12 V", "Warnung 12-V-Batterie"),
    "tyre_pressure_front_left": ("Pression pneu avant gauche", "Reifendruck vorne links"),
    "tyre_pressure_front_right": ("Pression pneu avant droit", "Reifendruck vorne rechts"),
    "tyre_pressure_rear_left": ("Pression pneu arrière gauche", "Reifendruck hinten links"),
    "tyre_pressure_rear_right": ("Pression pneu arrière droit", "Reifendruck hinten rechts"),
    "tyre_reference_front": ("Pression recommandée essieu avant", "Empfohlener Reifendruck Vorderachse"),
    "tyre_reference_rear": ("Pression recommandée essieu arrière", "Empfohlener Reifendruck Hinterachse"),
    "tyre_warning_front_left": ("Alerte pneu avant gauche", "Reifenwarnung vorne links"),
    "tyre_warning_front_right": ("Alerte pneu avant droit", "Reifenwarnung vorne rechts"),
    "tyre_warning_rear_left": ("Alerte pneu arrière gauche", "Reifenwarnung hinten links"),
    "tyre_warning_rear_right": ("Alerte pneu arrière droit", "Reifenwarnung hinten rechts"),
    "speed": ("Vitesse", "Geschwindigkeit"),
    "altitude": ("Altitude", "Höhe"),
    "heading": ("Cap", "Fahrtrichtung"),
    "odometer": ("Kilométrage", "Kilometerstand"),
    "trip_manual": ("Trajet (manuel)", "Fahrt (manuell)"),
    "trip_automatic": ("Trajet (automatique)", "Fahrt (automatisch)"),
    "trip_since_charge": ("Distance depuis la dernière charge", "Strecke seit der letzten Ladung"),
    "average_speed_manual": ("Vitesse moyenne (trajet manuel)", "Durchschnittsgeschwindigkeit (manuelle Fahrt)"),
    "average_speed_automatic": ("Vitesse moyenne (trajet automatique)", "Durchschnittsgeschwindigkeit (automatische Fahrt)"),
    "average_speed_since_charge": ("Vitesse moyenne depuis la charge", "Durchschnittsgeschwindigkeit seit der Ladung"),
    "target_soc": ("Objectif de charge", "Ladeziel"),
    "target_soc_type": ("Type d'objectif de charge", "Art des Ladeziels"),
    "target_soc_source": ("Source de l'objectif de charge", "Quelle des Ladeziels"),
    "climate_running_status": ("État de la climatisation à l'arrêt", "Status der Standklimatisierung"),
    "climate_main_running_status": ("État de la climatisation principale", "Status der Hauptklimatisierung"),
    "climate_ventilation": ("Ventilation", "Belüftung"),
    "climate_current_temperature": ("Température de l'habitacle", "Innenraumtemperatur"),
    "climate_requested_temperature": ("Température demandée", "Solltemperatur"),
    "climate_started_at": ("Début de la climatisation", "Start der Klimatisierung"),
    "climate_ending_at": ("Fin de la climatisation", "Ende der Klimatisierung"),
    "climate_start_reason": ("Motif de démarrage", "Startgrund"),
    "pre_cleaning_status": ("État de la prépurification", "Status der Vorreinigung"),
    "air_quality_index": ("Indice de qualité de l'air", "Luftqualitätsindex"),
    "particulate_matter_25": ("Particules PM2,5", "Feinstaub PM2,5"),
    "pre_cleaning_last_cycle": ("Dernier cycle de prépurification", "Letzter Vorreinigungszyklus"),
    "pre_cleaning_error": ("Erreur de prépurification", "Fehler der Vorreinigung"),
    "amp_limit": ("Limite de courant de charge", "Ladestrombegrenzung"),
    "charge_now": ("Charge immédiate", "Sofort laden"),
    "global_timer_active": ("Minuterie globale active", "Globaler Timer aktiv"),
    "global_timer_start": ("Début de la minuterie globale", "Start des globalen Timers"),
    "global_timer_stop": ("Fin de la minuterie globale", "Ende des globalen Timers"),
    "charge_location_id": ("Lieu de charge actuel", "Aktueller Ladeort"),
    "charge_location_arrived": ("Arrivée au lieu de charge", "Ankunft am Ladeort"),
    "charge_locations_count": ("Lieux de charge enregistrés", "Gespeicherte Ladeorte"),
    "discharge_energy_available": ("Énergie disponible pour la décharge", "Verfügbare Entladeenergie"),
    "discharge_energy_increase": ("Augmentation de l'énergie de décharge", "Zunahme der Entladeenergie"),
    "discharge_power_limit": ("Limite de puissance de décharge", "Entladeleistungsgrenze"),
    "light_warnings": ("Feux signalés", "Gemeldete Leuchten"),
    "climate_seat_front_left": ("Siège chauffant avant gauche demandé", "Sitzheizung vorne links (Soll)"),
    "climate_seat_front_right": ("Siège chauffant avant droit demandé", "Sitzheizung vorne rechts (Soll)"),
    "climate_seat_rear_left": ("Siège chauffant arrière gauche demandé", "Sitzheizung hinten links (Soll)"),
    "climate_seat_rear_right": ("Siège chauffant arrière droit demandé", "Sitzheizung hinten rechts (Soll)"),
    "climate_steering_wheel": ("Volant chauffant demandé", "Lenkradheizung (Soll)"),
    "climate_errors": ("Erreurs de climatisation à l'arrêt", "Fehler der Standklimatisierung"),
    "climate_warnings": ("Alertes de climatisation à l'arrêt", "Warnungen der Standklimatisierung"),
}


def spec_name(spec, lang: str) -> str:
    if lang == "en":
        return spec.name_en
    if lang == "es":
        return spec.name_es
    generated = catalog.GENERATED_NAMES.get(spec.key)
    if generated:
        return generated[lang]
    return SPEC_NAMES[spec.key][0 if lang == "fr" else 1]


def build(lang: str) -> dict:
    t = _TEXT[lang]
    f = _FIELDS[lang]
    out = {
        "config": {
            "step": {
                "user": {"title": t["user_title"], "description": t["user_desc"], "data": dict(f)},
                "reauth_confirm": {"title": t["reauth_title"], "description": t["reauth_desc"], "data": dict(f)},
            },
            "error": {
                k: t[k] for k in ("invalid_auth", "cannot_connect", "no_vehicle_access", "no_vehicles", "unknown")
            },
            "abort": {"already_configured": t["already_configured"], "reauth_successful": t["reauth_successful"]},
        },
        "options": {
            "step": {
                "init": {
                    "title": t["opt_title"],
                    "description": t["opt_desc"],
                    "data": {"scan_interval": t["opt_interval"], "endpoints": t["opt_endpoints"]},
                }
            },
            "error": {"no_endpoints": t["no_endpoints"], "too_many_calls": t["too_many_calls"]},
        },
        "selector": {"endpoints": {"options": {}}},
        "entity": {"sensor": {}, "binary_sensor": {}, "device_tracker": {}, "image": {}},
    }
    idx = {"en": None, "es": None, "fr": 0, "de": 1}[lang]
    for key, ep in catalog.ENDPOINTS.items():
        if lang == "en":
            name = ep.name_en
        elif lang == "es":
            name = ep.name_es
        else:
            name = ENDPOINT_NAMES[key][idx]
        out["selector"]["endpoints"]["options"][key] = name
    for s in catalog.SPECS:
        out["entity"][s.platform][s.key] = {"name": spec_name(s, lang)}
    for key, names in catalog.ACCOUNT_ENTITIES.items():
        name = names[0] if lang == "en" else names[1] if lang == "es" else ACCOUNT_NAMES[key][idx]
        out["entity"]["sensor"][key] = {"name": name}
    li = {"en": 0, "es": 1, "fr": 2, "de": 3}[lang]
    for key, names in catalog.DERIVED_NAMES.items():
        out["entity"]["sensor"][key] = {"name": names[li]}
    for key, names in catalog.IMAGE_NAMES.items():
        out["entity"]["image"][key] = {"name": names[li]}
    key, en, es = catalog.VEHICLE_LAST_UPDATE
    out["entity"]["sensor"][key] = {"name": en if lang == "en" else es if lang == "es" else LAST_UPDATE[idx]}
    tracker = catalog.TRACKER_NAME
    out["entity"]["device_tracker"]["location"] = {
        "name": tracker[0] if lang == "en" else tracker[1] if lang == "es" else TRACKER[idx]
    }
    return out


def main() -> None:
    seed = "--seed" in sys.argv[1:]
    langs = LANGS if seed else ("en",)
    tdir = COMP / "translations"
    tdir.mkdir(exist_ok=True)
    built = {lang: build(lang) for lang in LANGS}

    # Same structure in every language.
    def shape(node):
        return {k: shape(v) for k, v in node.items()} if isinstance(node, dict) else None

    reference = shape(built["en"])
    for lang in LANGS:
        if shape(built[lang]) != reference:
            raise SystemExit(f"Translation structure mismatch in {lang}")

    for lang in langs:
        text = json.dumps(built[lang], indent=2, ensure_ascii=False) + "\n"
        (tdir / f"{lang}.json").write_text(text, encoding="utf-8")
        if lang == "en":
            (COMP / "strings.json").write_text(text, encoding="utf-8")
    print("Wrote strings.json and translations/" + ", ".join(f"{l}.json" for l in langs))


if __name__ == "__main__":
    main()
