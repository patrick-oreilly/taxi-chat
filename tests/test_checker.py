"""The number checker accepts faithful rounding and rejects anything else."""

from __future__ import annotations

import pytest

from taxichat.checker import check_numbers

ALLOWED = [41_213_887, 18.6532, 2020, 2019, 2025]


@pytest.mark.parametrize(
    "reply",
    [
        "There were 41,213,887 trips in 2020.",
        "About 41.2 million trips in 2020.",
        "Roughly 41 million trips.",
        "41M trips.",
        "The average fare was $18.65.",
        "The average fare was about $19.",
        "Data covers 2019 to 2025.",
        "No numbers at all.",
    ],
)
def test_accepts_numbers_from_the_result(reply):
    assert check_numbers(reply, ALLOWED).passed


@pytest.mark.parametrize(
    "reply, bad",
    [
        ("About 40 million trips.", "40 million"),
        ("Trips rose 18% in 2020.", "18%"),
        ("The average fare was $18.70.", "$18.70"),
        ("There were 41,213,888 trips.", "41,213,888"),
        ("Fares were $18.65, up from 2017.", "2017"),
    ],
)
def test_rejects_numbers_not_in_the_result(reply, bad):
    check = check_numbers(reply, ALLOWED)
    assert not check.passed
    assert bad in check.detail
