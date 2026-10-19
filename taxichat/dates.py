"""Turn Jev's date-part choices into a concrete period, in code.

Jev picks a year option and a month option from closed lists (its docs flag
date arithmetic and comparison as unreliable for the model). Everything after
that, including what "last year" means and whether the period is covered by
the data, is decided here against an explicit current date.
"""

from __future__ import annotations

from datetime import date

from .trace import Period

DATA_START = date(2019, 1, 1)
DATA_END = date(2026, 1, 1)  # exclusive
DATA_LABEL = "January 2019 to December 2025"

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
YEARS = [str(y) for y in range(2019, 2027)]
YEAR_OPTIONS = YEARS + ["this_year", "last_year", "not_stated"]
MONTH_OPTIONS = MONTHS + ["not_stated"]


def _next_month(day: date) -> date:
    return date(day.year + day.month // 12, day.month % 12 + 1, 1)


def resolve_period(year: str, month: str, today: date) -> tuple[Period, list[str]]:
    """Return the period and any assumptions made filling in what wasn't stated."""
    assumptions: list[str] = []
    if year == "this_year":
        year_num: int | None = today.year
    elif year == "last_year":
        year_num = today.year - 1
    elif year == "not_stated":
        year_num = None
    else:
        year_num = int(year)

    if month == "not_stated":
        if year_num is None:
            assumptions.append(f"the whole period the data covers ({DATA_LABEL}), since no time was given")
            return Period(DATA_START, DATA_END, DATA_LABEL), assumptions
        return Period(date(year_num, 1, 1), date(year_num + 1, 1, 1), str(year_num)), assumptions

    month_num = MONTHS.index(month) + 1
    if year_num is None:
        # A month with no year means its most recent occurrence up to today.
        year_num = today.year if month_num <= today.month else today.year - 1
        assumptions.append(f"the most recent {month.title()}, {year_num}, since no year was given")
    start = date(year_num, month_num, 1)
    return Period(start, _next_month(start), f"{month.title()} {year_num}"), assumptions


def covered(period: Period) -> bool:
    return period.start >= DATA_START and period.end <= DATA_END
