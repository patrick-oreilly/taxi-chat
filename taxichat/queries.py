"""Parameterised queries over the hourly rollups. No free-form SQL.

The rollups store sums, not averages, so every average here is an exact
sum/trips over whatever period and service the question resolved to.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import duckdb

from .trace import Period

# measure -> (SQL expression over the rollups, unit)
MEASURE_SQL = {
    "trip_count": ("sum(trips)", "trips"),
    "total_fares": ("sum(fare_sum)", "usd"),
    "average_fare": ("sum(fare_sum) / sum(trips)", "usd"),
    "total_tips": ("sum(tip_sum)", "usd"),
    "average_tip": ("sum(tip_sum) / sum(trips)", "usd"),
    "average_distance": ("sum(distance_sum) / sum(trips)", "miles"),
    "average_duration": ("sum(duration_s_sum) / sum(trips) / 60", "minutes"),
}

# service option -> (column, value) to filter on; None means every service
SERVICE_FILTER = {
    "all": None,
    "yellow": ("service", "yellow"),
    "green": ("service", "green"),
    "rideshare": ("service", "fhvhv"),
    "uber": ("company", "uber"),
    "lyft": ("company", "lyft"),
}


@dataclass
class QueryResult:
    sql: str
    params: list
    source: str
    rows_scanned: int
    values: dict
    ms: float


class Database:
    def __init__(self, data_dir: Path):
        self.rollups = str(data_dir / "rollups" / "hourly" / "**" / "*.parquet")
        self.con = duckdb.connect()

    def total_or_average(self, measure: str, service: str, period: Period) -> QueryResult:
        expression, unit = MEASURE_SQL[measure]
        where = ["hour >= ?", "hour < ?"]
        params: list = [period.start, period.end]
        if (service_filter := SERVICE_FILTER[service]) is not None:
            where.append(f"{service_filter[0]} = ?")
            params.append(service_filter[1])
        sql = (
            f"SELECT {expression} AS value, sum(trips) AS trips, count(*) AS rollup_rows "
            f"FROM read_parquet('{self.rollups}', hive_partitioning = false) WHERE {' AND '.join(where)}"
        )
        started = time.perf_counter()
        value, trips, rows = self.con.execute(sql, params).fetchone()
        return QueryResult(
            sql=sql,
            params=[str(p) for p in params],
            source="rollup",
            rows_scanned=rows,
            values={"value": value, "trips": int(trips or 0), "measure": measure, "unit": unit},
            ms=(time.perf_counter() - started) * 1000,
        )
