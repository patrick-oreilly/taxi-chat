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


# Words that claim a size without a number, and the ratio each implies.
SIZE_WORDS = {
    "doubled": 2, "double": 2, "twice": 2, "tripled": 3, "triple": 3, "three times": 3,
    "quadrupled": 4, "four times": 4, "halved": 0.5, "half": 0.5,
}
SIZE_TOLERANCE = 0.15  # "doubled" is fine for a ratio of 1.7 to 2.3; "nearly double" lands in that too
SIZE_PATTERN = re.compile(r"\b(" + "|".join(sorted(map(re.escape, SIZE_WORDS), key=len, reverse=True)) + r")\b", re.IGNORECASE)


def check_size_words(reply: str, ratios: list[float]) -> Check:
    """Every size word must be backed by a ratio computed in code."""
    unsupported = [
        match.group(0)
        for match in SIZE_PATTERN.finditer(reply)
        if not any(abs(r - SIZE_WORDS[match.group(0).lower()]) <= SIZE_TOLERANCE * SIZE_WORDS[match.group(0).lower()] for r in ratios)
    ]
    if unsupported:
        return Check("size_words", False, "no computed ratio supports: " + ", ".join(unsupported))
    return Check("size_words", True)


def check_numbers(reply: str, allowed: list[float]) -> Check:
    unsupported = [
        written
        for written, value, tolerance in numbers_in(reply)
        if not any(abs(value - a) <= tolerance + 1e-9 for a in allowed)
    ]
    if unsupported:
        return Check("numbers", False, "not in the result: " + ", ".join(unsupported))
    return Check("numbers", True)
