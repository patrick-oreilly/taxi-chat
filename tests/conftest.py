"""Shared fixtures: a tiny rollup dataset with known answers, and Jev and DeepSeek via
recorded responses.

Run with RECORD=1 (and TYPESAFE_API_KEY and DEEPSEEK_API_KEY set) to call the
real APIs and refresh tests/recordings; otherwise every call is replayed offline.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import duckdb
import pytest

from taxichat.classify import JEV_URL, JevClassifier
from taxichat.queries import Database
from taxichat.transport import HttpTransport, RecordingTransport, ReplayTransport
from taxichat.writer import DEEPSEEK_URL, DeepSeekWriter

RECORDINGS = Path(__file__).parent / "recordings"
NOW = datetime(2026, 10, 19, 12, 0)

# (service, company, hour, zone, trips, tipped, fare_sum, tip_sum, total_sum, distance_sum, duration_s_sum)
ROLLUP_ROWS = [
    ("yellow", "yellow", "2020-03-01 10:00", 161, 100, 60, 1500.0, 300.0, 2100.0, 250.0, 90000.0),
    ("yellow", "yellow", "2020-03-31 23:00", 230, 50, 20, 1000.0, 100.0, 1300.0, 150.0, 45000.0),
    ("yellow", "yellow", "2020-04-01 00:00", 161, 7, 3, 140.0, 14.0, 180.0, 21.0, 6300.0),
    ("green", "green", "2020-03-10 08:00", 74, 10, 2, 120.0, 8.0, 150.0, 30.0, 9000.0),
    ("fhvhv", "uber", "2020-03-05 18:00", 132, 200, 40, 5000.0, 400.0, 6500.0, 900.0, 300000.0),
    ("fhvhv", "lyft", "2020-03-05 18:00", 132, 80, 20, 1800.0, 160.0, 2400.0, 340.0, 110000.0),
    # Friday 3 March 2023 night (9pm to 4am Saturday), plus traps around it.
    ("yellow", "yellow", "2023-03-03 22:00", 161, 300, 0, 0.0, 0.0, 0.0, 0.0, 0.0),  # Midtown Center
    ("yellow", "yellow", "2023-03-03 23:00", 230, 250, 0, 0.0, 0.0, 0.0, 0.0, 0.0),  # Times Sq
    ("yellow", "yellow", "2023-03-04 01:00", 132, 200, 0, 0.0, 0.0, 0.0, 0.0, 0.0),  # JFK, still Friday night
    ("yellow", "yellow", "2023-03-03 21:00", 79, 120, 0, 0.0, 0.0, 0.0, 0.0, 0.0),  # East Village
    ("yellow", "yellow", "2023-03-03 22:00", 255, 90, 0, 0.0, 0.0, 0.0, 0.0, 0.0),  # Williamsburg North
    ("yellow", "yellow", "2023-03-03 22:00", 256, 60, 0, 0.0, 0.0, 0.0, 0.0, 0.0),  # Williamsburg South
    ("yellow", "yellow", "2023-03-03 22:00", 264, 999, 0, 0.0, 0.0, 0.0, 0.0, 0.0),  # Unknown: never ranked
    ("yellow", "yellow", "2023-03-03 14:00", 138, 500, 0, 0.0, 0.0, 0.0, 0.0, 0.0),  # LaGuardia, afternoon
    ("yellow", "yellow", "2023-03-04 22:00", 161, 1000, 0, 0.0, 0.0, 0.0, 0.0, 0.0),  # Saturday night
    ("yellow", "yellow", "2023-03-04 05:00", 132, 40, 0, 0.0, 0.0, 0.0, 0.0, 0.0),  # Saturday 5am, not Friday night
    # January 2024 weeks: 8th and 15th are whole weeks; the week of the 29th is cut off by the month's end.
    ("yellow", "yellow", "2024-01-10 12:00", 161, 100, 0, 0.0, 0.0, 0.0, 0.0, 0.0),
    ("yellow", "yellow", "2024-01-17 12:00", 161, 120, 0, 0.0, 0.0, 0.0, 0.0, 0.0),
    ("yellow", "yellow", "2024-01-30 12:00", 161, 20, 0, 0.0, 0.0, 0.0, 0.0, 0.0),
]


# Raw trips in January 2024: (service, company, pickup_at, minutes, pickup_zone, dropoff_zone, distance_mi, fare, tip)
# Monday 8 January 8am has three trips to LaGuardia (138); yellow distances put exactly half under 2 miles.
RAW_TRIPS = [
    ("yellow", "yellow", "2024-01-08 08:05", 20, 161, 138, 0.5, 8.0, 1.0),
    ("yellow", "yellow", "2024-01-08 08:30", 25, 230, 138, 0.8, 9.0, 2.0),
    ("yellow", "yellow", "2024-01-08 09:10", 30, 79, 138, 1.5, 15.0, 3.0),
    ("yellow", "yellow", "2024-01-08 14:00", 10, 161, 132, 1.9, 18.0, 0.0),
    ("yellow", "yellow", "2024-01-09 08:00", 15, 132, 161, 3.0, 22.0, 4.0),
    ("yellow", "yellow", "2024-01-13 08:00", 12, 79, 138, 4.0, 25.0, 5.0),  # Saturday: not a weekday morning
    ("yellow", "yellow", "2024-01-15 19:00", 18, 161, 230, 6.0, 30.0, 6.0),
    ("yellow", "yellow", "2024-01-20 23:00", 40, 132, 79, 12.0, 60.0, 12.0),
    ("fhvhv", "uber", "2024-01-10 12:00", 22, 161, 79, 2.5, 20.0, 2.0),
    ("fhvhv", "uber", "2024-01-11 12:00", 35, 79, 132, 7.0, 45.0, 5.0),
]


@pytest.fixture(scope="session")
def db(tmp_path_factory) -> Database:
    root = tmp_path_factory.mktemp("data")
    con = duckdb.connect()
    con.execute(
        """CREATE TABLE r (service VARCHAR, company VARCHAR, hour TIMESTAMP, pickup_zone SMALLINT, trips BIGINT,
        tipped_trips BIGINT, fare_sum DOUBLE, tip_sum DOUBLE, total_sum DOUBLE, distance_sum DOUBLE, duration_s_sum DOUBLE)"""
    )
    con.executemany("INSERT INTO r VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", ROLLUP_ROWS)
    for service, year, month in con.execute("SELECT DISTINCT service, year(hour), month(hour) FROM r").fetchall():
        out = root / "rollups" / "hourly" / f"service={service}" / f"year={year}" / f"month={month:02d}"
        out.mkdir(parents=True)
        con.execute(
            f"COPY (SELECT * FROM r WHERE service = ? AND year(hour) = ? AND month(hour) = ?) TO '{out / 'data.parquet'}' (FORMAT parquet)",
            [service, year, month],
        )
    con.execute(
        """CREATE TABLE t AS SELECT service, company, pickup_at::TIMESTAMP AS pickup_at, pickup_at::TIMESTAMP + to_minutes(minutes) AS dropoff_at,
        pickup_zone::SMALLINT AS pickup_zone, dropoff_zone::SMALLINT AS dropoff_zone, NULL::TINYINT AS passengers, distance_mi, fare, tip,
        fare + tip AS total, NULL::TINYINT AS payment_type
        FROM (VALUES """ + ", ".join("(?, ?, ?, ?, ?, ?, ?, ?, ?)" for _ in RAW_TRIPS) + """) v(service, company, pickup_at, minutes, pickup_zone, dropoff_zone, distance_mi, fare, tip)""",
        [value for trip in RAW_TRIPS for value in trip],
    )
    for (service,) in con.execute("SELECT DISTINCT service FROM t").fetchall():
        out = root / "raw" / f"service={service}" / "year=2024" / "month=01"
        out.mkdir(parents=True)
        con.execute(f"COPY (SELECT * FROM t WHERE service = ? ORDER BY pickup_at) TO '{out / 'data.parquet'}' (FORMAT parquet)", [service])
    return Database(root)


@pytest.fixture(scope="session")
def classifier() -> JevClassifier:
    path = RECORDINGS / "jev.json"
    if os.environ.get("RECORD") == "1":
        transport = RecordingTransport(HttpTransport(JEV_URL, os.environ.get("TYPESAFE_API_KEY", "")), path)
    else:
        transport = ReplayTransport(path)
    return JevClassifier(transport)


@pytest.fixture(scope="session")
def deepseek_writer() -> DeepSeekWriter:
    path = RECORDINGS / "deepseek.json"
    if os.environ.get("RECORD") == "1":
        transport = RecordingTransport(HttpTransport(DEEPSEEK_URL, os.environ.get("DEEPSEEK_API_KEY", "")), path)
    else:
        transport = ReplayTransport(path)
    return DeepSeekWriter(transport)


class ScriptedWriter:
    """Returns the given replies in order and remembers what it was asked."""

    model = "scripted"

    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.calls: list[dict] = []

    def write(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return self.replies.pop(0)

    write_decline = write


class Adjusted:
    """Wraps a classifier and overrides parts of its classification, to reach
    gate branches that real questions only hit unpredictably."""

    def __init__(self, inner, **overrides):
        self.inner = inner
        self.overrides = overrides

    def __getattr__(self, name):
        return getattr(self.inner, name)  # the claim check and anything else pass straight through

    def classify(self, question: str, places):
        classification = self.inner.classify(question, places)
        for name, value in self.overrides.items():
            setattr(classification, name, value)
        return classification
