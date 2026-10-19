"""Check that every number in a reply comes from the query result.

A number in the reply passes if it equals an allowed value rounded to the
precision the reply shows: 41,213,887 may appear as "41.2 million" or
"41 million", but not "about 40 million". Allowed values are the result's
numbers plus the years the answer legitimately mentions.
"""

from __future__ import annotations

import re

from .trace import Check

SCALES = {"thousand": 1e3, "k": 1e3, "million": 1e6, "m": 1e6, "mn": 1e6, "billion": 1e9, "bn": 1e9, "b": 1e9}

NUMBER = re.compile(
    r"(?<![\w.])\$?(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?:\.(?P<frac>\d+))?"
    r"\s?(?P<scale>thousand|million|billion|mn|bn|k|m|b)?(?P<pct>%)?(?![\w])",
    re.IGNORECASE,
)


def numbers_in(text: str) -> list[tuple[str, float, float]]:
    """Each number as (as written, value, tolerance from its shown precision)."""
    found = []
    for match in NUMBER.finditer(text):
        mantissa = float(match["int"].replace(",", "") + ("." + match["frac"] if match["frac"] else ""))
        scale = SCALES[match["scale"].lower()] if match["scale"] else 1.0
        decimals = len(match["frac"] or "")
        found.append((match.group(0).strip(), mantissa * scale, 0.5 * 10**-decimals * scale))
    return found


def check_numbers(reply: str, allowed: list[float]) -> Check:
    unsupported = [
        written
        for written, value, tolerance in numbers_in(reply)
        if not any(abs(value - a) <= tolerance + 1e-9 for a in allowed)
    ]
    if unsupported:
        return Check("numbers", False, "not in the result: " + ", ".join(unsupported))
    return Check("numbers", True)
