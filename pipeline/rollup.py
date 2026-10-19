"""Aggregate each cleaned service-month into hourly rollups under data/rollups.

    uv run python -m pipeline.rollup --from 2019-01 --to 2025-12

One row per hour x pickup zone x company. Most questions (trends, rankings,
totals, comparisons) can be answered from these instead of scanning raw trips.
Sums rather than averages are stored, so any average can be recomputed exactly
at any coarser grain. A month is rebuilt only when its raw file is newer than
its rollup.
"""

from __future__ import annotations

import argparse
import time

import duckdb

from .common import RAW, ROLLUPS, SERVICES, month_range, partition


def rollup(con: duckdb.DuckDBPyConnection, service: str, month, force: bool) -> str:
    source = partition(RAW, service, month)
    if not source.exists():
        return "no raw file"
    out = partition(ROLLUPS, service, month)
    if not force and out.exists() and out.stat().st_mtime >= source.stat().st_mtime:
        return "up to date"

    started = time.perf_counter()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    con.execute(
        f"""
        COPY (
            SELECT
                service,
                company,
                date_trunc('hour', pickup_at) AS hour,
                pickup_zone,
                count(*) AS trips,
                count(*) FILTER (tip > 0) AS tipped_trips,
                sum(fare) AS fare_sum,
                sum(tip) AS tip_sum,
                sum(total) AS total_sum,
                sum(distance_mi) AS distance_sum,
                sum(epoch(dropoff_at - pickup_at)) AS duration_s_sum
            FROM read_parquet(?)
            GROUP BY ALL
            ORDER BY hour, pickup_zone, company
        ) TO '{tmp}' (FORMAT parquet, COMPRESSION zstd)
        """,
        [str(source)],
    )
    tmp.replace(out)
    rows = con.execute("SELECT count(*) FROM read_parquet(?)", [str(out)]).fetchone()[0]
    return f"{rows:,} rollup rows in {time.perf_counter() - started:.1f}s"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--services", nargs="+", default=list(SERVICES), choices=SERVICES)
    parser.add_argument("--from", dest="start", required=True)
    parser.add_argument("--to", dest="end", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    con = duckdb.connect()
    for service in args.services:
        for month in month_range(args.start, args.end):
            print(f"{service} {month}: {rollup(con, service, month, args.force)}", flush=True)


if __name__ == "__main__":
    main()
