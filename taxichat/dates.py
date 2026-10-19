"""Turn Jev's date-part choices into a concrete period, in code.

Jev picks a year option and a month-or-season option from closed lists (its
docs flag date arithmetic and comparison as unreliable for the model).
Everything after that, including what "last year" or "last summer" means and
whether the period is covered by the data, is decided here against an explicit
current date.

Seasons are meteorological: spring is March to May, summer June to August,
autumn September to November, and winter December to February. A winter
belongs to the year it starts in, so winter 2023 is December 2023 to February
2024. "Last summer" means the most recent summer that has finished.
"""

from __future__ import annotations

from datetime import date

from .trace import Period

DATA_START = date(2019, 1, 1)
DATA_END = date(2026, 1, 1)  # exclusive
DATA_LABEL = "January 2019 to December 2025"

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
SEASONS = {"spring": 3, "summer": 6, "autumn": 9, "winter": 12}  # season -> first month; every season is three months
SEASON_WORDS = {"spring": "March to May", "summer": "June to August", "autumn": "September to November", "winter": "December to February"}
YEARS = [str(y) for y in range(2019, 2027)]
YEAR_WORDS = {
    "this_year": "Says this year or the current year in words",
    "last_year": "Says last year or the previous year in words",
    "most_recent": "Means the most recent one without naming a year, such as last summer, last March or this past winter",
    "earlier_year": "Names a specific year before 2019",
    "later_year": "Names a specific year after 2026",
    "not_stated": "Names no year and no relative time",
}
YEAR_OPTIONS = YEARS + list(YEAR_WORDS)
MONTH_OPTIONS = MONTHS + list(SEASONS) + ["not_stated"]
# Years outside the options are only ever declined, so any year beyond the
# data stands in for them; only the label shown to the user names the gap.
OUTSIDE_YEARS = {"earlier_year": (2018, "a year before 2019"), "later_year": (2027, "a year after 2026")}


def _add_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def _build(month: str, year: int) -> Period:
    """The period for a month, season or whole year (month == "not_stated") starting in `year`."""
    if month == "not_stated":
        return Period(date(year, 1, 1), date(year + 1, 1, 1), str(year))
    if month in SEASONS:
        start = date(year, SEASONS[month], 1)
        label = f"winter {year}–{str(year + 1)[2:]}" if month == "winter" else f"{month} {year}"
        return Period(start, _add_months(start, 3), label)
    start = date(year, MONTHS.index(month) + 1, 1)
    return Period(start, _add_months(start, 1), f"{month.title()} {year}")


def _most_recent(month: str, today: date) -> Period:
    """The latest occurrence of a month that has started, or of a season that has finished."""
    for year in range(today.year, today.year - 3, -1):
        period = _build(month, year)
        if (period.end <= today) if month in SEASONS else (period.start <= today):
            return period
    raise AssertionError("unreachable")


def resolve_period(year: str, month: str, today: date) -> tuple[Period, list[str]]:
    """Return the period and any assumptions made filling in what wasn't stated."""
    assumptions: list[str] = []
    if month in SEASONS:
        assumptions.append(f"{month} means {SEASON_WORDS[month]}")

    if year in OUTSIDE_YEARS:
        stand_in, label = OUTSIDE_YEARS[year]
        period = _build(month, stand_in)
        return Period(period.start, period.end, label), assumptions

    if month == "not_stated":
        if year == "not_stated":
            assumptions.append(f"the whole period the data covers ({DATA_LABEL}), since no time was given")
            return Period(DATA_START, DATA_END, DATA_LABEL), assumptions
        if year in ("last_year", "most_recent"):
            return _build(month, today.year - 1), assumptions
        if year == "this_year":
            return _build(month, today.year), assumptions
        return _build(month, int(year)), assumptions

    if year == "this_year":
        return _build(month, today.year), assumptions
    if year == "last_year":
        return _build(month, today.year - 1), assumptions
    if year in ("most_recent", "not_stated"):
        period = _most_recent(month, today)
        name = month if month in SEASONS else month.title()
        what = f"the most recent {'finished ' if month in SEASONS else ''}{name}"
        assumptions.append(f"{what}, {period.label}" + (", since no year was given" if year == "not_stated" else ""))
        return period, assumptions
    return _build(month, int(year)), assumptions


def covered(period: Period) -> bool:
    return period.start >= DATA_START and period.end <= DATA_END


def nearest_covered(month: str, period: Period) -> Period | None:
    """The same month, season or year shifted by whole years until the data covers it."""
    step = -1 if period.end > DATA_END else 1
    for shift in range(1, 30):
        candidate = _build(month, period.start.year + step * shift)
        if covered(candidate):
            return candidate
    return None
