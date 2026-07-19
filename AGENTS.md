# Pūreretā Ahutoru — Agent Guide

Filament inventory and print tracking for a Bambu Lab P1S with full AMS, inspired by SpoolStock but with hybrid Bambu auto-sync (LAN MQTT + cloud API + FTPS gcode fallback).

## Stack & deployment

| Layer | Tech |
|-------|------|
| Frontend | Vite + React + react-router-dom |
| Backend | Python 3.12 (`server/purereta_server.py`) — static SPA + `/api/*` |
| Database | SQLite at `data/purereta.db` on server volume |
| Bambu sync | Background worker (`server/bambu/sync_worker.py`) — MQTT, cloud poll, FTPS |
| Runtime | Python Alpine behind Traefik on home network |
| Delivery | Private GitHub repo → GitOps → Portainer auto-deploy |

### URLs

| Context | URL |
|---------|-----|
| Production (browser) | `http://pūreretā-ahutoru.internal` or `http://xn--preret-ahutoru-qub40o.internal` (equivalent; Traefik accepts both) |
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

Hybrid sync (recommended setup):

1. **LAN MQTT** (`BAMBU_PRINTER_IP`, `BAMBU_SERIAL`, `BAMBU_LAN_ACCESS_CODE`) — live printer/AMS state, print finish events
2. **Cloud API** (`BAMBU_CLOUD_EMAIL` + `BAMBU_CLOUD_PASSWORD`, or `BAMBU_CLOUD_ACCESS_TOKEN`) — historical tasks with slicer `used_g` / `used_m`
3. **FTPS fallback** — gcode/3mf download when cloud lacks per-filament weights (SD/local prints)

**Printer prerequisites:** LAN Mode ON; Developer Mode ON for full protocol.

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
| `BAMBU_PRINTER_IP` | empty | Yes |
| `BAMBU_SERIAL` | empty | Yes |
| `BAMBU_LAN_ACCESS_CODE` | — | **Yes (secret)** |
| `BAMBU_CLOUD_EMAIL` | — | **Yes (secret)** |
| `BAMBU_CLOUD_PASSWORD` | — | **Yes (secret)** |
| `BAMBU_CLOUD_ACCESS_TOKEN` | — | **Yes (secret, alternative to email/password)** |
| `BAMBU_CLOUD_DEVICE_ID` | — | Optional filter for cloud tasks |

Never commit secrets. Document only in this file and `.env.example` placeholders.

## Directory map

```
frontend/                 Vite + React SPA
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
- `GET /api/export/csv`, `POST /api/import/csv`
- `GET/PUT /api/settings`

## Deferred (Phase 4)

QR sticker sheets, Web NFC linking, Wi-Fi label PDFs, Bambu invoice PDF import — not implemented yet.

## Git conventions

- **Do not commit:** `.env`, `.env.local`, `data/purereta.db`, `data/photos/`
- **Do commit:** app code, Dockerfile, compose files, migrations, seed JSON
- No force-push to `main` without explicit user request
