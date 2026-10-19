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
