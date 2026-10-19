"""Parameterised queries over the hourly rollups or the raw trips. No free-form SQL.

Every template runs against either source. The rollups are tiny and answer
most questions in milliseconds, but they're keyed by pickup zone and hold sums,
not individual trips, so questions about where trips end, and distributions,
use the raw trips instead. The caller decides which, and the trace records it.

The rollups store sums, not averages, so every rollup average is an exact
sum/trips, identical to the average over the raw trips it summarises.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path

import duckdb

from .places import EXCLUDED_ZONES, ZONES_CSV
from .trace import Period

MEASURE_UNITS = {
    "trip_count": "trips",
    "total_fares": "usd",
    "average_fare": "usd",
    "total_tips": "usd",
    "average_tip": "usd",
    "average_distance": "miles",
    "average_duration": "minutes",
}

SOURCES = {
    "rollup": {
        "table": "rollups",
        "time": "hour",
        "zone": {"pickup": "pickup_zone"},
        "trips": "sum(trips)",
        "measures": {
            "trip_count": "sum(trips)",
            "total_fares": "sum(fare_sum)",
            "average_fare": "sum(fare_sum) / sum(trips)",
            "total_tips": "sum(tip_sum)",
            "average_tip": "sum(tip_sum) / sum(trips)",
            "average_distance": "sum(distance_sum) / sum(trips)",
            "average_duration": "sum(duration_s_sum) / sum(trips) / 60",
        },
    },
    "raw": {
        "table": "raw",
        "time": "pickup_at",
        "zone": {"pickup": "pickup_zone", "dropoff": "dropoff_zone"},
        "trips": "count(*)",
        "measures": {
            "trip_count": "count(*)",
            "total_fares": "sum(fare)",
            "average_fare": "avg(fare)",
            "total_tips": "sum(tip)",
            "average_tip": "avg(tip)",
            "average_distance": "avg(distance_mi)",
            "average_duration": "avg(epoch(dropoff_at - pickup_at)) / 60",
        },
    },
}

# Raw-trip columns a distribution can describe, and the buckets it's split into.
DISTRIBUTIONS = {
    "distance": ("distance_mi", "miles", [1, 2, 5, 10]),
    "fare": ("fare", "usd", [10, 20, 40, 80]),
    "tip": ("tip", "usd", [1, 3, 5, 10]),
    "duration": ("epoch(dropoff_at - pickup_at) / 60", "minutes", [10, 20, 40, 60]),
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

# Averages over very few trips are noise; rankings by an average ignore places below this.
MIN_TRIPS_FOR_AVERAGE_RANKING = 100

TREND_GRAINS = ("day", "week", "month", "year")


@dataclass
class Filters:
    period: Period
    service: str
    zone_ids: tuple[int, ...] | None = None
    day: str | None = None
    time_of_day: str | None = None
    role: str = "pickup"  # whether zone_ids (and rankings) mean where trips start or end


@dataclass
class QueryResult:
    sql: str
    params: list
    source: str
    rows_scanned: int
    values: dict
    ms: float


def _where(f: Filters, source: str) -> tuple[list[str], list]:
    s = SOURCES[source]
    t = s["time"]
    where = [f"{t} >= ?", f"{t} < ?"]
    params: list = [f.period.start, f.period.end]
    if (service_filter := SERVICE_FILTER[f.service]) is not None:
        where.append(f"{service_filter[0]} = ?")
        params.append(service_filter[1])
    if f.zone_ids is not None:
        where.append(f"{s['zone'][f.role]} IN ({', '.join('?' * len(f.zone_ids))})")
        params.extend(f.zone_ids)
    # Shifting by four hours lets a night window that crosses midnight be one range
    # on one day; it only applies when the window is night.
    shifted = f"{t} - INTERVAL {NIGHT_SHIFT_HOURS} HOUR" if f.time_of_day == "night" else t
    if f.day is not None:
        where.append(f"isodow({shifted}) IN ({', '.join(map(str, DAY_NUMBERS[f.day]))})")
    if f.time_of_day is not None:
        offset = NIGHT_SHIFT_HOURS if f.time_of_day == "night" else 0
        ranges = [f"hour({shifted}) BETWEEN {s0 - offset} AND {e - offset - 1}" for s0, e in TIME_WINDOWS[f.time_of_day]]
        where.append("(" + " OR ".join(ranges) + ")")
    return where, params


class Database:
    def __init__(self, data_dir: Path):
        rollups = str(data_dir / "rollups" / "hourly" / "**" / "*.parquet")
        raw = str(data_dir / "raw" / "**" / "*.parquet")
        self.con = duckdb.connect()
        self.con.execute(f"CREATE VIEW rollups AS SELECT * FROM read_parquet('{rollups}', hive_partitioning = false)")
        self.con.execute(f"CREATE VIEW raw AS SELECT * FROM read_parquet('{raw}', hive_partitioning = false)")
        self.con.execute(f"CREATE TABLE zones AS SELECT LocationID AS zone, Zone AS name, Borough AS borough FROM read_csv('{ZONES_CSV}')")

    def _run(self, sql: str, params: list) -> tuple[list, float]:
        started = time.perf_counter()
        rows = self.con.execute(sql, params).fetchall()
        return rows, (time.perf_counter() - started) * 1000

    def _scanned(self, f: Filters, source: str) -> int:
        """Rows the query had to read: rollup rows, or raw trips, matching the filters."""
        where, params = _where(f, source)
        [(n,)], _ = self._run(f"SELECT count(*) FROM {SOURCES[source]['table']} WHERE {' AND '.join(where)}", params)
        return n

    def total_or_average(self, measure: str, f: Filters, source: str = "rollup") -> QueryResult:
        s = SOURCES[source]
        where, params = _where(f, source)
        sql = f"SELECT {s['measures'][measure]} AS value, {s['trips']} AS trips, count(*) AS scanned FROM {s['table']} WHERE {' AND '.join(where)}"
        [(value, trips, scanned)], ms = self._run(sql, params)
        values = {"value": value, "trips": int(trips or 0), "measure": measure, "unit": MEASURE_UNITS[measure]}
        return QueryResult(sql, [str(p) for p in params], source, scanned, values, ms)

    def ranking(self, measure: str, f: Filters, *, unit_of_rank: str, direction: str, n: int, source: str = "rollup") -> QueryResult:
        s = SOURCES[source]
        zone_col = s["zone"][f.role]
        where, params = _where(f, source)
        where.append(f"{zone_col} NOT IN ({', '.join(map(str, EXCLUDED_ZONES))})")
        min_trips = 1 if measure == "trip_count" else MIN_TRIPS_FOR_AVERAGE_RANKING
        key, label = ("z.zone", "z.name") if unit_of_rank == "zones" else ("z.borough", "z.borough")
        order = "DESC" if direction == "highest" else "ASC"
        sql = (
            f"WITH matched AS (SELECT * FROM {s['table']} WHERE {' AND '.join(where)}) "
            f"SELECT {key} AS id, any_value({label}) AS name, any_value(z.borough) AS borough, {s['measures'][measure]} AS value, {s['trips']} AS trips, "
            f"(SELECT count(*) FROM matched) AS scanned "
            f"FROM matched JOIN zones z ON z.zone = matched.{zone_col} "
            f"GROUP BY {key} HAVING {s['trips']} >= ? ORDER BY value {order}, id LIMIT ?"
        )
        params += [min_trips, n]
        rows, ms = self._run(sql, params)
        ranked = [{"rank": i + 1, "id": r[0], "name": r[1], "borough": r[2], "value": r[3], "trips": int(r[4])} for i, r in enumerate(rows)]
        values = {"rows": ranked, "measure": measure, "unit": MEASURE_UNITS[measure], "rank_unit": unit_of_rank, "direction": direction, "n": n, "min_trips": min_trips, "role": f.role}
        return QueryResult(sql, [str(p) for p in params], source, rows[0][5] if rows else 0, values, ms)

    def trend(self, measure: str, f: Filters, *, grain: str, source: str = "rollup") -> QueryResult:
        assert grain in TREND_GRAINS
        s = SOURCES[source]
        where, params = _where(f, source)
        sql = (
            f"SELECT date_trunc('{grain}', {s['time']})::DATE AS t, {s['measures'][measure]} AS value, {s['trips']} AS trips, count(*) AS scanned "
            f"FROM {s['table']} WHERE {' AND '.join(where)} GROUP BY 1 ORDER BY 1"
        )
        rows, ms = self._run(sql, params)
        # A step cut off by the period's edges (the week of 29 January in a January
        # question) isn't comparable with full ones, so it's marked partial.
        series = [
            {"t": r[0].isoformat(), "value": r[1], "trips": int(r[2]), "complete": r[0] >= f.period.start and _step_end(r[0], grain) <= f.period.end}
            for r in rows
        ]
        values = {"series": series, "grain": grain, "measure": measure, "unit": MEASURE_UNITS[measure]}
        return QueryResult(sql, [str(p) for p in params], source, sum(r[3] for r in rows), values, ms)

    def compare(self, measure: str, groups: list[tuple[str, Filters]], source: str = "rollup") -> QueryResult:
        """The same total or average for each labelled group, run as one query per group."""
        sqls, params, rows, scanned, ms = [], [], [], 0, 0.0
        for label, f in groups:
            q = self.total_or_average(measure, f, source)
            sqls.append(q.sql)
            params.append(q.params)
            rows.append({"label": label, "value": q.values["value"], "trips": q.values["trips"]})
            scanned += q.rows_scanned
            ms += q.ms
        values = {"groups": rows, "measure": measure, "unit": MEASURE_UNITS[measure]}
        return QueryResult(";\n".join(sqls), params, source, scanned, values, ms)

    def distribution(self, variable: str, f: Filters, *, threshold: float | None) -> QueryResult:
        """How a raw-trip column is spread across fixed buckets, and the share below a threshold."""
        column, unit, edges = DISTRIBUTIONS[variable]
        where, params = _where(f, "raw")
        cases = []
        lower = None
        for edge in edges + [None]:
            if lower is None:
                cases.append(f"count(*) FILTER ({column} < {edge})")
            elif edge is None:
                cases.append(f"count(*) FILTER ({column} >= {lower})")
            else:
                cases.append(f"count(*) FILTER ({column} >= {lower} AND {column} < {edge})")
            lower = edge
        below = f", count(*) FILTER ({column} < ?) AS below" if threshold is not None else ""
        sql = f"SELECT count(*) AS trips, {', '.join(cases)}{below} FROM raw WHERE {' AND '.join(where)}"
        run_params = ([threshold] if threshold is not None else []) + params
        [row], ms = self._run(sql, run_params)
        trips = row[0]
        bounds = [None] + edges + [None]
        buckets = [
            {"from": bounds[i], "to": bounds[i + 1], "trips": row[1 + i], "share": row[1 + i] / trips if trips else None}
            for i in range(len(edges) + 1)
        ]
        values = {"variable": variable, "unit": unit, "trips": trips, "buckets": buckets}
        if threshold is not None:
            values["threshold"] = threshold
            values["below"] = row[-1]
            values["share_below"] = row[-1] / trips if trips else None
        return QueryResult(sql, [str(p) for p in run_params], "raw", trips, values, ms)


def _step_end(start: date, grain: str) -> date:
    if grain == "day":
        return start + timedelta(days=1)
    if grain == "week":
        return start + timedelta(days=7)
    if grain == "month":
        return date(start.year + start.month // 12, start.month % 12 + 1, 1)
    return date(start.year + 1, 1, 1)


def with_period(f: Filters, period: Period) -> Filters:
    return replace(f, period=period)
