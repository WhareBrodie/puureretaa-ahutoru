# Pūreretā Ahutoru — Agent Guide

Filament inventory and print tracking for a Bambu Lab P1S with full AMS, inspired by SpoolStock but with cloud-first Bambu auto-sync (cloud API + cloud MQTT, optional local MQTT/FTPS fallback).

## Stack & deployment

| Layer | Tech |
|-------|------|
| Frontend | Vite + React + react-router-dom |
| Backend | Python 3.12 (`server/purereta_server.py`) — static SPA + `/api/*` |
| Database | SQLite at `data/purereta.db` on server volume |
| Bambu sync | Background worker (`server/bambu/sync_worker.py`) — cloud API poll, cloud/local MQTT, optional FTPS |
| Runtime | Python Alpine behind Traefik on home network |
| Delivery | Private GitHub repo → GitOps → Portainer auto-deploy |

### URLs

| Context | URL |
|---------|-----|
| Production (browser) | `http://pūreretā-ahutoru.internal` (human-friendly DNS name) |
| Traefik Host rule | `xn--preret-ahutoru-qub40o.internal` only — **macrons must be punycode in compose labels**; Traefik rejects non-ASCII in `Host()` matchers |
| Container | `http://purereta-ahutoru:80` |
| Native Mac dev | `http://localhost:5173` (Vite; proxies `/api` → `:8080`) |

### Data vs code

| What | Where it lives | Updated how |
|------|----------------|-------------|
| App (React, Python) | GitHub → Docker image | Push to `main` → GitOps redeploy |
| SQLite DB, photos | Server volume (`/c/containers/vibes/purereta-ahutoru/data/`) | In-app CRUD + Bambu sync |
| Seed empty-spool weights | Git repo (`data/seed_empty_spool_weights.json`) | Seeded once on first DB init |

Deploy host admin creates `/c/containers/vibes/purereta-ahutoru/data` once before first deploy.

**localhost vs production:** separate databases. Use production URL for day-to-day inventory.

## Bambu integration

**Do not enable LAN Only Mode** on the printer unless you intentionally want to leave the Bambu cloud account. LAN Only disconnects the printer from your account (Handy, cloud history, etc.) and is not required for this app.

Cloud-first sync (recommended setup):

1. **Cloud API** (`BAMBU_CLOUD_EMAIL` + `BAMBU_CLOUD_PASSWORD`, or `BAMBU_CLOUD_ACCESS_TOKEN`) — primary print import with slicer `used_g` / `used_m`; auto-discovers bound printer serial and access code
2. **Cloud MQTT** (same cloud credentials + serial) — live printer/AMS state via `us.mqtt.bambulab.com` (override with `BAMBU_MQTT_BROKER` for CN accounts)
3. **Optional local MQTT/FTPS** (`BAMBU_PRINTER_IP`, optionally `BAMBU_LAN_ACCESS_CODE`) — lower-latency live state and gcode fallback for SD/local prints; works while the printer stays cloud-connected

Print completion is imported primarily by **cloud task polling** (`SYNC_CLOUD_INTERVAL_S`, default 300s). MQTT finish events can import sooner when cloud task data is already available.

**Minimum for print auto-import:** cloud credentials (`BAMBU_CLOUD_ACCESS_TOKEN`, or email + password). The LAN vars alone (`BAMBU_PRINTER_IP`, `BAMBU_SERIAL`, `BAMBU_LAN_ACCESS_CODE`) enable local MQTT live AMS state and optional FTPS, but not cloud print history import.

### How to get `BAMBU_CLOUD_ACCESS_TOKEN`

Bambu does **not** show this in Bambu Studio anymore. Two practical methods:

#### Method A — MakerWorld browser cookie (easiest; NZ/global accounts)

