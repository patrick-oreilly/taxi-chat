"""The data pipeline, tested one service-month at a time on tiny Parquet files.

The fixtures reproduce the drift seen in real TLC files (column casing, INT32
vs INT64 vs DOUBLE, fee columns that appear in 2025) and one row per rejection
rule. Tests assert only on what the stages write: the output files and the
manifests.
"""

from __future__ import annotations

import json
import os

import duckdb
import httpx
import pytest

from pipeline import common, download, normalise, report, rollup
from pipeline.common import Month, write_json

UNIFIED_SCHEMA = [
    ("service", "VARCHAR"),
    ("company", "VARCHAR"),
    ("pickup_at", "TIMESTAMP"),
    ("dropoff_at", "TIMESTAMP"),
    ("pickup_zone", "SMALLINT"),
    ("dropoff_zone", "SMALLINT"),
    ("passengers", "TINYINT"),
    ("distance_mi", "DOUBLE"),
    ("fare", "DOUBLE"),
    ("tip", "DOUBLE"),
    ("total", "DOUBLE"),
    ("payment_type", "TINYINT"),
]


@pytest.fixture
def data(tmp_path, monkeypatch):
    """Point every stage at an empty data directory under tmp_path."""
    paths = {
        "LANDING": tmp_path / "landing",
        "RAW": tmp_path / "raw",
        "ROLLUPS": tmp_path / "rollups" / "hourly",
        "MANIFESTS": tmp_path / "manifests",
        "REF": tmp_path / "ref",
    }
    for module in (common, download, normalise, rollup, report):
        for name, path in paths.items():
            if hasattr(module, name):
                monkeypatch.setattr(module, name, path)
    return tmp_path


@pytest.fixture
def con():
    return duckdb.connect()


def write_landing(con, service: str, month: Month, select_sql: str):
    """Write a landing file from a SELECT whose casts fix each column's Parquet type."""
    path = common.landing_path(service, month)
    path.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY ({select_sql}) TO '{path}' (FORMAT parquet)")
    return path


def yellow_select(rows, *, location_type, passenger_type, airport_column, with_cbd):
    """rows: (pickup, dropoff, pu, do, distance, fare, tip, total)."""
    values = ",\n".join(
        "(" + ", ".join("NULL" if v is None else f"'{v}'" if isinstance(v, str) else str(v) for v in row) + ")"
        for row in rows
    )
    cbd = ", CAST(0.75 AS DOUBLE) AS cbd_congestion_fee" if with_cbd else ""
    return f"""
        SELECT
            CAST(1 AS {location_type}) AS VendorID,
            CAST(p AS TIMESTAMP) AS tpep_pickup_datetime,
            CAST(d AS TIMESTAMP) AS tpep_dropoff_datetime,
            CAST(1 AS {passenger_type}) AS passenger_count,
            CAST(dist AS DOUBLE) AS trip_distance,
            CAST(pu AS {location_type}) AS PULocationID,
            CAST(dz AS {location_type}) AS DOLocationID,
            CAST(1 AS BIGINT) AS payment_type,
            CAST(fare AS DOUBLE) AS fare_amount,
            CAST(tip AS DOUBLE) AS tip_amount,
            CAST(total AS DOUBLE) AS total_amount,
            CAST(1.75 AS DOUBLE) AS "{airport_column}"
            {cbd}
        FROM (VALUES {values}) t(p, d, pu, dz, dist, fare, tip, total)
    """


def schema_of(con, path):
    return [(name, type_) for name, type_, *_ in con.execute("DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning = false)", [str(path)]).fetchall()]


def manifest(service: str, month: Month) -> dict:
    return json.loads(common.manifest_path(service, month).read_text())


JAN = Month(2024, 1)
MAR_2025 = Month(2025, 3)

