# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**oracle-python-apex-chart** is a Docker Compose demo: FastAPI + `python-oracledb` against Oracle Database Free, with an ApexCharts frontend that requests 100 / 1,000 / 10,000 / 100,000 rows and displays query, payload, and browser-load timings.

## Build and Run

```bash
docker compose up --build       # http://localhost:8000
```

First run takes a few minutes — Oracle initializes, then the app retries the connection until it accepts.

| Service | Port | Image / build |
|---------|------|---------------|
| `oracle` | 1521 | `gvenzl/oracle-free:slim` |
| `app`    | 8000 | built from `./app` (Python 3.12 slim) |

DB credentials (set in `compose.yaml`): user `demo` / password `DemoPassword123` / DSN `oracle:1521/FREEPDB1`. Seeded table is `DEMO_CHART_POINTS`.

## Architecture

### Startup (`app/main.py`)

FastAPI lifespan runs in order:
1. `wait_for_database()` — retries `oracledb.connect(...)` up to `DB_CONNECT_RETRIES` times with `DB_CONNECT_SLEEP_SECONDS` between attempts. Defaults: 90 × 2s.
2. `oracledb.create_pool(...)` — sized by `DB_MIN_POOL_SIZE` / `DB_MAX_POOL_SIZE`, increment 1.
3. `ensure_schema()` — creates `DEMO_CHART_POINTS` if absent, then seeds **iff** `row_count < SEED_ROWS`.

### Schema and seed

`DEMO_CHART_POINTS` columns: `point_index` (PK, 1..SEED_ROWS), `metric_value`, `volume_value`, `created_at`. Values are deterministic — generated in a single `connect by level <= :seed_rows` insert in `seed_table()`.

### API

- `GET /` — serves `app/static/index.html`
- `GET /api/health` — runs `select 'ok' from dual`
- `GET /api/row-presets` — returns `ROW_PRESETS` tuple
- `GET /api/chart-data?rows=N` — `1 <= N <= SEED_ROWS`. Cursor `arraysize = min(rows, 5000)`. Returns `{rows, elapsed_ms, series: [{name, data: [[idx, val], ...]}]}`.

### Frontend

`app/static/{index.html, app.js, styles.css}`. ApexCharts loaded from `cdn.jsdelivr.net` at runtime — no bundler, no build step. Animations disabled on update for performance.

## Configuration (env vars)

| Var | Default | Notes |
|---|---|---|
| `DB_USER` | `demo` | |
| `DB_PASSWORD` | `demo` (compose overrides to `DemoPassword123`) | |
| `DB_DSN` | `localhost:1521/FREEPDB1` (compose overrides to `oracle:...`) | |
| `DB_MIN_POOL_SIZE` / `DB_MAX_POOL_SIZE` | 1 / 4 | |
| `SEED_ROWS` | 100000 | See gotchas below. |
| `DB_CONNECT_RETRIES` / `DB_CONNECT_SLEEP_SECONDS` | 90 / 2 | |

## Gotchas

- **Re-seed only happens when the table has fewer rows than `SEED_ROWS`.** Lowering `SEED_ROWS` does **not** shrink the table. To reset, drop the `oracle-data` volume: `docker compose down -v`.
- **`SEED_ROWS` is floored to `max(ROW_PRESETS)`** at `app/main.py:26` (`max(int(...), max(ROW_PRESETS))`). You can raise it via env var, but lowering below 100,000 requires editing `ROW_PRESETS` too.
- **`/api/chart-data?rows=` upper bound is `SEED_ROWS`, not `max(ROW_PRESETS)`** — see the `Query(..., le=SEED_ROWS)` validator at `app/main.py:166`. If you raise `SEED_ROWS`, the API allows larger requests automatically; the frontend buttons won't.
- **No source volume mount for `app`** — code edits require `docker compose up --build`, not just restart.
- **Oracle readiness is gated by `wait_for_database()`, not a Compose `healthcheck`.** `compose.yaml` has only `depends_on: oracle` (no `condition: service_healthy`).

## Debugging

```bash
docker compose logs -f app
docker compose logs -f oracle

# sqlplus into the DB container
docker exec -it oracle-apex-chart-db sqlplus demo/DemoPassword123@FREEPDB1

# timing sweep across presets
for rows in 100 1000 10000 100000; do
  curl -s "http://localhost:8000/api/chart-data?rows=$rows" | jq '.elapsed_ms'
done
```
