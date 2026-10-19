"""The single entry point: a question and the current date in, an answer trace out.

    for event in answer(question, now, classifier=..., writer=..., db=...): ...
    trace = run(question, now, classifier=..., writer=..., db=...)

`answer` yields one event per stage as it completes (the web page streams
these) and finishes with a "done" event carrying the full trace. The eval and
the tests call the same function, so they exercise exactly what the page does.

So far totals/averages and rankings are answered; the other intents decline
as not supported until their own tickets land.
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Iterator

from .checker import check_numbers
from .classify import Classification
from .dates import DATA_END, DATA_LABEL, DATA_START, covered, resolve_period
from .places import all_places, candidates
from .queries import Database, Filters
from .trace import AnswerTrace, Check, Detail
from .writer import MEASURE_WORDS, SERVICE_WORDS, TIME_NUMBERS, facts_for, scope_words, template_reply

# Starting points; the eval tunes these on the tuning split.
THRESHOLDS = {"intent": 0.6, "detail": 0.5, "injection": 0.5}

SUPPORTED_INTENTS = {"total_or_average", "ranking"}

# Only these details are gated for each intent: a total question's "direction"
# is meaningless, so a low confidence on it must not decline the question.
RELEVANT_DETAILS = {
    "total_or_average": ["measure", "service", "year", "month", "place", "place_role", "day", "time_of_day"],
    "ranking": ["measure", "service", "year", "month", "place", "day", "time_of_day", "direction", "rank_unit"],
}

DEFAULT_RANK_N = 5
MAX_RANK_N = 20
NUMBER_WORDS = {w: i for i, w in enumerate("one two three four five six seven eight nine ten".split(), start=1)}

DECLINE_MESSAGES = {
    "injection": "That reads like instructions rather than a question about the trip data, so I won't act on it.",
    "out_of_scope": "That isn't something the NYC trip records can answer.",
    "uncertain_intent": "I'm not confident what you're asking. Try rephrasing it as a question about trips, fares, tips, distance or duration.",
    "not_supported_yet": "I can answer totals, averages and rankings so far; trends, comparisons and distributions are coming.",
    "dropoff_not_supported_yet": "Questions about where trips end need the raw trip data, which I can't search yet; I can answer about where trips start.",
    "uncertain_detail": "I'm not confident about part of your question ({detail}). Try stating it more directly.",
    "outside_data": f"I don't have data for {{period}}; the data covers {DATA_LABEL}.",
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


def answer(question: str, now: datetime, *, classifier, writer, db: Database) -> Iterator[dict]:
    trace = AnswerTrace(question=question, now=now.isoformat())

    def decline(reason: str, **fmt) -> Iterator[dict]:
        trace.declined = reason
        trace.decline_message = DECLINE_MESSAGES[reason].format(**fmt)
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
        "measure": c.measure, "service": c.service, "year": c.year, "month": c.month, "place": c.place,
        "place_role": c.place_role, "day": c.day, "time_of_day": c.time_of_day, "direction": c.direction, "rank_unit": c.rank_unit,
    }
    yield {"stage": "classified", "intent": c.intent.__dict__, "details": {k: v.__dict__ for k, v in trace.details.items()}, "injection": c.injection}

    if c.injection >= THRESHOLDS["injection"]:
        yield from decline("injection")
        return
    if c.intent.value == "out_of_scope":
        yield from decline("out_of_scope")
        return
    if c.intent.confidence < THRESHOLDS["intent"]:
        yield from decline("uncertain_intent")
        return
    if c.intent.value not in SUPPORTED_INTENTS:
        yield from decline("not_supported_yet")
        return
    intent = c.intent.value
    for name in RELEVANT_DETAILS[intent]:
        if trace.details[name].confidence < THRESHOLDS["detail"]:
            yield from decline("uncertain_detail", detail=name.replace("_", " "))
            return

    if c.service.value == "not_stated":
        trace.details["service"] = Detail("all", c.service.confidence, defaulted=True)
        trace.assumptions.append("all services, since none was named")
    service = trace.details["service"].value

    place = all_places()[c.place.value] if c.place.value != "no_place" else None
    if place is not None:
        if c.place_role.value == "dropoff":
            yield from decline("dropoff_not_supported_yet")
            return
        if c.place_role.value == "not_stated":
            trace.assumptions.append(f"trips that start in {place.label}")
        if place.kind == "group":
            trace.assumptions.append(f"{place.label} means all {len(place.zone_ids)} of its zones")

    period, date_assumptions = resolve_period(c.year.value, c.month.value, now.date())
    trace.period = period
    trace.assumptions += date_assumptions
    day = None if c.day.value == "not_stated" else c.day.value
    time_of_day = None if c.time_of_day.value == "not_stated" else c.time_of_day.value

    n = None
    if intent == "ranking":
        n = rank_size(question)
        if n is None:
            n = DEFAULT_RANK_N
            trace.assumptions.append(f"the top {n}, since no number was given")
        if c.measure.value != "trip_count":
            trace.assumptions.append("only places with at least 100 trips, so a handful of trips can't top an average")
    yield {"stage": "resolved", "period": period.label, "service": service, "place": place.label if place else None, "day": day, "time_of_day": time_of_day, "assumptions": trace.assumptions}

    if not covered(period):
        yield from decline("outside_data", period=period.label)
        return

    measure = c.measure.value
    filters = Filters(period, service, place.zone_ids if place else None, day, time_of_day)
    if intent == "ranking":
        q = db.ranking(measure, filters, unit_of_rank=c.rank_unit.value, direction=c.direction.value, n=n)
    else:
        q = db.total_or_average(measure, filters)
    trace.query, trace.source, trace.rows_scanned, trace.result = q.sql, q.source, q.rows_scanned, q.values
    trace.timings_ms["query"] = round(q.ms, 1)
    yield {"stage": "queried", "sql": q.sql, "params": q.params, "source": q.source, "rows_scanned": q.rows_scanned, "result": q.values}

    scope = scope_words(service, place.label if place else None, day, time_of_day, period.label)
    if q.values.get("value", 0) is None or q.values.get("rows") == []:
        trace.reply, trace.reply_source = f"There are no trips for {scope} in the data.", "template"
        yield {"stage": "written", "reply": trace.reply, "source": "template"}
        yield {"stage": "done", "trace": trace.to_dict()}
        return
    template = template_reply(measure, scope, q.values, trace.assumptions)

    if writer is None:
        # No language model configured: the template is the reply.
        trace.reply, trace.reply_source = template, "template"
        yield {"stage": "written", "reply": trace.reply, "source": "template"}
        yield {"stage": "done", "trace": trace.to_dict()}
        return

    allowed: list[float] = [period.start.year, period.end.year - 1, DATA_START.year, DATA_END.year - 1, now.year]
    allowed += TIME_NUMBERS.get(time_of_day, [])
    if intent == "ranking":
        allowed += [n, q.values["min_trips"]]
        for row in q.values["rows"]:
            allowed += [row["rank"], row["value"], row["trips"]]
    else:
        allowed += [q.values["value"], q.values["trips"]]
    details_words = {"measure": MEASURE_WORDS[measure], "scope": scope}
    if intent == "ranking":
        details_words["ranking"] = f"{'top' if c.direction.value == 'highest' else 'bottom'} {n} {c.rank_unit.value} by pickups"
    facts = facts_for(q.values)
    feedback = None
    for source in ("llm", "llm_retry"):
        started = time.perf_counter()
        reply = writer.write(question=question, details=details_words, facts=facts, assumptions=trace.assumptions, today=now.date().isoformat(), feedback=feedback)
        trace.timings_ms[f"write_{source}"] = _ms(started)
        check = check_numbers(reply, allowed)
        trace.checks.append(Check(f"{check.name}:{source}", check.passed, check.detail))
        yield {"stage": "checked", "attempt": source, "reply": reply, "passed": check.passed, "detail": check.detail}
        if check.passed:
            trace.reply, trace.reply_source = reply, source
            break
        feedback = check.detail
    else:
        trace.reply, trace.reply_source = template, "template"

    trace.models["writer"] = getattr(writer, "model", "unknown")
    yield {"stage": "written", "reply": trace.reply, "source": trace.reply_source}
    yield {"stage": "done", "trace": trace.to_dict()}


def run(question: str, now: datetime, **deps) -> dict:
    """Run the pipeline to completion and return the final trace."""
    for event in answer(question, now, **deps):
        if event["stage"] == "done":
            return event["trace"]
    raise AssertionError("pipeline ended without a done event")