# Kept rows are deliberately out of pickup order; zone 264 ("Unknown") is valid.
YELLOW_JAN_ROWS = [
    ("2024-01-20 10:00:00", "2024-01-20 10:20:00", 161, 230, 2.5, 15.0, 3.0, 21.0),
    ("2024-01-05 08:00:00", "2024-01-05 08:10:00", 132, 161, 12.0, 50.0, 10.0, 70.0),
    ("2024-01-31 23:50:00", "2024-02-01 00:05:00", 264, 79, 1.0, 8.0, 0.0, 10.0),
    # One row per rejection rule.
    (None, "2024-01-10 10:00:00", 161, 161, 1.0, 5.0, 0.0, 6.0),  # missing_timestamp
    ("2023-12-31 23:00:00", "2023-12-31 23:10:00", 161, 161, 1.0, 5.0, 0.0, 6.0),  # outside_file_month
    ("2024-01-10 10:00:00", "2024-01-10 09:00:00", 161, 161, 1.0, 5.0, 0.0, 6.0),  # dropoff_before_pickup
    ("2024-01-10 10:00:00", "2024-01-11 11:00:00", 161, 161, 1.0, 5.0, 0.0, 6.0),  # over_24_hours
    ("2024-01-10 10:00:00", "2024-01-10 10:10:00", 0, 161, 1.0, 5.0, 0.0, 6.0),  # unknown_zone
    ("2024-01-10 10:00:00", "2024-01-10 10:10:00", 161, 161, 1.0, -5.0, 0.0, -6.0),  # negative_money
    ("2024-01-10 10:00:00", "2024-01-10 10:10:00", 161, 161, 600.0, 5.0, 0.0, 6.0),  # implausible_distance
    # Breaks two rules; only the first in rule order counts.
    ("2023-12-31 23:00:00", "2023-12-31 23:10:00", 161, 161, 1.0, -5.0, 0.0, -6.0),  # outside_file_month
]


def land_yellow_jan(con):
    return write_landing(
        con, "yellow", JAN,
        yellow_select(YELLOW_JAN_ROWS, location_type="BIGINT", passenger_type="DOUBLE", airport_column="airport_fee", with_cbd=False),
    )


def land_yellow_2025(con):
    rows = [("2025-03-02 12:00:00", "2025-03-02 12:30:00", 236, 161, 3.0, 20.0, 4.0, 30.0)]
    return write_landing(
        con, "yellow", MAR_2025,
        yellow_select(rows, location_type="INTEGER", passenger_type="BIGINT", airport_column="Airport_fee", with_cbd=True),
    )


def land_green_jan(con):
    return write_landing(con, "green", JAN, """
        SELECT
            CAST('2024-01-03 09:00:00' AS TIMESTAMP) AS lpep_pickup_datetime,
            CAST('2024-01-03 09:15:00' AS TIMESTAMP) AS lpep_dropoff_datetime,
            CAST(2.0 AS DOUBLE) AS passenger_count,
            CAST(1.8 AS DOUBLE) AS trip_distance,
            CAST(74 AS BIGINT) AS PULocationID,
            CAST(75 AS BIGINT) AS DOLocationID,
            CAST(2.0 AS DOUBLE) AS payment_type,
            CAST(11.0 AS DOUBLE) AS fare_amount,
            CAST(0.0 AS DOUBLE) AS tip_amount,
            CAST(13.5 AS DOUBLE) AS total_amount,
            CAST(NULL AS INTEGER) AS ehail_fee
    """)