1. In a browser, log in to [makerworld.com](https://makerworld.com/) with the **same Bambu account** as your printer.
2. Open Developer Tools:
   - **Chrome / Edge:** `Cmd+Option+I` → **Application** tab
   - **Safari:** enable Develop menu, then **Develop → Show Web Inspector** → **Storage** tab
   - **Firefox:** `Cmd+Option+I` → **Storage** tab
3. Open **Cookies** → select `https://makerworld.com` (or `makerworld.com`).
4. Find the cookie named **`token`** (not `refresh_token` or session IDs).
5. Copy the full **Value** — a long string, often starting with `eyJ` (JWT).
6. In Portainer, add env var `BAMBU_CLOUD_ACCESS_TOKEN` = paste that value (no `Bearer` prefix).
7. Redeploy the stack.

Token is usually valid ~3 months; repeat when sync stops with 401 errors.

#### Method B — Email + password in Portainer (no 2FA only)

Set `BAMBU_CLOUD_EMAIL` and `BAMBU_CLOUD_PASSWORD` in Portainer. Works if Bambu does not require email verification on login. If the sync worker logs *"login requires 2FA verification"*, use Method A instead.

#### Method C — One-off login script (2FA via email code)

If Method A is awkward, use a community login helper (handles the email verification code Bambu sends):

```bash
pip install bambu-lab-cloud-api
python -c "from bambulab import BambuAuthenticator; print(BambuAuthenticator().login('you@email.com', 'your-password'))"
```

Copy the printed token into Portainer as `BAMBU_CLOUD_ACCESS_TOKEN`.

### Known limitations (read before relying on auto-sync)

| Issue | Impact |
|-------|--------|
| **2FA on Bambu account** | Email/password login may fail; use Method A or C above |
| **Token expiry** | Tokens last ~3 months; re-copy from MakerWorld cookie or re-run login when sync stops with 401 errors |
| **Cloud task detail 403** | Some jobs return only total weight, not per-filament breakdown → review queue or manual assignment |
| **SD / non-cloud-sliced prints** | Often lack cloud filament metadata; needs FTPS fallback (printer IP reachable from deploy host) or manual log |
| **Cloud MQTT reliability** | Bambu has changed cloud MQTT auth before; reconnect loop retries every 30s |
| **Polling delay** | Default 5-minute cloud poll — not instant unless MQTT + matching cloud task align |
| **Multiple printers** | Set `BAMBU_CLOUD_DEVICE_ID` or `BAMBU_SERIAL` when more than one device is bound |
| **Deploy host networking** | Container must reach `api.bambulab.com` and `us.mqtt.bambulab.com`; optional FTPS needs route to printer LAN IP |

Developer Mode on the printer is **not** required for cloud sync.

### Non-Bambu filament

- Map AMS slots 1–4 to inventory spools in **AMS** page
- Bambu RFID `tag_uid` auto-links Bambu spools when detected
- Ambiguous prints land in **Review queue** (`/prints?review=1`) for manual spool assignment

## Environment variables

| Variable | Production default | Set in Portainer? |
|----------|-------------------|-------------------|
| `TZ` | `Pacific/Auckland` | Only if overriding |
| `PUBLIC_URL` | `http://xn--preret-ahutoru-qub40o.internal` | Only if hostname changes |
| `DEFAULT_LOW_STOCK_THRESHOLD_G` | `100` | Optional |
| `SYNC_CLOUD_INTERVAL_S` | `300` | Optional |
| `BAMBU_CLOUD_EMAIL` | — | **Yes (secret)** |
| `BAMBU_CLOUD_PASSWORD` | — | **Yes (secret)** |
| `BAMBU_CLOUD_ACCESS_TOKEN` | — | **Yes (secret, preferred with 2FA)** |
| `BAMBU_CLOUD_DEVICE_ID` | empty | Optional filter when multiple printers bound |
| `BAMBU_SERIAL` | empty | Optional; auto-discovered from cloud bind API |
| `BAMBU_MQTT_BROKER` | `us.mqtt.bambulab.com` | Optional (`cn.mqtt.bambulab.com` for CN accounts) |
| `BAMBU_MQTT_MODE` | `auto` | Optional: `auto`, `cloud`, or `local` |
| `BAMBU_PRINTER_IP` | empty | Optional — local MQTT/FTPS fallback |
| `BAMBU_LAN_ACCESS_CODE` | — | Optional secret — auto-fetched from bind API if omitted |

Never commit secrets. Document only in this file and `.env.example` placeholders.

## Directory map

```
frontend/                 Vite + React SPA
  src/pages/
    FilamentsPage.jsx     One row per filament (brand+material+color); drill-down
    FilamentDetailPage.jsx  Aggregated view + individual spools for a filament
    InventoryPage.jsx     Spools grouped by storage location
    SpoolDetailPage.jsx   Single spool: photo, scale, drying, usage history
server/
  purereta_server.py      Static files + /api/*
  db.py                   SQLite + migrations
  routes/                 spools, prints, ams, dashboard, settings, csv_io
  bambu/                  mqtt_client, cloud_sync, ftps_gcode, print_processor, sync_worker
  entrypoint.sh           Init DB + start sync worker + API
data/
  migrations/001_init.sql
  seed_empty_spool_weights.json
Dockerfile                Multi-stage: npm build → Python Alpine
docker-compose.yml        Production — Traefik labels, host volume, no ports
docker-compose.local.yml
start-dev.sh              Native Mac dev (API + sync worker + Vite)
```

## Local development

```bash
chmod +x start-dev.sh
./start-dev.sh
# → http://localhost:5173
```

Optional Docker test:

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up --build
# → http://localhost:8080
```

## API overview

- `GET /api/dashboard`, `/api/stats`, `/api/alerts`
- `GET/POST/PUT/DELETE /api/spools`, `/api/locations`
- `GET/POST /api/prints`, `POST /api/prints/:id/review`
- `GET/PUT /api/ams/slots`, `GET /api/ams/live`
- `GET /api/export/csv`, `POST /api/import/csv` — native export or **SpoolStock export** import (auto-detected)
- `GET/PUT /api/settings`

## Deferred (Phase 4)

QR sticker sheets, Web NFC linking, Wi-Fi label PDFs, Bambu invoice PDF import — not implemented yet.

## Git conventions

- **Do not commit:** `.env`, `.env.local`, `data/purereta.db`, `data/photos/`
- **Do commit:** app code, Dockerfile, compose files, migrations, seed JSON
- No force-push to `main` without explicit user request
