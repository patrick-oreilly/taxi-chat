"""The single entry point: a question and the current date in, an answer trace out.

    for event in answer(question, now, classifier=..., writer=..., db=...): ...
    trace = run(question, now, classifier=..., writer=..., db=...)

`answer` yields one event per stage as it completes (the web page streams
these) and finishes with a "done" event carrying the full trace. The eval and
the tests call the same function, so they exercise exactly what the page does.

Answers totals, averages, rankings, trends, comparisons and distributions.
"""

from __future__ import annotations

import re
import time
from dataclasses import replace
from datetime import date, datetime
from typing import Iterator

from .checker import check_numbers, check_size_words, numbers_in
from .classify import Classification
from .dates import DATA_END, DATA_LABEL, DATA_START, covered, nearest_covered, resolve_period
from .places import all_places, candidates
from .derived import derive
from .queries import Database, Filters
from .trace import AnswerTrace, Check, Detail, Period
from .writer import MEASURE_WORDS, SERVICE_WORDS, TIME_NUMBERS, facts_for, scope_words, template_reply

# Starting points; the eval tunes these on the tuning split.
THRESHOLDS = {"intent": 0.6, "detail": 0.5, "injection": 0.5, "compound": 0.5, "single": 0.5, "claim": 0.5, "unanswerable": 0.5}

SUPPORTED_INTENTS = {"total_or_average", "ranking", "trend", "compare", "distribution"}

# Only these details are gated for each intent: a total question's "direction"
# is meaningless, so a low confidence on it must not decline the question.
_COMMON = ["service", "year", "month", "place", "place_role", "day", "time_of_day"]
RELEVANT_DETAILS = {
    "total_or_average": ["measure", *_COMMON],
    "ranking": ["measure", *_COMMON, "direction", "rank_unit"],
    "trend": ["measure", *_COMMON],  # its step and end year are handled where they're used
    "compare": ["measure", *_COMMON, "compare_by"],
    "distribution": ["distribution_of", *_COMMON],
}
# A comparison also gates the detail that names its second item.
COMPARE_SECOND = {"services": "service_b", "places": "place_b", "periods": "year_to"}

DEFAULT_RANK_N = 5
MAX_RANK_N = 20
NUMBER_WORDS = {w: i for i, w in enumerate("one two three four five six seven eight nine ten".split(), start=1)}
THRESHOLD_PATTERN = re.compile(
    r"\b(?:under|below|less than|shorter than|cheaper than|over|above|more than|longer than)\s+"
    r"(?:\$\s?)?(\d+(?:\.\d+)?|half an?|an|a|one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|forty|fifty|sixty)"
    r"\s*(hours?|hrs?)?"
)
THRESHOLD_WORDS = {"a": 1, "an": 1, "half a": 0.5, "half an": 0.5, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, **NUMBER_WORDS}

DECLINE_MESSAGES = {
    "injection": "That reads like instructions rather than a question about the trip data, so I won't act on it.",
    "compound": "That asks more than one thing. Ask them one at a time and I'll answer each.",
    "out_of_scope": "That isn't something the NYC trip records can answer.",
    "uncertain_intent": "I'm not confident what you're asking. Try rephrasing it as a question about trips, fares, tips, distance or duration.",
    "not_supported_yet": "I can't answer that kind of question yet.",
    "missing_second": "That compares two things, but I couldn't tell which {what} is the second one. Try naming both.",
    "uncertain_detail": "I'm not confident about part of your question ({detail}). Try stating it more directly.",
    "outside_data": f"I don't have data for {{period}}; the data covers {DATA_LABEL}. The nearest period I can answer is {{nearest}}.",
}


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def rank_size(question: str) -> int | None:
    """The N in "top N", read in code; None when the question doesn't give one."""
    for word in re.findall(r"[a-z0-9]+", question.lower()):
        if word.isdigit() and len(word) <= 2:
            return max(1, min(int(word), MAX_RANK_N))
        if word in NUMBER_WORDS:
            return NUMBER_WORDS[word]
    return None


