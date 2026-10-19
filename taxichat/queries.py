"""Parameterised queries over the hourly rollups. No free-form SQL.

The rollups store sums, not averages, so every average here is an exact
sum/trips over whatever period, service, place and time window the question
resolved to. Rollups are keyed by pickup zone, so place filters here mean
"trips starting there".
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import duckdb

from .places import EXCLUDED_ZONES, ZONES_CSV
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

DAY_NUMBERS = {
    "monday": [1], "tuesday": [2], "wednesday": [3], "thursday": [4], "friday": [5], "saturday": [6], "sunday": [7],
    "weekdays": [1, 2, 3, 4, 5], "weekends": [6, 7],
}

# time of day -> hour ranges [start, end). Night runs 21:00 to 04:00 and belongs
# to the day it started on, so Friday night includes the small hours of Saturday.
TIME_WINDOWS = {
    "morning": [(6, 12)],
    "afternoon": [(12, 17)],
    "evening": [(17, 21)],
    "night": [(21, 28)],
    "rush_hour": [(7, 10), (16, 19)],
}
NIGHT_SHIFT_HOURS = 4

# Averages over very few trips are noise; rankings by an average ignore zones below this.
MIN_TRIPS_FOR_AVERAGE_RANKING = 100


@dataclass
class Filters:
    period: Period
    service: str
    zone_ids: tuple[int, ...] | None = None
    day: str | None = None
    time_of_day: str | None = None


@dataclass
class QueryResult:
    sql: str
    params: list
    source: str
    rows_scanned: int
    values: dict
    ms: float


def _where(f: Filters) -> tuple[list[str], list]:
    where = ["hour >= ?", "hour < ?"]
    params: list = [f.period.start, f.period.end]
    if (service_filter := SERVICE_FILTER[f.service]) is not None:
        where.append(f"{service_filter[0]} = ?")
        params.append(service_filter[1])
    if f.zone_ids is not None:
        where.append(f"pickup_zone IN ({', '.join('?' * len(f.zone_ids))})")
        params.extend(f.zone_ids)
    # Shifting by four hours lets a night window that crosses midnight be one range
    # on one day; it only applies when the window is night.
    shifted = f"hour - INTERVAL {NIGHT_SHIFT_HOURS} HOUR" if f.time_of_day == "night" else "hour"
    if f.day is not None:
        where.append(f"isodow({shifted}) IN ({', '.join(map(str, DAY_NUMBERS[f.day]))})")
    if f.time_of_day is not None:
        offset = NIGHT_SHIFT_HOURS if f.time_of_day == "night" else 0
        ranges = [f"hour({shifted}) BETWEEN {s - offset} AND {e - offset - 1}" for s, e in TIME_WINDOWS[f.time_of_day]]
        where.append("(" + " OR ".join(ranges) + ")")
    return where, params


class Database:
    def __init__(self, data_dir: Path):
        rollups = str(data_dir / "rollups" / "hourly" / "**" / "*.parquet")
        self.con = duckdb.connect()
        self.con.execute(f"CREATE VIEW rollups AS SELECT * FROM read_parquet('{rollups}', hive_partitioning = false)")
        self.con.execute(f"CREATE TABLE zones AS SELECT LocationID AS zone, Zone AS name, Borough AS borough FROM read_csv('{ZONES_CSV}')")

    def _run(self, sql: str, params: list) -> tuple[list, float]:
        started = time.perf_counter()
        rows = self.con.execute(sql, params).fetchall()
        return rows, (time.perf_counter() - started) * 1000

    def total_or_average(self, measure: str, f: Filters) -> QueryResult:
        expression, unit = MEASURE_SQL[measure]
        where, params = _where(f)
        sql = f"SELECT {expression} AS value, sum(trips) AS trips, count(*) AS rollup_rows FROM rollups WHERE {' AND '.join(where)}"
        [(value, trips, rows)], ms = self._run(sql, params)
        return QueryResult(sql, [str(p) for p in params], "rollup", rows, {"value": value, "trips": int(trips or 0), "measure": measure, "unit": unit}, ms)

    def ranking(self, measure: str, f: Filters, *, unit_of_rank: str, direction: str, n: int) -> QueryResult:
        expression, unit = MEASURE_SQL[measure]
        where, params = _where(f)
        where.append(f"pickup_zone NOT IN ({', '.join(map(str, EXCLUDED_ZONES))})")
        min_trips = 1 if measure == "trip_count" else MIN_TRIPS_FOR_AVERAGE_RANKING
        key, label = ("z.zone", "z.name") if unit_of_rank == "zones" else ("z.borough", "z.borough")
        order = "DESC" if direction == "highest" else "ASC"
        sql = (
            f"WITH matched AS (SELECT * FROM rollups WHERE {' AND '.join(where)}) "
            f"SELECT {key} AS id, any_value({label}) AS name, any_value(z.borough) AS borough, {expression} AS value, sum(trips) AS trips, "
            f"(SELECT count(*) FROM matched) AS rollup_rows "
            f"FROM matched JOIN zones z ON z.zone = matched.pickup_zone "
            f"GROUP BY {key} HAVING sum(trips) >= ? ORDER BY value {order}, id LIMIT ?"
        )
        params += [min_trips, n]
        rows, ms = self._run(sql, params)
        ranked = [
            {"rank": i + 1, "id": r[0], "name": r[1], "borough": r[2], "value": r[3], "trips": int(r[4])}
            for i, r in enumerate(rows)
        ]
        return QueryResult(
            sql,
            [str(p) for p in params],
            "rollup",
            rows[0][5] if rows else 0,
            {"rows": ranked, "measure": measure, "unit": unit, "rank_unit": unit_of_rank, "direction": direction, "n": n, "min_trips": min_trips},
            ms,
        )
