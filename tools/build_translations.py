#!/usr/bin/env python3
"""Generate strings.json and translations/{en,es}.json from the catalog.

Run from the repository root:  python3 tools/build_translations.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / "custom_components" / "polestar_data_portal"

# Load catalog.py without importing the package (which needs Home Assistant).
spec = importlib.util.spec_from_file_location("catalog", COMP / "catalog.py")
catalog = importlib.util.module_from_spec(spec)
sys.modules["catalog"] = catalog
spec.loader.exec_module(catalog)

STATIC = {
    "en": {
        "config": {
            "step": {
                "user": {
                    "title": "Polestar Data Portal",
                    "description": "Create API credentials in the Polestar data portal (data-portal.polestar.com → Credential) and enter them here. The Account ID is shown on the API Documentation page (x-client-id).",
                    "data": {
                        "client_id": "Client ID",
                        "client_secret": "Client secret",
                        "account_id": "Account ID (x-client-id)",
                    },
                },
                "reauth_confirm": {
                    "title": "Re-enter your API credentials",
                    "description": "The Polestar Data Portal rejected the stored credentials. Enter valid ones.",
                    "data": {
                        "client_id": "Client ID",
                        "client_secret": "Client secret",
                        "account_id": "Account ID (x-client-id)",
                    },
                },
            },
            "error": {
                "invalid_auth": "The client ID or secret was rejected.",
                "cannot_connect": "Could not reach the Polestar Data Portal. Try again later.",
                "no_vehicle_access": "These credentials are not authorised to list vehicles. Check the Account ID.",
                "no_vehicles": "No vehicles are available for this account (only vehicles registered in an eligible EU/EEA market are listed).",
                "unknown": "Unexpected error. Check the Home Assistant log.",
            },
            "abort": {
                "already_configured": "These credentials are already configured.",
                "reauth_successful": "Credentials updated.",
            },
        },
        "options": {
            "step": {
                "init": {
                    "title": "Polling options",
                    "description": "The portal allows 10,000 API calls per day. Each enabled endpoint costs one call per vehicle and poll. You have {vehicles} vehicle(s); the integration keeps the estimate under {limit} calls per day.",
                    "data": {
                        "scan_interval": "Polling interval (minutes)",
                        "endpoints": "Data to fetch",
                    },
                }
            },
            "error": {
                "no_endpoints": "Select at least one kind of data.",
                "too_many_calls": "This would exceed the daily API limit. Increase the interval or disable some data.",
            },
        },
        "selector": {"endpoints": {"options": {}}},
        "entity": {"sensor": {}, "binary_sensor": {}, "device_tracker": {}},
    },
    "es": {
        "config": {
            "step": {
                "user": {
                    "title": "Polestar Data Portal",
                    "description": "Crea credenciales de API en el portal de datos de Polestar (data-portal.polestar.com → Credential) e introdúcelas aquí. El Account ID aparece en la página API Documentation (x-client-id).",
                    "data": {
                        "client_id": "Client ID",
                        "client_secret": "Client secret",
                        "account_id": "Account ID (x-client-id)",
                    },
                },
                "reauth_confirm": {
                    "title": "Vuelve a introducir las credenciales de API",
                    "description": "El portal rechazó las credenciales guardadas. Introduce unas válidas.",
                    "data": {
                        "client_id": "Client ID",
                        "client_secret": "Client secret",
                        "account_id": "Account ID (x-client-id)",
                    },
                },
            },
            "error": {
                "invalid_auth": "Se rechazó el Client ID o el secreto.",
                "cannot_connect": "No se pudo conectar con el Polestar Data Portal. Inténtalo más tarde.",
                "no_vehicle_access": "Estas credenciales no pueden listar vehículos. Revisa el Account ID.",
                "no_vehicles": "No hay vehículos disponibles para esta cuenta (solo se listan los matriculados en un mercado UE/EEE elegible).",
                "unknown": "Error inesperado. Revisa el registro de Home Assistant.",
            },
            "abort": {
                "already_configured": "Estas credenciales ya están configuradas.",
                "reauth_successful": "Credenciales actualizadas.",
            },
        },
        "options": {
            "step": {
                "init": {
                    "title": "Opciones de sondeo",
                    "description": "El portal permite 10.000 llamadas a la API al día. Cada tipo de dato activado cuesta una llamada por vehículo y sondeo. Tienes {vehicles} vehículo(s); la integración mantiene la estimación por debajo de {limit} llamadas al día.",
                    "data": {
                        "scan_interval": "Intervalo de sondeo (minutos)",
                        "endpoints": "Datos a consultar",
                    },
                }
            },
            "error": {
                "no_endpoints": "Selecciona al menos un tipo de dato.",
                "too_many_calls": "Esto superaría el límite diario de la API. Aumenta el intervalo o desactiva algunos datos.",
            },
        },
        "selector": {"endpoints": {"options": {}}},
        "entity": {"sensor": {}, "binary_sensor": {}, "device_tracker": {}},
    },
}


def build(lang: str) -> dict:
    out = json.loads(json.dumps(STATIC[lang]))
    idx = 0 if lang == "en" else 1
    for key, ep in catalog.ENDPOINTS.items():
        out["selector"]["endpoints"]["options"][key] = (ep.name_en, ep.name_es)[idx]
    for s in catalog.SPECS:
        out["entity"][s.platform][s.key] = {"name": (s.name_en, s.name_es)[idx]}
    for key, names in catalog.ACCOUNT_ENTITIES.items():
        out["entity"]["sensor"][key] = {"name": names[idx]}
    key, en, es = catalog.VEHICLE_LAST_UPDATE
    out["entity"]["sensor"][key] = {"name": (en, es)[idx]}
    out["entity"]["device_tracker"]["location"] = {"name": catalog.TRACKER_NAME[idx]}
    return out


def main() -> None:
    tdir = COMP / "translations"
    tdir.mkdir(exist_ok=True)
    for lang in ("en", "es"):
        data = build(lang)
        (tdir / f"{lang}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if lang == "en":
            (COMP / "strings.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Wrote strings.json, translations/en.json, translations/es.json")


if __name__ == "__main__":
    main()
