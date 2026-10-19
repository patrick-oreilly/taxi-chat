"""Numbers a reply may cite that aren't in the query result directly.

Percentage changes, ratios and shares are computed here, in code, and handed
to the writer as facts, so "up 18%" or "nearly double" is only ever said when
code worked it out. `ratios` feeds the size-word check.
"""

from __future__ import annotations


def _pct(new: float, old: float) -> float | None:
    return (new - old) / old * 100 if old else None


def _ratio(a: float, b: float) -> float | None:
    return a / b if b else None


def derive(intent: str, result: dict) -> tuple[dict, list[float]]:
    """(derived values, ratios a size word may be checked against)."""
    if intent == "trend":
        points = [p for p in result["series"] if p["value"] is not None]
        # Partial steps at the edges would distort the change, peak and low; leave
        # them out unless nothing else is left.
        complete = [p for p in points if p.get("complete", True)] or points
        if not complete:
            return {}, []
        first, last = complete[0], complete[-1]
        peak = max(complete, key=lambda p: p["value"])
        low = min(complete, key=lambda p: p["value"])
        ratio = _ratio(last["value"], first["value"])
        derived = {"first": first, "last": last, "peak": peak, "low": low, "pct_change": _pct(last["value"], first["value"]), "ratio": ratio,
                   "partial_left_out": len(points) - len(complete)}
        return derived, [r for r in (ratio,) if r]

    if intent == "compare":
        a, b = result["groups"]
        va, vb = a["value"] or 0, b["value"] or 0
        ratio, inverse = _ratio(va, vb), _ratio(vb, va)
        return {"difference": va - vb, "ratio": ratio, "pct_difference": _pct(va, vb)}, [r for r in (ratio, inverse) if r]

    if intent == "distribution":
        derived = {"bucket_pcts": [b["share"] * 100 if b["share"] is not None else None for b in result["buckets"]]}
        if result.get("share_below") is not None:
            derived["pct_below"] = result["share_below"] * 100
            derived["pct_above"] = result["share_above"] * 100
        return derived, []

    return {}, []
