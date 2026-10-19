"""Trends, comparisons and distributions, and the checks on what the reply may claim.

Fixture figures: yellow trips are 150 in March 2020, 7 in April 2020 and 3,559
in 2023; March 2020 has 200 Uber and 80 Lyft trips; 2023 pickups are 150 in
Brooklyn and 740 in Queens. The raw January 2024 yellow trips put exactly half
under 2 miles.
"""

from __future__ import annotations

import pytest

from taxichat.pipeline import run

from .conftest import NOW, ScriptedWriter


def ask(question, classifier, db, writer=None):
    return run(question, NOW, classifier=classifier, writer=writer, db=db)


def test_monthly_trend(classifier, db):
    trace = ask("Monthly yellow cab trips in 2020", classifier, db)

    assert trace["intent"]["value"] == "trend"
    assert trace["result"]["grain"] == "month"
    assert [(p["t"], p["value"]) for p in trace["result"]["series"]] == [("2020-03-01", 150), ("2020-04-01", 7)]
    assert trace["derived"]["pct_change"] == pytest.approx((7 - 150) / 150 * 100)
    assert trace["source"] == "rollup"


def test_trend_over_a_range_of_years(classifier, db):
    trace = ask("How did yellow cab trips change from 2020 to 2023?", classifier, db)

    assert trace["period"]["label"] == "2020 to 2023"
    assert trace["result"]["grain"] == "year"
    assert [(p["t"], p["value"]) for p in trace["result"]["series"]] == [("2020-01-01", 157), ("2023-01-01", 3559)]


def test_trend_without_a_step_picks_one_from_the_period_and_says_so(classifier, db):
    trace = ask("How have yellow cab trips changed over 2020?", classifier, db)

    assert trace["intent"]["value"] == "trend"
    assert trace["result"]["grain"] == "month"
    assert "by month, since no step was given" in trace["assumptions"]


def test_compares_two_services(classifier, db):
    trace = ask("Uber vs Lyft trips in March 2020", classifier, db)

    assert trace["intent"]["value"] == "compare"
    assert [(g["label"], g["value"]) for g in trace["result"]["groups"]] == [("Uber", 200), ("Lyft", 80)]
    assert trace["derived"]["ratio"] == pytest.approx(2.5)
    assert trace["derived"]["pct_difference"] == pytest.approx(150)


def test_compares_two_places(classifier, db):
    trace = ask("Were there more pickups in Brooklyn or Queens in 2023?", classifier, db)

    assert [(g["label"], g["value"]) for g in trace["result"]["groups"]] == [("Brooklyn", 150), ("Queens", 740)]


def test_compares_two_years(classifier, db):
    trace = ask("How did yellow cab trips in 2020 compare with 2023?", classifier, db)

    assert [(g["label"], g["value"]) for g in trace["result"]["groups"]] == [("2020", 157), ("2023", 3559)]


def test_distribution_uses_the_raw_trips_and_the_threshold_from_the_question(classifier, db):
    trace = ask("What share of yellow cab trips in January 2024 were under 2 miles?", classifier, db)

    assert trace["intent"]["value"] == "distribution"
    assert trace["source"] == "raw"
    assert trace["rows_scanned"] == 8
    assert trace["result"]["threshold"] == 2
    assert trace["derived"]["pct_below"] == pytest.approx(50)
    assert [b["trips"] for b in trace["result"]["buckets"]] == [2, 2, 2, 1, 1]


def test_size_word_without_a_supporting_ratio_is_rejected(classifier, db):
    # Trips rose 22.7x from 2020 to 2023, so "doubled" is wrong even with no number in it.
    writer = ScriptedWriter("Yellow cab trips doubled between 2020 and 2023.", "Yellow cab trips doubled again.")
    trace = ask("How did yellow cab trips change from 2020 to 2023?", classifier, db, writer)

    assert trace["reply_source"] == "template"
    assert not any(c["passed"] for c in trace["checks"] if c["name"].startswith("size_words"))


def test_size_word_backed_by_a_computed_ratio_passes(classifier, db):
    writer = ScriptedWriter("Uber had 2.5 times as many trips as Lyft in March 2020: 200 against 80.")
    trace = ask("Uber vs Lyft trips in March 2020", classifier, db, writer)

    assert trace["reply_source"] == "llm", trace["checks"]


def test_jev_flags_a_claim_the_result_does_not_support(classifier, db):
    writer = ScriptedWriter(
        "There were 150 yellow taxi trips in March 2020, far fewer than usual because of the pandemic lockdown.",
        "There were 150 yellow taxi trips in March 2020.",
    )
    trace = ask("How many yellow cab trips in March 2020?", classifier, db, writer)

    assert trace["reply_source"] == "llm_retry"
    claim_checks = [c for c in trace["checks"] if c["name"].startswith("claim")]
    assert [c["passed"] for c in claim_checks] == [False, True]


@pytest.mark.parametrize(
    "question",
    [
        "How did yellow cab trips change from 2020 to 2023?",
        "Uber vs Lyft trips in March 2020",
        "What share of yellow cab trips in January 2024 were under 2 miles?",
    ],
)
def test_real_writer_replies_pass_every_check(question, classifier, deepseek_writer, db):
    trace = ask(question, classifier, db, deepseek_writer)

    assert trace["reply_source"] in ("llm", "llm_retry"), trace["checks"]


@pytest.mark.parametrize("question, grain", [("Weekly yellow cab trips in 2020", "week"), ("Daily yellow cab trips in March 2020", "day")])
def test_a_named_step_makes_it_a_trend(question, grain, classifier, db):
    trace = ask(question, classifier, db)

    assert trace["intent"]["value"] == "trend"
    assert trace["result"]["grain"] == grain


def test_partial_steps_at_the_edges_are_left_out_of_the_change(classifier, db):
    trace = ask("Weekly yellow cab trips in January 2024", classifier, db)

    assert [(p["t"], p["complete"]) for p in trace["result"]["series"]] == [("2024-01-08", True), ("2024-01-15", True), ("2024-01-29", False)]
    assert trace["derived"]["pct_change"] == pytest.approx(20)  # 100 -> 120, not 100 -> 20
    assert trace["derived"]["partial_left_out"] == 1
    assert "Partial weeks" in trace["reply"]