def threshold_in(question: str) -> float | None:
    """The 2 in "under 2 miles", read in code; None when there isn't one.

    Words count too ("less than a dollar", "over half an hour"), and hours become
    minutes, the unit durations are measured in."""
    match = THRESHOLD_PATTERN.search(question.lower())
    if not match:
        return None
    amount, hours = match.groups()
    value = float(amount) if amount[0].isdigit() else float(THRESHOLD_WORDS[amount])
    return value * 60 if hours else value


def steps_in(period: Period, grain: str) -> int:
    """How many steps of `grain` the period spans (a partial step counts)."""
    if grain == "day":
        return (period.end - period.start).days
    if grain == "week":
        return -(-(period.end - period.start).days // 7)
    months = (period.end.year - period.start.year) * 12 + period.end.month - period.start.month
    return months if grain == "month" else -(-months // 12)


def _year(option: str, today) -> int | None:
    """A year option as a number, or None when it doesn't name one."""
    if option in ("this_year",):
        return today.year
    if option in ("last_year", "most_recent"):
        return today.year - 1
    return int(option) if option.isdigit() else None


def _numbers(value) -> list[float]:
    """Every number written anywhere in the facts, which the reply may therefore use."""
    if isinstance(value, dict):
        return [n for v in value.values() for n in _numbers(v)]
    if isinstance(value, list):
        return [n for v in value for n in _numbers(v)]
    if isinstance(value, (int, float)):
        return [value]
    return [n for _, n, _ in numbers_in(str(value))]


def _empty(intent: str, values: dict) -> bool:
    if intent == "ranking":
        return not values["rows"]
    if intent == "trend":
        return not values["series"]
    if intent == "compare":
        return all(g["trips"] == 0 for g in values["groups"])
    if intent == "distribution":
        return values["trips"] == 0
    return values["value"] is None


def answer(question: str, now: datetime, *, classifier, writer, db: Database) -> Iterator[dict]:
    trace = AnswerTrace(question=question, now=now.isoformat())
    today = now.date()

    def decline(reason: str, **fmt) -> Iterator[dict]:
        trace.declined = reason
        trace.decline_message = DECLINE_MESSAGES[reason].format(**fmt)
        trace.decline_source = "fixed"
        yield {"stage": "declined", "reason": reason, "message": trace.decline_message}
        yield {"stage": "done", "trace": trace.to_dict()}

    started = time.perf_counter()
    options = candidates(question)
    trace.place_candidates = [p.key for p in options]
    c: Classification = classifier.classify(question, options)
    trace.timings_ms["classify"] = _ms(started)
    trace.models["classifier"] = c.model
    trace.intent = c.intent
    trace.details = {
        name: getattr(c, name)
        for name in ("measure", "service", "year", "month", "place", "place_role", "day", "time_of_day", "direction",
                     "rank_unit", "grain", "year_to", "compare_by", "service_b", "place_b", "distribution_of")
    }
    yield {"stage": "classified", "intent": c.intent.__dict__, "details": {k: v.__dict__ for k, v in trace.details.items()}, "injection": c.injection, "compound": c.compound}

    # Order matters: each check assumes the ones before it passed.
    if c.injection >= THRESHOLDS["injection"]:
        yield from decline("injection")
        return
    if c.compound >= THRESHOLDS["compound"]:
        yield from decline("compound")
        return
    if c.intent.value == "out_of_scope" or c.unanswerable >= THRESHOLDS["unanswerable"]:
        yield from decline("out_of_scope")
        return
    # Jev wavers between a single total and a trend for "weekly trips in 2023", but
    # its step answer doesn't. A named step settles it once the period is known:
    # more than one step is a series, one step ("trips last year") is a total.
    step_named = c.intent.value in ("total_or_average", "trend") and c.grain.value != "not_stated" and c.grain.confidence >= THRESHOLDS["detail"]
    if c.intent.confidence < THRESHOLDS["intent"] and not step_named:
        yield from decline("uncertain_intent")
        return
    if c.intent.value not in SUPPORTED_INTENTS:
        yield from decline("not_supported_yet")
        return
    intent = c.intent.value
    gated = RELEVANT_DETAILS[intent] + ([COMPARE_SECOND[c.compare_by.value]] if intent == "compare" else [])
    for name in gated:
        if trace.details[name].confidence < THRESHOLDS["detail"]:
            yield from decline("uncertain_detail", detail=name.replace("_", " "))
            return

    if c.service.value == "not_stated":
        trace.details["service"] = Detail("all", c.service.confidence, defaulted=True)
        trace.assumptions.append("all services, since none was named")
    service = trace.details["service"].value
    role = "dropoff" if c.place_role.value == "dropoff" else "pickup"

    def place_assumptions(place) -> None:
        if c.place_role.value == "not_stated":
            trace.assumptions.append(f"trips that start in {place.label}")
        if place.kind == "group":
            trace.assumptions.append(f"{place.label} means all {len(place.zone_ids)} of its zones")

    place = all_places()[c.place.value] if c.place.value != "no_place" else None
    if place is not None:
        place_assumptions(place)

    period, date_assumptions = resolve_period(c.year.value, c.month.value, today)
    trace.assumptions += date_assumptions
    day = None if c.day.value == "not_stated" else c.day.value
    time_of_day = None if c.time_of_day.value == "not_stated" else c.time_of_day.value

    # A range of years ("from 2019 to 2024") widens a trend's period. Uncertainty
    # only matters when the end year would change the answer: wavering between
    # "2020" and "not stated" for "monthly trips in 2020" is harmless.
    year_to = _year(c.year_to.value, today)
    widens = (intent == "trend" or step_named) and year_to is not None and c.month.value == "not_stated" and year_to != period.start.year and period.end.year - period.start.year == 1
    if widens and c.year_to.confidence < THRESHOLDS["detail"]:
        yield from decline("uncertain_detail", detail="end year")
        return
    if widens:
        first, last = sorted((period.start.year, year_to))
        period = Period(date(first, 1, 1), date(last + 1, 1, 1), f"{first} to {last}")
    trace.period = period

    step_too_coarse = False
    if step_named:
        confident_trend = intent == "trend" and c.intent.confidence >= THRESHOLDS["intent"]
        if steps_in(period, c.grain.value) > 1:
            decided = "trend"
        elif confident_trend:
            decided, step_too_coarse = "trend", True  # "how did trips change over 2022?" still wants a series
        else:
            decided = "total_or_average"
        if decided != intent or c.intent.confidence < THRESHOLDS["intent"]:
            trace.notes.append(
                f"treated as a {decided.replace('_', ' ')}: a {c.grain.value}-by-{c.grain.value} step gives "
                f"{steps_in(period, c.grain.value)} figure(s) for {period.label} (step confidence {c.grain.confidence:.2f})"
            )
        intent = decided
        trace.intent = Detail(decided, max(c.intent.confidence, c.grain.confidence))

    n = None
    if intent == "ranking":
        n = rank_size(question)
        if n is None and c.single >= THRESHOLDS["single"]:
            n = 1  # "which zone had the most" asks for one, not a default list
        if n is None:
            n = DEFAULT_RANK_N
            trace.assumptions.append(f"the top {n}, since no number was given")
        if c.measure.value != "trip_count":
            trace.assumptions.append("only places with at least 100 trips, so a handful of trips can't top an average")

    grain = None
    if intent == "trend":
        # The step is presentation, not correctness: an unsure one gets the stated default.
        grain = c.grain.value if c.grain.confidence >= THRESHOLDS["detail"] and not step_too_coarse else "not_stated"
        if grain == "not_stated":
            days = (period.end - period.start).days
            grain = "day" if days <= 62 else "month" if days <= 731 else "year"
            why = f"{c.grain.value}-by-{c.grain.value} gives one figure for {period.label}" if step_too_coarse else "no step was given"
            trace.assumptions.append(f"by {grain}, since {why}")

    base = Filters(period, service, place.zone_ids if place else None, day, time_of_day, role)
    groups = None
    compare_by = c.compare_by.value if intent == "compare" else None
    if compare_by == "services":
        if c.service_b.value == "not_stated" or service == "all":
            yield from decline("missing_second", what="service")
            return
        groups = [(SERVICE_WORDS[service], base), (SERVICE_WORDS[c.service_b.value], replace(base, service=c.service_b.value))]
    elif compare_by == "places":
        if place is None or c.place_b.value == "no_place" or c.place_b.value == c.place.value:
            yield from decline("missing_second", what="place")
            return
        place_b = all_places()[c.place_b.value]
        place_assumptions(place_b)
        groups = [(place.label, base), (place_b.label, replace(base, zone_ids=place_b.zone_ids))]
    elif compare_by == "periods":
        if year_to is None or year_to == period.start.year:
            yield from decline("missing_second", what="period")
            return
        period_b, _ = resolve_period(str(year_to), c.month.value, today)
        if not covered(period_b):
            yield from decline_outside_data(question, now, period_b, c.month.value, trace, writer)
            return
        groups = [(period.label, base), (period_b.label, replace(base, period=period_b))]

    yield {"stage": "resolved", "period": period.label, "service": service, "place": place.label if place else None, "role": role, "day": day, "time_of_day": time_of_day, "assumptions": trace.assumptions}

    if not covered(period):
        yield from decline_outside_data(question, now, period, c.month.value, trace, writer)
        return

    # The rollups are keyed by pickup and hold sums; anything else needs the raw trips.
    source = "raw" if role == "dropoff" or intent == "distribution" else "rollup"
    measure = c.measure.value
    if intent == "ranking":
        q = db.ranking(measure, base, unit_of_rank=c.rank_unit.value, direction=c.direction.value, n=n, source=source)
    elif intent == "trend":
        q = db.trend(measure, base, grain=grain, source=source)
    elif intent == "compare":
        q = db.compare(measure, groups, source=source)
    elif intent == "distribution":
        q = db.distribution(c.distribution_of.value, base, threshold=threshold_in(question))
    else:
        q = db.total_or_average(measure, base, source=source)
    trace.query, trace.source, trace.rows_scanned, trace.result = q.sql, q.source, q.rows_scanned, q.values
    trace.timings_ms["query"] = round(q.ms, 1)
    yield {"stage": "queried", "sql": q.sql, "params": q.params, "source": q.source, "rows_scanned": q.rows_scanned, "result": q.values}

    scope = scope_words(
        None if compare_by == "services" else service,
        None if compare_by == "places" or not place else place.label,
        day,
        time_of_day,
        None if compare_by == "periods" else period.label,
        role,
    )
    if _empty(intent, q.values):
        trace.reply, trace.reply_source = f"There are no trips for {scope} in the data.", "template"
        yield {"stage": "written", "reply": trace.reply, "source": "template"}
        yield {"stage": "done", "trace": trace.to_dict()}
        return
    derived, ratios = derive(intent, q.values)
    trace.derived = derived
    facts = facts_for(intent, q.values, derived)
    template = template_reply(intent, measure, scope, q.values, derived, trace.assumptions)

    if writer is None:
        # No language model configured: the template is the reply.
        trace.reply, trace.reply_source = template, "template"
        yield {"stage": "written", "reply": trace.reply, "source": "template"}
        yield {"stage": "done", "trace": trace.to_dict()}
        return

    allowed: list[float] = [period.start.year, period.end.year - 1, DATA_START.year, DATA_END.year - 1, now.year]
    allowed += TIME_NUMBERS.get(time_of_day, []) + _numbers(facts) + _numbers(q.values)
    allowed += [n for g in (groups or []) for n in _numbers(g[0])]
    details_words = {"question_type": intent.replace("_", " "), "measure": MEASURE_WORDS.get(measure, measure), "scope": scope}
    if intent == "ranking":
        details_words["ranking"] = f"{'top' if c.direction.value == 'highest' else 'bottom'} {n} {c.rank_unit.value} by {role}s"
    if compare_by:
        details_words["comparing"] = compare_by
    feedback = None
    for attempt in ("llm", "llm_retry"):
        started = time.perf_counter()
        reply = writer.write(question=question, details=details_words, facts=facts, assumptions=trace.assumptions, today=today.isoformat(), feedback=feedback)
        trace.timings_ms[f"write_{attempt}"] = _ms(started)
        checks = [check_numbers(reply, allowed), check_size_words(reply, ratios)]
        if all(ch.passed for ch in checks) and hasattr(classifier, "unsupported_claim"):
            started = time.perf_counter()
            # The check must see everything the writer saw about what the figures cover, or a
            # reply naming the service and period would read as a claim beyond the result.
            p = classifier.unsupported_claim(reply, {"about": details_words, "facts": facts, "assumptions": trace.assumptions})
            trace.timings_ms[f"claim_{attempt}"] = _ms(started)
            checks.append(Check("claim", p < THRESHOLDS["claim"], f"Jev rates an unsupported claim at {p:.2f}"))
        trace.checks += [Check(f"{ch.name}:{attempt}", ch.passed, ch.detail) for ch in checks]
        failed = [ch for ch in checks if not ch.passed]
        yield {"stage": "checked", "attempt": attempt, "reply": reply, "passed": not failed, "detail": "; ".join(ch.detail for ch in failed)}
        if not failed:
            trace.reply, trace.reply_source = reply, attempt
            break
        feedback = "; ".join(ch.detail for ch in failed)
    else:
        trace.reply, trace.reply_source = template, "template"

    trace.models["writer"] = getattr(writer, "model", "unknown")
    yield {"stage": "written", "reply": trace.reply, "source": trace.reply_source}
    yield {"stage": "done", "trace": trace.to_dict()}


def decline_outside_data(question: str, now: datetime, period, month: str, trace: AnswerTrace, writer) -> Iterator[dict]:
    """Decline a period the data doesn't cover, suggesting the nearest one it does.

    The decision is made in code; the writer only phrases it, and its reply
    may mention no number or date beyond the requested period, the coverage
    and the suggestion, and must include the suggestion and the coverage.
    """
    nearest = nearest_covered(month, period)
    trace.declined = "outside_data"
    trace.nearest_period = nearest
    fixed = DECLINE_MESSAGES["outside_data"].format(period=period.label, nearest=nearest.label)
    trace.decline_message, trace.decline_source = fixed, "fixed"

    if writer is not None:
        facts = {"REQUESTED_PERIOD": period.label, "DATA_COVERS": DATA_LABEL, "NEAREST_AVAILABLE": nearest.label}
        allowed = [value for text in facts.values() for _, value, _ in numbers_in(text)] + [now.year]
        must_mention = [written for written, _, _ in numbers_in(nearest.label)] + [str(DATA_END.year - 1)]
        feedback = None
        for source in ("llm", "llm_retry"):
            started = time.perf_counter()
            reply = writer.write_decline(question=question, facts=facts, today=now.date().isoformat(), feedback=feedback)
            trace.timings_ms[f"decline_{source}"] = _ms(started)
            check = check_numbers(reply, allowed)
            if check.passed and (missing := [m for m in must_mention if m not in reply]):
                check = Check("numbers", False, "must mention the coverage and the suggested period: missing " + ", ".join(missing))
            trace.checks.append(Check(f"decline:{source}", check.passed, check.detail))
            yield {"stage": "checked", "attempt": source, "reply": reply, "passed": check.passed, "detail": check.detail}
            if check.passed:
                trace.decline_message, trace.decline_source = reply, source
                break
            feedback = check.detail
        else:
            trace.decline_source = "template"
        trace.models["writer"] = getattr(writer, "model", "unknown")

    yield {"stage": "declined", "reason": "outside_data", "message": trace.decline_message, "nearest": nearest.label}
    yield {"stage": "done", "trace": trace.to_dict()}


def run(question: str, now: datetime, **deps) -> dict:
    """Run the pipeline to completion and return the final trace."""
    for event in answer(question, now, **deps):
        if event["stage"] == "done":
            return event["trace"]
    raise AssertionError("pipeline ended without a done event")
