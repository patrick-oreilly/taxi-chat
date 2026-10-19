"""Places, day and time filters, and rankings, tested through the pipeline entry point.

The fixture has one Friday night in March 2023 (9pm Friday to 4am Saturday)
surrounded by trips that must not count: an afternoon, a Saturday night, a
5am Saturday, and the Unknown zone with the most trips of all.
"""

from __future__ import annotations

import pytest

from taxichat.pipeline import run
from taxichat.trace import Detail

from .conftest import NOW, Adjusted


def ask(question, classifier, db):
    return run(question, NOW, classifier=classifier, writer=None, db=db)


def test_ranks_pickup_zones_on_friday_nights(classifier, db):
    trace = ask("Top 5 pickup zones on Friday nights in 2023", classifier, db)

    assert trace["intent"]["value"] == "ranking"
    ranked = [(r["name"], r["value"]) for r in trace["result"]["rows"]]
    # Unknown (999 trips), the afternoon and the Saturday trips are all left out.
    assert ranked == [
        ("Midtown Center", 300),
        ("Times Sq/Theatre District", 250),
        ("JFK Airport", 200),
        ("East Village", 120),
        ("Williamsburg (North Side)", 90),
    ]
    assert trace["reply"].startswith("Top 5 pickup zones by trips for all services on Friday nights (9pm to 4am) in 2023: 1. Midtown Center (300)")


def test_ranks_boroughs_lowest_first_with_n_from_the_question(classifier, db):
    trace = ask("What were the 3 quietest boroughs for yellow cabs in 2023?", classifier, db)

    assert [(r["name"], r["value"]) for r in trace["result"]["rows"]] == [("Brooklyn", 150), ("Queens", 740), ("Manhattan", 1670)]
    assert not any("top 5" in a for a in trace["assumptions"])


def test_official_zone_name(classifier, db):
    trace = ask("How many trips from JFK on Friday nights in 2023?", classifier, db)

    assert trace["details"]["place"]["value"] == "zone:132"
    assert trace["result"]["value"] == 200


def test_informal_name_resolves_to_its_zones(classifier, db):
    trace = ask("How many Billyburg pickups on Friday nights in 2023?", classifier, db)

    assert trace["details"]["place"]["value"] == "group:williamsburg"
    assert trace["result"]["value"] == 90 + 60


def test_ambiguous_name_means_all_its_zones_and_says_so(classifier, db):
    trace = ask("How many pickups in Midtown on Friday nights in 2023?", classifier, db)

    assert trace["details"]["place"]["value"] == "group:midtown"
    assert trace["result"]["value"] == 300
    assert "Midtown means all 4 of its zones" in trace["assumptions"]


def test_borough_and_unstated_direction_assume_pickups(classifier, db):
    trace = ask("How many trips in Brooklyn on Friday nights in 2023?", classifier, db)

    assert trace["details"]["place"]["value"] == "borough:brooklyn"
    assert trace["result"]["value"] == 150
    assert "trips that start in Brooklyn" in trace["assumptions"]


def test_similar_name_picks_the_right_zone(classifier, db):
    trace = ask("How many trips in Clinton Hill in 2023?", classifier, db)

    assert trace["details"]["place"]["value"] == "zone:49"


def test_dropoff_questions_are_answered_from_the_raw_trips(classifier, db):
    trace = ask("How many trips to LaGuardia on weekday mornings in January 2024?", classifier, db)

    assert trace["details"]["place_role"]["value"] == "dropoff"
    assert trace["source"] == "raw"
    assert trace["result"]["value"] == 3  # the Saturday-morning LaGuardia trip doesn't count
    assert "to LaGuardia Airport" in trace["reply"]


def test_low_confidence_place_declines(classifier, db):
    unsure = Adjusted(classifier, place=Detail("zone:132", 0.2))
    trace = ask("How many trips from JFK on Friday nights in 2023?", unsure, db)

    assert trace["declined"] == "uncertain_detail"
    assert trace["query"] is None


@pytest.mark.parametrize(
    "question, n",
    [("top 3 zones", 3), ("the ten busiest zones", 10), ("busiest zones in 2023", None), ("top 50 zones", 20)],
)
def test_rank_size_is_read_in_code(question, n):
    from taxichat.pipeline import rank_size

    assert rank_size(question) == n


def test_real_writer_ranking_reply_passes_the_number_check(classifier, deepseek_writer, db):
    trace = run("Top 5 pickup zones on Friday nights in 2023", NOW, classifier=classifier, writer=deepseek_writer, db=db)

    assert trace["reply_source"] in ("llm", "llm_retry"), trace["checks"]
    assert "Midtown Center" in trace["reply"]


def test_singular_question_ranks_one_without_assuming_a_list(classifier, db):
    trace = ask("Which borough had the most yellow cab pickups in 2023?", classifier, db)

    assert [r["name"] for r in trace["result"]["rows"]] == ["Manhattan"]
    assert not any("top 5" in a for a in trace["assumptions"])


def test_borough_rankings_never_include_newark_airport(classifier, db):
    trace = ask("Which borough had the fewest green taxi pickups in 2023?", classifier, db)

    assert [r["name"] for r in trace["result"]["rows"]] == ["Manhattan"]  # not "EWR", whose 5 trips are fewer
