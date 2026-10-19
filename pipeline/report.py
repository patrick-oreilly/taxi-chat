"""Total the per-month manifests into the numbers the README publishes.

    uv run python -m pipeline.report

Reads only the manifests, so the counts are exactly what the normalise stage
recorded, and it also lists any month that is missing between the first and
last month present for each service.
"""

from __future__ import annotations

import json
from collections import Counter

from .common import MANIFESTS, SERVICES, Month, month_range


def main() -> None:
    manifests = [json.loads(p.read_text()) for p in sorted(MANIFESTS.glob("*/*.json"))]
    if not manifests:
        raise SystemExit("no manifests yet; run the normalise stage first")

    rows_in = sum(m["rows_in"] for m in manifests)
    rows_out = sum(m["rows_out"] for m in manifests)
    rejected = Counter()
    for m in manifests:
        rejected.update(m["rejected"])

    print(f"trips kept   {rows_out:>15,}")
    print(f"rows read    {rows_in:>15,}")
    print(f"rejected     {rows_in - rows_out:>15,}  ({100 * (rows_in - rows_out) / rows_in:.2f}%)")
    for reason, count in rejected.most_common():
        print(f"  {reason:<22} {count:>13,}  ({100 * count / rows_in:.3f}%)")

    print()
    for service in SERVICES:
        months = sorted(Month.parse(m["month"]) for m in manifests if m["service"] == service)
        if not months:
            print(f"{service:<7} no data")
            continue
        kept = sum(m["rows_out"] for m in manifests if m["service"] == service)
        expected = month_range(str(months[0]), str(months[-1]))
        gaps = [str(m) for m in expected if m not in set(months)]
        print(f"{service:<7} {kept:>15,} trips  {months[0]} to {months[-1]}  missing: {', '.join(gaps) or 'none'}")


if __name__ == "__main__":
    main()