def fhvhv_select(rows, *, with_cbd):
    """rows: (licence, pickup, base_fare, tips, tolls, bcf, sales_tax, congestion, airport, cbd)."""
    values = ",\n".join(
        "(" + ", ".join("NULL" if v is None else f"'{v}'" if isinstance(v, str) else str(v) for v in row) + ")"
        for row in rows
    )
    cbd = ", CAST(cbd AS DOUBLE) AS cbd_congestion_fee" if with_cbd else ""
    return f"""
        SELECT
            lic AS hvfhs_license_num,
            CAST(p AS TIMESTAMP) AS pickup_datetime,
            CAST(p AS TIMESTAMP) + INTERVAL 20 MINUTE AS dropoff_datetime,
            CAST(132 AS BIGINT) AS PULocationID,
            CAST(161 AS BIGINT) AS DOLocationID,
            CAST(4.2 AS DOUBLE) AS trip_miles,
            CAST(1200 AS BIGINT) AS trip_time,
            CAST(base AS DOUBLE) AS base_passenger_fare,
            CAST(tolls AS DOUBLE) AS tolls,
            CAST(bcf AS DOUBLE) AS bcf,
            CAST(tax AS DOUBLE) AS sales_tax,
            CAST(cong AS DOUBLE) AS congestion_surcharge,
            CAST(airport AS DOUBLE) AS airport_fee,
            CAST(tips AS DOUBLE) AS tips
            {cbd}
        FROM (VALUES {values}) t(lic, p, base, tips, tolls, bcf, tax, cong, airport, cbd)
    """


def land_fhvhv_jan(con):
    rows = [
        ("HV0003", "2024-01-02 18:00:00", 20.0, 3.0, 1.0, 0.5, 1.5, 2.75, None, 0),
        ("HV0005", "2024-01-01 07:00:00", 30.0, 0.0, 0.0, 0.8, 2.0, 2.75, 2.5, 0),
        ("HV0099", "2024-01-03 12:00:00", 10.0, 1.0, 0.0, 0.2, 0.8, 0.0, 0.0, 0),
    ]
    return write_landing(con, "fhvhv", JAN, fhvhv_select(rows, with_cbd=False))


def land_fhvhv_2025(con):
    rows = [("HV0003", "2025-03-04 08:00:00", 25.0, 2.0, 0.0, 0.6, 1.9, 2.75, 0.0, 1.5)]
    return write_landing(con, "fhvhv", MAR_2025, fhvhv_select(rows, with_cbd=True))


# --- normalise ---------------------------------------------------------------


def test_every_service_and_year_lands_in_the_unified_schema(data, con):
    land_yellow_jan(con), land_yellow_2025(con), land_green_jan(con), land_fhvhv_jan(con), land_fhvhv_2025(con)
    for service, month in [("yellow", JAN), ("yellow", MAR_2025), ("green", JAN), ("fhvhv", JAN), ("fhvhv", MAR_2025)]:
        normalise.normalise(con, service, month, force=False)
        out = common.partition(common.RAW, service, month)
        assert schema_of(con, out) == UNIFIED_SCHEMA, f"{service} {month}"


def test_output_is_sorted_by_pickup_time(data, con):
    land_yellow_jan(con)
    normalise.normalise(con, "yellow", JAN, force=False)

    pickups = [r[0] for r in con.execute("SELECT pickup_at FROM read_parquet(?)", [str(common.partition(common.RAW, "yellow", JAN))]).fetchall()]
    assert pickups == sorted(pickups)
    assert len(pickups) == 3


def test_each_rejection_rule_is_counted_under_its_reason(data, con):
    land_yellow_jan(con)
    normalise.normalise(con, "yellow", JAN, force=False)

    m = manifest("yellow", JAN)
    assert m["rows_in"] == len(YELLOW_JAN_ROWS)
    assert m["rows_out"] == 3  # including the trip in zone 264 ("Unknown"), which is valid
    assert m["rejected"] == {
        "missing_timestamp": 1,
        "outside_file_month": 2,  # the row breaking two rules counts once, under the first
        "dropoff_before_pickup": 1,
        "over_24_hours": 1,
        "unknown_zone": 1,
        "negative_money": 1,
        "implausible_distance": 1,
    }
    assert m["rows_in"] - m["rows_out"] == sum(m["rejected"].values())


def test_fee_columns_are_read_whatever_their_casing_or_presence(data, con):
    land_yellow_2025(con)
    normalise.normalise(con, "yellow", MAR_2025, force=False)

    m = manifest("yellow", MAR_2025)
    assert m["rows_out"] == 1
    assert "airport_fee" in m["source_columns"] and "cbd_congestion_fee" in m["source_columns"]
    row = con.execute("SELECT passengers, pickup_zone, total FROM read_parquet(?)", [str(common.partition(common.RAW, "yellow", MAR_2025))]).fetchone()
    assert row == (1, 236, 30.0)


