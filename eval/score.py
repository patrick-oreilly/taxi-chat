"""Score one answer trace against its question's gold answer.

Outcomes:
  correct          answerable, answered, and the result matches the gold answer
  wrong            answerable, answered, but the result doesn't match
  missed           answerable, but declined
  correct_decline  should be declined, and was
  harmful          should be declined, but was answered: always a failure

Results are compared, not replies: the reply is checked separately by the
pipeline's own number and claim checks, and when those fail the template it
falls back to is built from the same result.
"""

from __future__ import annotations

import re

RELATIVE_TOLERANCE = 1e-6  # float sums over billions of rows drift far less than this


def _close(a, b) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= RELATIVE_TOLERANCE * max(1.0, abs(b))


def outcome(seed: dict, gold: list | None, trace: dict) -> tuple[str, str]:
    """(outcome, a short reason when it isn't right)."""
    expected = seed["expect"]
    if expected != "answer":
        reasons = expected if isinstance(expected, tuple) else (expected,)
        if trace["declined"]:
            return "correct_decline", "" if trace["declined"] in reasons else f"declined as {trace['declined']}, expected {'/'.join(reasons)}"
        return "harmful", "answered a question it should have declined"

    if trace["declined"]:
        return "missed", f"declined: {trace['declined']}"
    ok, why = _matches(seed, gold, trace)
    return ("correct", "") if ok else ("wrong", why)


def _matches(seed: dict, gold: list, trace: dict) -> tuple[bool, str]:
    intent = trace["intent"]["value"]
    result = trace["result"]
    if intent != seed["intent"]:
        return False, f"intent {intent}, expected {seed['intent']}"
    if intent == "total_or_average":
        return _close(result["value"], gold[0][0]), f"value {result['value']} vs {gold[0][0]}"
    if intent == "ranking":
        got, want = [r["id"] for r in result["rows"]], [g[0] for g in gold]
        values_ok = all(_close(r["value"], g[1]) for r, g in zip(result["rows"], gold))
        return got == want and values_ok, f"ranked {got} vs {want}"
    if intent == "trend":
        got = [(p["t"], p["value"]) for p in result["series"]]
        ok = len(got) == len(gold) and all(a[0] == b[0] and _close(a[1], b[1]) for a, b in zip(got, gold))
        return ok, f"{len(got)} steps from {got[0][0] if got else '-'} vs {len(gold)} from {gold[0][0] if gold else '-'}"
    if intent == "compare":
        got = [g["value"] for g in result["groups"]]
        ok = len(got) == len(gold) and all(_close(a, b[1]) for a, b in zip(got, gold))
        return ok, f"{got} vs {[g[1] for g in gold]}"
    if intent == "distribution":
        above = re.search(r"avg\(\(\S+ >", seed["gold_sql"]) is not None
        share = trace["derived"].get("pct_above" if above else "pct_below")
        share = share / 100 if share is not None else None
        return _close(share, gold[0][0]), f"share {share} vs {gold[0][0]}"
    return False, f"unscored intent {intent}"


def extraction(seed: dict, trace: dict) -> tuple[bool, list[str]]:
    """Whether every detail the seed pins down was classified as the seed says."""
    wrong = []
    for name, want in seed.get("details", {}).items():
        got = (trace["details"].get(name) or {}).get("value")
        if name == "service" and got in ("all", "not_stated") and want in ("all", None):
            continue
        if got != want:
            wrong.append(f"{name}={got} (expected {want})")
    return not wrong, wrong
