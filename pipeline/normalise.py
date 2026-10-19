"""Clean each landed TLC file into the unified schema under data/raw.

    uv run python -m pipeline.normalise --from 2019-01 --to 2025-12

One output file per service-month, sorted by pickup time so date filters can
skip row groups. Every rejected row is counted by reason in the month's
manifest; nothing is dropped silently. A month is skipped when its manifest
says it was built from the same landing file, so reruns only redo what changed.

TLC's schemas drift over the years (column case, INT32 vs INT64 vs DOUBLE, new
fee columns), so each file's columns are read first and the SELECT is built
from what's actually there.
"""

from __future__ import annotations

import argparse
import time

import duckdb

from .common import RAW, SERVICES, landing_path, manifest_path, month_range, partition, read_manifest, write_json

SCHEMA_VERSION = 1

# HVFHS licence numbers, from TLC's data dictionary.
COMPANIES = {"HV0002": "juno", "HV0003": "uber", "HV0004": "via", "HV0005": "lyft"}


def columns(con: duckdb.DuckDBPyConnection, path) -> set[str]:
    return {row[0].lower() for row in con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]).fetchall()}


def optional(cols: set[str], name: str) -> str:
    return f"coalesce({name}, 0)" if name in cols else "0"


def select_sql(service: str, cols: set[str]) -> str:
    if service in ("yellow", "green"):
        prefix = "tpep" if service == "yellow" else "lpep"
        return f"""
            '{service}' AS service,
            '{service}' AS company,
            CAST({prefix}_pickup_datetime AS TIMESTAMP) AS pickup_at,
            CAST({prefix}_dropoff_datetime AS TIMESTAMP) AS dropoff_at,
            CAST(PULocationID AS SMALLINT) AS pickup_zone,
            CAST(DOLocationID AS SMALLINT) AS dropoff_zone,
            CAST(passenger_count AS TINYINT) AS passengers,
            CAST(trip_distance AS DOUBLE) AS distance_mi,
            CAST(fare_amount AS DOUBLE) AS fare,
            CAST(tip_amount AS DOUBLE) AS tip,
            CAST(total_amount AS DOUBLE) AS total,
            CAST(payment_type AS TINYINT) AS payment_type
        """
    companies = " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in COMPANIES.items())
    # Rideshare files have no total column; this sums what the rider paid.
    total = " + ".join(
        ["base_passenger_fare", "tips"]
        + [optional(cols, c) for c in ("tolls", "bcf", "sales_tax", "congestion_surcharge", "airport_fee", "cbd_congestion_fee")]
    )
    return f"""
        'fhvhv' AS service,
        CASE hvfhs_license_num {companies} ELSE 'other' END AS company,
        CAST(pickup_datetime AS TIMESTAMP) AS pickup_at,
        CAST(dropoff_datetime AS TIMESTAMP) AS dropoff_at,
        CAST(PULocationID AS SMALLINT) AS pickup_zone,
        CAST(DOLocationID AS SMALLINT) AS dropoff_zone,
        CAST(NULL AS TINYINT) AS passengers,
        CAST(trip_miles AS DOUBLE) AS distance_mi,
        CAST(base_passenger_fare AS DOUBLE) AS fare,
        CAST(tips AS DOUBLE) AS tip,
        CAST({total} AS DOUBLE) AS total,
        CAST(NULL AS TINYINT) AS payment_type
    """


# First matching rule wins, so each rejected row is counted under one reason.
REJECT_RULES = [
    ("missing_timestamp", "pickup_at IS NULL OR dropoff_at IS NULL"),
    ("outside_file_month", "pickup_at < $start OR pickup_at >= $end"),
    ("dropoff_before_pickup", "dropoff_at < pickup_at"),
    ("over_24_hours", "dropoff_at - pickup_at > INTERVAL 24 HOUR"),
    ("unknown_zone", "pickup_zone NOT BETWEEN 1 AND 265 OR dropoff_zone NOT BETWEEN 1 AND 265"),
    ("negative_money", "fare < 0 OR tip < 0 OR total < 0"),
    ("implausible_distance", "distance_mi < 0 OR distance_mi > 500"),
]
REASON_SQL = "CASE " + " ".join(f"WHEN {cond} THEN '{name}'" for name, cond in REJECT_RULES) + " END"
UNIFIED = "service, company, pickup_at, dropoff_at, pickup_zone, dropoff_zone, passengers, distance_mi, fare, tip, total, payment_type"


def normalise(con: duckdb.DuckDBPyConnection, service: str, month, force: bool) -> str:
    source = landing_path(service, month)
    if not source.exists():
        return "no landing file"
    fingerprint = {"size": source.stat().st_size, "mtime": source.stat().st_mtime, "schema_version": SCHEMA_VERSION}
    previous = read_manifest(service, month)
    if not force and previous and previous.get("source") == fingerprint:
        return "up to date"

    started = time.perf_counter()
    start = f"{month}-01"
    end = f"{month.next()}-01"
    cols = columns(con, source)
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE staged AS
        WITH t AS (SELECT {select_sql(service, cols)} FROM read_parquet(?))
        SELECT *, {REASON_SQL} AS reject_reason FROM t
        """.replace("$start", f"TIMESTAMP '{start}'").replace("$end", f"TIMESTAMP '{end}'"),
        [str(source)],
    )
    out = partition(RAW, service, month)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    con.execute(
        f"COPY (SELECT {UNIFIED} FROM staged WHERE reject_reason IS NULL ORDER BY pickup_at) "
        f"TO '{tmp}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 1000000)"
    )
    tmp.replace(out)

    rows_in, rows_out = con.execute("SELECT count(*), count(*) FILTER (reject_reason IS NULL) FROM staged").fetchone()
    rejected = dict(con.execute("SELECT reject_reason, count(*) FROM staged WHERE reject_reason IS NOT NULL GROUP BY 1 ORDER BY 2 DESC").fetchall())
    con.execute("DROP TABLE staged")
    write_json(
        manifest_path(service, month),
        {
            "service": service,
            "month": str(month),
            "source": fingerprint,
            "source_columns": sorted(cols),
            "rows_in": rows_in,
            "rows_out": rows_out,
            "rejected": rejected,
            "output": str(out.relative_to(RAW.parent)),
            "output_bytes": out.stat().st_size,
            "seconds": round(time.perf_counter() - started, 1),
        },
    )
    share = 100 * (rows_in - rows_out) / rows_in if rows_in else 0
    return f"{rows_out:,} kept of {rows_in:,} ({share:.2f}% rejected) in {time.perf_counter() - started:.0f}s"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--services", nargs="+", default=list(SERVICES), choices=SERVICES)
    parser.add_argument("--from", dest="start", required=True)
    parser.add_argument("--to", dest="end", required=True)
    parser.add_argument("--force", action="store_true", help="rebuild even if the manifest is current")
    parser.add_argument("--memory", default="8GB", help="DuckDB memory limit; it spills to disk past this")
    args = parser.parse_args()

    con = duckdb.connect()
    con.execute(f"SET memory_limit = '{args.memory}'")
    con.execute(f"SET temp_directory = '{RAW.parent / 'tmp'}'")
    for service in args.services:
        for month in month_range(args.start, args.end):
            print(f"{service} {month}: {normalise(con, service, month, args.force)}", flush=True)


if __name__ == "__main__":
    main()
