"""Compute every answerable seed's gold answer from the raw trips.

    uv run python -m eval.gold

Writes eval/gold.json: seed id -> rows the gold SQL returned. The SQL runs
directly on the raw trips through the views below, never through the bot's
query templates or the rollups.
"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

import duckdb

from taxichat.places import ZONES_CSV

from .seeds import SEEDS

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).parent / "gold.json"


def main() -> None:
    con = duckdb.connect()
    con.execute("SET memory_limit = '8GB'")
    raw = ROOT / "data" / "raw" / "**" / "*.parquet"
    con.execute(
        f"""CREATE VIEW t AS SELECT *, epoch(dropoff_at - pickup_at) / 60 AS minutes, pickup_at - INTERVAL 4 HOUR AS night_at
        FROM read_parquet('{raw}', hive_partitioning = false)"""
    )
    con.execute(f"CREATE TABLE z AS SELECT LocationID AS zone, Zone AS name, Borough AS borough FROM read_csv('{ZONES_CSV}')")

    gold = {}
    for seed in SEEDS:
        if "gold_sql" not in seed:
            continue
        started = time.perf_counter()
        rows = con.execute(seed["gold_sql"]).fetchall()
        gold[seed["id"]] = [[v.isoformat() if isinstance(v, date) else v for v in row] for row in rows]
        print(f"{seed['id']:<11} {time.perf_counter() - started:5.1f}s  {str(gold[seed['id']])[:90]}", flush=True)
    OUT.write_text(json.dumps(gold, indent=1))


if __name__ == "__main__":
    main()
