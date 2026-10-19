"""The answer trace: everything the pipeline decided and did for one question.

The web page renders it, the eval scores it, and tests assert on it, so its
shape is the contract every later stage extends.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date


@dataclass
class Detail:
    """One classified detail: the option chosen, how confident Jev was, and
    whether the value is a stated default rather than something in the question."""

    value: str | None
    confidence: float | None = None
    defaulted: bool = False


@dataclass
class Period:
    start: date  # inclusive
    end: date  # exclusive
    label: str  # how the reply should describe it, e.g. "March 2020"


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class AnswerTrace:
    question: str
    now: str
    intent: Detail | None = None
    details: dict[str, Detail] = field(default_factory=dict)
    period: Period | None = None
    assumptions: list[str] = field(default_factory=list)
    declined: str | None = None  # reason code; None when answered
    decline_message: str | None = None
    decline_source: str | None = None  # "fixed", "llm", "llm_retry" or "template"
    nearest_period: Period | None = None  # for periods outside the data: the closest one it covers
    query: str | None = None
    source: str | None = None  # "rollup" or "raw"
    rows_scanned: int | None = None
    result: dict | None = None
    reply: str | None = None
    reply_source: str | None = None  # "llm", "llm_retry" or "template"
    checks: list[Check] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)
    models: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
