"""Constants for the Polestar Data Portal integration."""

DOMAIN = "polestar_data_portal"

CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_ACCOUNT_ID = "account_id"

CONF_SCAN_INTERVAL = "scan_interval"  # minutes
CONF_ENDPOINTS = "endpoints"

# How long to skip an endpoint after a 404/403 for a given VIN (seconds).
UNAVAILABLE_RETRY_SECONDS = 6 * 3600
# How often to refresh the VIN list (seconds).
VEHICLE_REFRESH_SECONDS = 24 * 3600
# Max parallel requests per poll.
MAX_CONCURRENCY = 4
