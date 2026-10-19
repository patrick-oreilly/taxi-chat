"""The single entry point: a question and the current date in, an answer trace out.

    for event in answer(question, now, classifier=..., writer=..., db=...): ...
    trace = run(question, now, classifier=..., writer=..., db=...)

`answer` yields one event per stage as it completes (the web page streams
these) and finishes with a "done" event carrying the full trace. The eval and
the tests call the same function, so they exercise exactly what the page does.

So far only total/average questions are answered; the other intents decline
as not supported until their own tickets land.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Iterator

from .checker import check_numbers
from .classify import Classification
from .dates import DATA_END, DATA_LABEL, DATA_START, covered, resolve_period
from .queries import Database
from .trace import AnswerTrace, Check, Detail
from .writer import SERVICE_WORDS, facts_for, template_reply

# Starting points; the eval tunes these on the tuning split.
THRESHOLDS = {"intent": 0.6, "detail": 0.5, "injection": 0.5}

SUPPORTED_INTENTS = {"total_or_average"}

DECLINE_MESSAGES = {
    "injection": "That reads like instructions rather than a question about the trip data, so I won't act on it.",
    "out_of_scope": "That isn't something the NYC trip records can answer.",
    "uncertain_intent": "I'm not confident what you're asking. Try rephrasing it as a question about trips, fares, tips, distance or duration.",
    "not_supported_yet": "I can answer totals and averages so far; trends, comparisons, rankings and distributions are coming.",
    "uncertain_detail": "I'm not confident about part of your question ({detail}). Try stating it more directly.",
    "outside_data": f"I don't have data for {{period}}; the data covers {DATA_LABEL}.",
}


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def answer(question: str, now: datetime, *, classifier, writer, db: Database) -> Iterator[dict]:
    trace = AnswerTrace(question=question, now=now.isoformat())

    def decline(reason: str, **fmt) -> Iterator[dict]:
        trace.declined = reason
        trace.decline_message = DECLINE_MESSAGES[reason].format(**fmt)
        yield {"stage": "declined", "reason": reason, "message": trace.decline_message}
        yield {"stage": "done", "trace": trace.to_dict()}

    started = time.perf_counter()
    c: Classification = classifier.classify(question)
    trace.timings_ms["classify"] = _ms(started)
    trace.models["classifier"] = c.model
    trace.intent = c.intent
    trace.details = {"measure": c.measure, "service": c.service, "year": c.year, "month": c.month}
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
    for name, detail in trace.details.items():
        if detail.confidence < THRESHOLDS["detail"]:
            yield from decline("uncertain_detail", detail=name)
            return

    if c.service.value == "not_stated":
        trace.details["service"] = Detail("all", c.service.confidence, defaulted=True)
        trace.assumptions.append("all services, since none was named")
    service = trace.details["service"].value
    period, date_assumptions = resolve_period(c.year.value, c.month.value, now.date())
    trace.period = period
    trace.assumptions += date_assumptions
    yield {"stage": "resolved", "period": period.label, "service": service, "assumptions": trace.assumptions}

    if not covered(period):
        yield from decline("outside_data", period=period.label)
        return

    measure = c.measure.value
    q = db.total_or_average(measure, service, period)
    trace.query, trace.source, trace.rows_scanned, trace.result = q.sql, q.source, q.rows_scanned, q.values
    trace.timings_ms["query"] = round(q.ms, 1)
    yield {"stage": "queried", "sql": q.sql, "params": q.params, "source": q.source, "rows_scanned": q.rows_scanned, "result": q.values}

    template = template_reply(measure, service, period.label, q.values, trace.assumptions)
    if q.values["value"] is None:
        trace.reply, trace.reply_source = f"There are no {SERVICE_WORDS[service]} trips in {period.label} in the data.", "template"
        yield {"stage": "written", "reply": trace.reply, "source": "template"}
        yield {"stage": "done", "trace": trace.to_dict()}
        return

    if writer is None:
        # No language model configured: the template is the reply.
        trace.reply, trace.reply_source = template, "template"
        yield {"stage": "written", "reply": trace.reply, "source": "template"}
        yield {"stage": "done", "trace": trace.to_dict()}
        return

    allowed = [q.values["value"], q.values["trips"], period.start.year, period.end.year - 1, DATA_START.year, DATA_END.year - 1, now.year]
    details_words = {"measure": measure, "service": SERVICE_WORDS[service], "period": period.label}
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
