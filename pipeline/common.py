"""Paths and month helpers shared by the pipeline stages."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
LANDING = DATA / "landing"  # files exactly as TLC publishes them
RAW = DATA / "raw"  # one cleaned, unified-schema file per service-month
ROLLUPS = DATA / "rollups" / "hourly"
MANIFESTS = DATA / "manifests"
REF = DATA / "ref"

SERVICES = ("yellow", "green", "fhvhv")
TLC_BASE = "https://d37ci6vzurychx.cloudfront.net"


@dataclass(frozen=True, order=True)
class Month:
    year: int
    month: int

    @classmethod
    def parse(cls, text: str) -> "Month":
        year, month = text.split("-")
        return cls(int(year), int(month))

    def __str__(self) -> str:
        return f"{self.year}-{self.month:02d}"

    def next(self) -> "Month":
        return Month(self.year + self.month // 12, self.month % 12 + 1)


def month_range(start: str, end: str) -> list[Month]:
    """Inclusive range of months, e.g. month_range("2019-01", "2019-03")."""
    months, current, last = [], Month.parse(start), Month.parse(end)
    while current <= last:
        months.append(current)
        current = current.next()
    return months


def landing_path(service: str, month: Month) -> Path:
    return LANDING / service / f"{service}_tripdata_{month}.parquet"


def partition(base: Path, service: str, month: Month) -> Path:
    return base / f"service={service}" / f"year={month.year}" / f"month={month.month:02d}" / "data.parquet"


def manifest_path(service: str, month: Month) -> Path:
    return MANIFESTS / service / f"{month}.json"


def read_manifest(service: str, month: Month) -> dict | None:
    path = manifest_path(service, month)
    return json.loads(path.read_text()) if path.exists() else None


def write_json(path: Path, payload: dict) -> None:
    # Write then rename, so a crash never leaves a half-written manifest that a
    # rerun would trust.
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str))
    tmp.replace(path)