def test_green_double_payment_type_is_cast(data, con):
    land_green_jan(con)
    normalise.normalise(con, "green", JAN, force=False)

    row = con.execute("SELECT company, passengers, payment_type FROM read_parquet(?)", [str(common.partition(common.RAW, "green", JAN))]).fetchone()
    assert row == ("green", 2, 2)


def test_rideshare_company_and_rider_paid_total(data, con):
    land_fhvhv_jan(con), land_fhvhv_2025(con)
    normalise.normalise(con, "fhvhv", JAN, force=False)
    normalise.normalise(con, "fhvhv", MAR_2025, force=False)

    jan = con.execute("SELECT company, fare, tip, total, passengers, payment_type FROM read_parquet(?) ORDER BY pickup_at", [str(common.partition(common.RAW, "fhvhv", JAN))]).fetchall()
    assert jan == [
        ("lyft", 30.0, 0.0, pytest.approx(30.0 + 0.0 + 0.0 + 0.8 + 2.0 + 2.75 + 2.5), None, None),
        ("uber", 20.0, 3.0, pytest.approx(20.0 + 3.0 + 1.0 + 0.5 + 1.5 + 2.75), None, None),  # NULL airport fee counts as 0
        ("other", 10.0, 1.0, pytest.approx(10.0 + 1.0 + 0.2 + 0.8), None, None),
    ]
    mar = con.execute("SELECT total FROM read_parquet(?)", [str(common.partition(common.RAW, "fhvhv", MAR_2025))]).fetchone()[0]
    assert mar == pytest.approx(25.0 + 2.0 + 0.6 + 1.9 + 2.75 + 1.5)  # includes the 2025 congestion fee


def test_unchanged_month_is_skipped_and_forced_month_is_rebuilt(data, con):
    land_yellow_jan(con)
    normalise.normalise(con, "yellow", JAN, force=False)
    out = common.partition(common.RAW, "yellow", JAN)
    written = out.stat().st_mtime_ns

    assert normalise.normalise(con, "yellow", JAN, force=False) == "up to date"
    assert out.stat().st_mtime_ns == written

    assert "kept of" in normalise.normalise(con, "yellow", JAN, force=True)
    assert out.stat().st_mtime_ns != written


def test_changed_landing_file_is_rebuilt(data, con):
    source = land_yellow_jan(con)
    normalise.normalise(con, "yellow", JAN, force=False)
    stat = source.stat()
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    assert "kept of" in normalise.normalise(con, "yellow", JAN, force=False)


def test_missing_landing_file_is_reported_not_raised(data, con):
    assert normalise.normalise(con, "yellow", JAN, force=False) == "no landing file"


# --- rollup ------------------------------------------------------------------


def test_rollup_reconciles_with_raw_rows(data, con):
    land_yellow_jan(con), land_fhvhv_jan(con)
    for service in ("yellow", "fhvhv"):
        normalise.normalise(con, service, JAN, force=False)
        rollup.rollup(con, service, JAN, force=False)

        raw = str(common.partition(common.RAW, service, JAN))
        rolled = str(common.partition(common.ROLLUPS, service, JAN))
        expected = con.execute(
            "SELECT count(*), count(*) FILTER (tip > 0), sum(fare), sum(tip), sum(total), sum(distance_mi), sum(epoch(dropoff_at - pickup_at)) FROM read_parquet(?)",
            [raw],
        ).fetchone()
        actual = con.execute(
            "SELECT sum(trips), sum(tipped_trips), sum(fare_sum), sum(tip_sum), sum(total_sum), sum(distance_sum), sum(duration_s_sum) FROM read_parquet(?)",
            [rolled],
        ).fetchone()
        assert actual == pytest.approx(expected), service


