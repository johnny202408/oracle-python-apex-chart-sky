from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import oracledb
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOGGER = logging.getLogger("oracle-apex-chart")

STATIC_DIR = Path(__file__).parent / "static"
TABLE_NAME = "DEMO_CHART_POINTS"
ROW_PRESETS = (100, 1_000, 10_000, 100_000)

DB_USER = os.getenv("DB_USER", "demo")
DB_PASSWORD = os.getenv("DB_PASSWORD", "demo")
DB_DSN = os.getenv("DB_DSN", "localhost:1521/FREEPDB1")
DB_MIN_POOL_SIZE = int(os.getenv("DB_MIN_POOL_SIZE", "1"))
DB_MAX_POOL_SIZE = int(os.getenv("DB_MAX_POOL_SIZE", "4"))
SEED_ROWS = max(int(os.getenv("SEED_ROWS", str(max(ROW_PRESETS)))), max(ROW_PRESETS))
DB_CONNECT_RETRIES = int(os.getenv("DB_CONNECT_RETRIES", "90"))
DB_CONNECT_SLEEP_SECONDS = float(os.getenv("DB_CONNECT_SLEEP_SECONDS", "2"))

pool: oracledb.ConnectionPool | None = None


def wait_for_database() -> None:
    for attempt in range(1, DB_CONNECT_RETRIES + 1):
        try:
            with oracledb.connect(user=DB_USER, password=DB_PASSWORD, dsn=DB_DSN):
                LOGGER.info("Connected to Oracle on attempt %s", attempt)
                return
        except oracledb.Error as exc:
            LOGGER.info(
                "Waiting for Oracle (%s/%s): %s",
                attempt,
                DB_CONNECT_RETRIES,
                exc,
            )
            time.sleep(DB_CONNECT_SLEEP_SECONDS)

    raise RuntimeError(f"Could not connect to Oracle at {DB_DSN}")


def get_pool() -> oracledb.ConnectionPool:
    if pool is None:
        raise RuntimeError("Oracle connection pool has not been initialized")
    return pool


def table_exists(connection: oracledb.Connection) -> bool:
    cursor = connection.cursor()
    cursor.execute(
        """
        select count(*)
        from user_tables
        where table_name = :table_name
        """,
        table_name=TABLE_NAME,
    )
    return cursor.fetchone()[0] == 1


def create_table(connection: oracledb.Connection) -> None:
    cursor = connection.cursor()
    cursor.execute(
        f"""
        create table {TABLE_NAME} (
            point_index number(10) not null,
            metric_value number(12,4) not null,
            volume_value number(12,4) not null,
            created_at timestamp default systimestamp not null,
            constraint demo_chart_points_pk primary key (point_index)
        )
        """
    )


def seed_table(connection: oracledb.Connection) -> None:
    cursor = connection.cursor()
    cursor.execute(f"truncate table {TABLE_NAME}")
    cursor.execute(
        f"""
        insert into {TABLE_NAME} (point_index, metric_value, volume_value)
        select
            level as point_index,
            round(50 + 18 * sin(level / 53) + 6 * cos(level / 11), 4) as metric_value,
            round(700 + sqrt(level) * 9 + 42 * sin(level / 313), 4) as volume_value
        from dual
        connect by level <= :seed_rows
        """,
        seed_rows=SEED_ROWS,
    )
    connection.commit()


def ensure_schema() -> None:
    with get_pool().acquire() as connection:
        if not table_exists(connection):
            LOGGER.info("Creating %s", TABLE_NAME)
            create_table(connection)

        cursor = connection.cursor()
        cursor.execute(f"select count(*) from {TABLE_NAME}")
        row_count = cursor.fetchone()[0]

        if row_count < SEED_ROWS:
            LOGGER.info("Seeding %s rows into %s", SEED_ROWS, TABLE_NAME)
            seed_table(connection)
        else:
            LOGGER.info("%s already has %s rows", TABLE_NAME, row_count)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool

    wait_for_database()
    pool = oracledb.create_pool(
        user=DB_USER,
        password=DB_PASSWORD,
        dsn=DB_DSN,
        min=DB_MIN_POOL_SIZE,
        max=DB_MAX_POOL_SIZE,
        increment=1,
    )
    ensure_schema()

    yield

    if pool is not None:
        pool.close()


app = FastAPI(title="Oracle Python ApexCharts Demo", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    with get_pool().acquire() as connection:
        cursor = connection.cursor()
        cursor.execute("select 'ok' from dual")
        status = cursor.fetchone()[0]
    return {"status": status}


@app.get("/api/row-presets")
def row_presets() -> dict[str, list[int]]:
    return {"presets": list(ROW_PRESETS)}


@app.get("/api/chart-data")
def chart_data(
    rows: int = Query(default=100, ge=1, le=SEED_ROWS),
) -> dict[str, object]:
    started = time.perf_counter()

    try:
        with get_pool().acquire() as connection:
            cursor = connection.cursor()
            cursor.arraysize = min(rows, 5_000)
            cursor.execute(
                f"""
                select point_index, metric_value
                from {TABLE_NAME}
                where point_index <= :row_limit
                order by point_index
                """,
                row_limit=rows,
            )
            data = [[int(point_index), float(metric_value)] for point_index, metric_value in cursor]
    except oracledb.Error as exc:
        LOGGER.exception("Oracle query failed")
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    return {
        "rows": rows,
        "elapsed_ms": elapsed_ms,
        "series": [{"name": "Metric value", "data": data}],
    }
