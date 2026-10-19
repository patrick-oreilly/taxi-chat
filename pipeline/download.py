"""Download TLC monthly trip files into data/landing.

    uv run python -m pipeline.download --from 2019-01 --to 2025-12
    uv run python -m pipeline.download --services yellow --from 2024-01 --to 2024-02

Resumable: a file only lands under its real name once its size matches what
the server reported, so an interrupted run never leaves a truncated file that
a later stage would read. Months TLC hasn't published yet (404) are skipped.
"""

from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

from .common import REF, SERVICES, TLC_BASE, Month, landing_path, month_range

ATTEMPTS = 5


def fetch(client: httpx.Client, url: str, dest) -> str:
    head = client.head(url)
    if head.status_code == 404:
        return "not published"
    head.raise_for_status()
    expected = int(head.headers["content-length"])
    if dest.exists() and dest.stat().st_size == expected:
        return "already have"

    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                with part.open("wb") as out:
                    for chunk in response.iter_bytes(1 << 20):
                        out.write(chunk)
            if part.stat().st_size != expected:
                raise IOError(f"got {part.stat().st_size} bytes, expected {expected}")
            part.replace(dest)
            return f"downloaded {expected / 1e6:.0f} MB"
        except (httpx.HTTPError, IOError) as error:
            if attempt == ATTEMPTS:
                part.unlink(missing_ok=True)
                raise RuntimeError(f"{url}: {error}") from error
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--services", nargs="+", default=list(SERVICES), choices=SERVICES)
    parser.add_argument("--from", dest="start", required=True)
    parser.add_argument("--to", dest="end", required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    jobs = [(s, m) for s in args.services for m in month_range(args.start, args.end)]
    failures = 0
    with httpx.Client(timeout=httpx.Timeout(30, read=120), follow_redirects=True) as client:
        zones = REF / "taxi_zone_lookup.csv"
        if not zones.exists():
            fetch(client, f"{TLC_BASE}/misc/taxi_zone_lookup.csv", zones)

        with ThreadPoolExecutor(args.workers) as pool:
            futures = {
                pool.submit(fetch, client, f"{TLC_BASE}/trip-data/{s}_tripdata_{m}.parquet", landing_path(s, m)): (s, m)
                for s, m in jobs
            }
            for future in as_completed(futures):
                service, month = futures[future]
                try:
                    print(f"{service} {month}: {future.result()}", flush=True)
                except RuntimeError as error:
                    failures += 1
                    print(f"{service} {month}: FAILED {error}", flush=True)
    if failures:
        raise SystemExit(f"{failures} file(s) failed; rerun to retry just those")


if __name__ == "__main__":
    main()