def test_rollup_has_one_row_per_hour_zone_and_company(data, con):
    land_fhvhv_jan(con)
    normalise.normalise(con, "fhvhv", JAN, force=False)
    rollup.rollup(con, "fhvhv", JAN, force=False)

    rows = con.execute(
        "SELECT company, hour, pickup_zone, trips FROM read_parquet(?) ORDER BY hour",
        [str(common.partition(common.ROLLUPS, "fhvhv", JAN))],
    ).fetchall()
    assert [(r[0], r[1].hour, r[2], r[3]) for r in rows] == [("lyft", 7, 132, 1), ("uber", 18, 132, 1), ("other", 12, 132, 1)]


def test_rollup_skips_when_up_to_date(data, con):
    land_green_jan(con)
    normalise.normalise(con, "green", JAN, force=False)
    assert "rollup rows" in rollup.rollup(con, "green", JAN, force=False)
    assert rollup.rollup(con, "green", JAN, force=False) == "up to date"
    assert "rollup rows" in rollup.rollup(con, "green", JAN, force=True)


# --- report ------------------------------------------------------------------


def fake_manifest(service, month, rows_in, rows_out, rejected):
    write_json(common.manifest_path(service, Month.parse(month)), {"service": service, "month": month, "rows_in": rows_in, "rows_out": rows_out, "rejected": rejected})


def test_report_totals_manifests_and_finds_missing_months(data, capsys):
    fake_manifest("yellow", "2024-01", 100, 90, {"negative_money": 10})
    fake_manifest("yellow", "2024-03", 50, 49, {"unknown_zone": 1})
    fake_manifest("fhvhv", "2024-01", 1000, 1000, {})

    report.main()
    out = " ".join(capsys.readouterr().out.split())  # column padding isn't the behaviour under test
    assert "trips kept 1,139" in out
    assert "rows read 1,150" in out
    assert "rejected 11 (0.96%)" in out
    assert "negative_money 10" in out and "unknown_zone 1" in out
    assert "yellow 139 trips 2024-01 to 2024-03 missing: 2024-02" in out
    assert "fhvhv 1,000 trips 2024-01 to 2024-01 missing: none" in out
    assert "green no data" in out


def test_report_without_manifests_exits(data):
    with pytest.raises(SystemExit):
        report.main()


# --- download ----------------------------------------------------------------

URL = "https://cdn.example/trip-data/yellow_tripdata_2024-01.parquet"


def mock_client(*, head_status=200, size=10, body=b"x" * 10, calls=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request.method)
        if request.method == "HEAD":
            return httpx.Response(head_status, headers={"content-length": str(size)})
        return httpx.Response(200, content=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(download.time, "sleep", lambda seconds: None)


@pytest.mark.parametrize("status", [403, 404])
def test_unpublished_month_is_skipped(tmp_path, status):
    dest = tmp_path / "yellow_tripdata_2024-01.parquet"
    assert download.fetch(mock_client(head_status=status), URL, dest) == "not published"
    assert not dest.exists()


def test_complete_download_is_renamed_into_place(tmp_path):
    dest = tmp_path / "landing" / "yellow_tripdata_2024-01.parquet"
    assert download.fetch(mock_client(), URL, dest).startswith("downloaded")
    assert dest.read_bytes() == b"x" * 10
    assert list(dest.parent.glob("*.part")) == []


def test_file_of_the_right_size_is_not_downloaded_again(tmp_path):
    dest = tmp_path / "yellow_tripdata_2024-01.parquet"
    dest.write_bytes(b"y" * 10)
    calls = []
    assert download.fetch(mock_client(calls=calls), URL, dest) == "already have"
    assert calls == ["HEAD"]
    assert dest.read_bytes() == b"y" * 10


def test_truncated_download_never_lands_and_leaves_no_part_file(tmp_path, no_sleep):
    dest = tmp_path / "yellow_tripdata_2024-01.parquet"
    calls = []
    with pytest.raises(RuntimeError, match="expected 10"):
        download.fetch(mock_client(body=b"x" * 8, calls=calls), URL, dest)
    assert calls.count("GET") == download.ATTEMPTS
    assert not dest.exists()
    assert list(tmp_path.glob("*.part")) == []
