# Polestar Data Portal (EU Data Act) for Home Assistant

A Home Assistant custom integration that reads your vehicle data from the **official Polestar Data Portal API** (`data-portal.polestar.com`), the access Polestar provides to vehicle owners under the EU Data Act.

> **Status: untested beta (v0.1.0).** It was written from the portal's API documentation and covered by offline unit tests (API client, parsing, error handling), but it has **not yet been run against a live account or inside Home Assistant**. Please report what you see.

- Read-only: no commands, no charging control.
- Uses the official OAuth2 client-credentials API (no scraping, no Polestar ID password stored).
- Not affiliated with Polestar. Unofficial community project.

## Requirements

- Home Assistant 2024.12.0 or newer
- A Polestar vehicle registered in an eligible EU/EEA market (the portal lists only those)
- A Polestar ID with access to the vehicle in the [Polestar data portal](https://data-portal.polestar.com/)

## Get API credentials

1. Sign in to the Polestar data portal.
2. Open **Credential** and create an API credential. Note the **Client ID** and **Client secret** (the secret is shown once; keep it private).
3. Open **API Documentation** and note the **Account ID / x-client-id**.

## Install

**HACS:** HACS → ⋮ → *Custom repositories* → add this repository as type **Integration** → install → restart Home Assistant.

**Manual:** copy `custom_components/polestar_data_portal` into your `config/custom_components/` folder and restart.

Then: **Settings → Devices & services → Add integration → Polestar Data Portal**, and enter Client ID, Client secret and Account ID.

## Options

**Configure** on the integration lets you choose:

- **Polling interval** (default 5 min).
- **Data to fetch.** Each selected kind of data is one API call per vehicle per poll.

The portal allows **10,000 calls per client per day**. The options form refuses combinations estimated to exceed 9,000 calls/day. A diagnostic sensor, **API calls today**, shows the running count.

| Data | Default | Entities |
|---|---|---|
| Availability | on | availability status, usage mode |
| Battery and charging | on | battery %, range, charging status/type/power/current/voltage, time to full, consumption |
| Doors, windows and locks | on | doors, windows, hood, tailgate, sunroof, central lock, alarm |
| Health | on | days/km to service, warnings, tyre pressures |
| Location | on | device tracker, speed, altitude, heading |
| Odometer and trips | on | odometer, trip meters, average speeds |
| Charge target | on | target charge level |
| Parking climatization | off | status, cabin temperature, requested temperature |
| Cabin pre-cleaning | off | status, air quality, last cycle |
| Charging current limit | off | amp limit |
| Charge Now | off | override status |
| Global charge timer | off | active, start, stop |
| At charge location | off | current charge location, arrival time |
| Charge locations | off | number of saved locations |

Entities are created only when your vehicle actually reports the field, so a model without a sunroof gets no sunroof entity. Some endpoints are model-specific and answer 404 for other models; the integration skips those for 6 hours and tries again.

Every sensor has a `reported_at` attribute with the timestamp the vehicle/portal reported for that data. The per-vehicle **Last update** sensor shows the newest one.

## Known limitations

- **Enum values are not documented.** For status fields (charging status, warnings, door states …) the API documents plain strings without listing possible values. Text sensors show the raw value. Door/window/lock binary sensors interpret values containing *open/closed/locked/unlocked*; the raw value is always in the `raw_state` attribute, and the state stays *unknown* if a value isn't recognised. If you see unknown values, open an issue with the raw value.
- Light warnings and parking-climate timers are available from the API but not mapped to entities yet.
- Data freshness depends on what the vehicle uploads; the portal only returns what the car has reported.
- The `x-client-id` header is sent on every request. The documentation marks it required for the vehicle list; whether other endpoints need it is not stated.

## Troubleshooting

- **Invalid credentials:** check Client ID, secret and Account ID; create a new credential if needed.
- **No vehicles:** only vehicles registered in an eligible EU/EEA market are listed.
- **Some entities missing:** the vehicle hasn't reported that field, or the model doesn't support that endpoint. Use **Download diagnostics** (redacted) to see which payloads arrive.
- Enable debug logging with:

```yaml
logger:
  logs:
    custom_components.polestar_data_portal: debug
```

## Development

```bash
python3 -m unittest discover -s tests -v      # offline tests, no Home Assistant needed
python3 tools/build_translations.py           # regenerate strings.json and translations/
```

Entities are defined in `custom_components/polestar_data_portal/catalog.py`; adding a field is one line there, followed by rebuilding the translations.

## License

MIT
