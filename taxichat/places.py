"""Place candidates for a question, found in code before Jev chooses.

A Jev Choice allows at most 255 options and NYC has 265 taxi zones, so code
narrows the field: every zone, every group of zones that share a name (the
four Midtowns, both Williamsburgs), every borough and a few well-known
nicknames are fuzzy-matched against the words of the question, and the best
five go to Jev as options alongside "no place".
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz

ZONES_CSV = Path(__file__).parent / "zones.csv"
EXCLUDED_ZONES = (264, 265)  # TLC's "Unknown" and "Outside of NYC"
# TLC gives Newark Airport its own "borough", EWR; borough rankings are over these five.
BOROUGHS = ("Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island")
CANDIDATES = 5

# Informal names that fuzzy matching can't be trusted to find.
NICKNAMES = {
    "billyburg": "group:williamsburg",
    "hells kitchen": "group:clinton",
    "hell's kitchen": "group:clinton",
    "fidi": "group:financial district",
    "ues": "group:upper east side",
    "uws": "group:upper west side",
    "les": "zone:148",
    "times square": "zone:230",
    "jfk": "zone:132",
    "lga": "zone:138",
    "laguardia": "zone:138",
    "newark": "zone:1",
    "ewr": "zone:1",
}


@dataclass(frozen=True)
class Place:
    key: str  # the option name Jev sees, e.g. "zone:132", "group:midtown", "borough:brooklyn"
    label: str  # how replies name it
    description: str  # what Jev reads for this option
    zone_ids: tuple[int, ...]
    kind: str  # "zone", "group" or "borough"


def _group_name(zone: str) -> str:
    return re.sub(r"\s*\(.*?\)|\s+(North|South|East|West|Center|Central)$", "", zone).strip()


@lru_cache(maxsize=1)
def all_places() -> dict[str, Place]:
    with ZONES_CSV.open() as f:
        rows = [r for r in csv.DictReader(f) if int(r["LocationID"]) not in EXCLUDED_ZONES]

    places: dict[str, Place] = {}
    by_name: dict[str, list[dict]] = defaultdict(list)
    by_group: dict[str, list[dict]] = defaultdict(list)
    by_borough: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        by_name[row["Zone"]].append(row)
        by_group[_group_name(row["Zone"])].append(row)
        by_borough[row["Borough"]].append(int(row["LocationID"]))

    for name, same in by_name.items():
        if len(same) == 1:  # zones sharing an exact name are only offered as their group
            row = same[0]
            places[f"zone:{row['LocationID']}"] = Place(
                f"zone:{row['LocationID']}", name, f"{name}, a zone in {row['Borough']}", (int(row["LocationID"]),), "zone"
            )
    for group, members in by_group.items():
        if len(members) > 1:
            names = ", ".join(sorted({m["Zone"] for m in members}))
            places[f"group:{group.lower()}"] = Place(
                f"group:{group.lower()}",
                group,
                f"{group} as a whole: all {len(members)} zones ({names})",
                tuple(sorted(int(m["LocationID"]) for m in members)),
                "group",
            )
    for borough, ids in by_borough.items():
        if borough not in ("EWR", "N/A", "Unknown"):  # EWR is just the Newark Airport zone
            places[f"borough:{borough.lower()}"] = Place(
                f"borough:{borough.lower()}", borough, f"the whole borough of {borough}", tuple(sorted(ids)), "borough"
            )
    return places


def _ngrams(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9']+", text.lower())
    return [" ".join(words[i : i + n]) for n in range(1, 5) for i in range(len(words) - n + 1)]


def _names(place: Place) -> list[str]:
    # "Times Sq/Theatre District" can be referred to by either half.
    return [part.strip().lower() for part in re.split(r"/", place.label) if part.strip()]


def nicknames_in(question: str) -> dict[str, str]:
    """Nicknames code recognised, so Jev can be told what they mean."""
    lowered = " " + " ".join(re.findall(r"[a-z0-9']+", question.lower())) + " "
    places = all_places()
    return {nick: places[key].description for nick, key in NICKNAMES.items() if f" {nick} " in lowered}


def candidates(question: str) -> list[Place]:
    """The five places the question most plausibly refers to, best first."""
    places = all_places()
    grams = _ngrams(question)
    scores: dict[str, float] = {}
    for key, place in places.items():
        # Ties go to the longer name, so "Clinton Hill" beats "Clinton" for "clinton hill".
        scores[key] = max((fuzz.ratio(name, gram) + len(name) / 1000 for name in _names(place) for gram in grams), default=0)
    lowered = " " + " ".join(re.findall(r"[a-z0-9']+", question.lower())) + " "
    for nickname, key in NICKNAMES.items():
        if f" {nickname} " in lowered:
            scores[key] = 101  # a known nickname outranks any fuzzy score
    best = sorted(scores, key=lambda k: (-scores[k], k))[:CANDIDATES]
    return [places[k] for k in best]
