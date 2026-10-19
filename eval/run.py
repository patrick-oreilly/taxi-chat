"""The benchmark.

    uv run --env-file .env python -m eval.run collect   # live Jev on the tuning split, cached
    uv run python -m eval.run tune                       # sweep thresholds over the cache, offline
    uv run --env-file .env python -m eval.run report     # tuning split end to end with DeepSeek, chosen thresholds
    uv run --env-file .env python -m eval.run order      # option-order check on the tuning split
    uv run --env-file .env python -m eval.run final      # the held-out split, once, frozen thresholds

`tune` and `report` only ever see the tuning split. `final` refuses to run
without the thresholds `tune` chose, and records that it ran, so the held-out
result can't be quietly retried after a change.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import statistics
import subprocess
import time
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

from taxichat import pipeline
from taxichat.classify import JEV_URL, JevClassifier
from taxichat.queries import Database
from taxichat.transport import HttpTransport, RecordingTransport, ReplayTransport
from taxichat.writer import DEEPSEEK_URL, DeepSeekWriter

from .holdout import HOLDOUT_SEEDS
from .questions import load
from .score import extraction, outcome
from .seeds import REFERENCE_DATE, SEEDS

EVAL = Path(__file__).parent
ROOT = EVAL.parent
CACHE = EVAL / "cache"
RESULTS = EVAL / "results"
THRESHOLDS_FILE = EVAL / "thresholds.json"
NOW = datetime.combine(REFERENCE_DATE, datetime.min.time())

TARGET_PRECISION = 0.97
# Published prices: Jev bills input tokens only; DeepSeek Flash at peak rates (off-peak is half).
JEV_PER_TOKEN = 0.042 / 1e6
DEEPSEEK_INPUT_PER_TOKEN = 0.30 / 1e6
DEEPSEEK_OUTPUT_PER_TOKEN = 1.20 / 1e6

GRID = {
    "intent": [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9],
    "detail": [0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
    "refuse": [0.3, 0.4, 0.5, 0.6, 0.7],  # shared by the injection, compound and unanswerable checks
}


class Meter:
    """Wraps a transport and adds up the tokens each call reports."""

    def __init__(self, inner):
        self.inner = inner
        self.input = self.output = 0

    def __call__(self, body: dict) -> dict:
        response = self.inner(body)
        usage = response.get("usage", {})
        self.input += usage.get("input_tokens", usage.get("prompt_tokens", 0))
        self.output += usage.get("output_tokens", usage.get("completion_tokens", 0))
        return response


class CachedDatabase(Database):
    """Thresholds never change which SQL runs, only whether the pipeline gets that
    far, so a sweep can reuse every query's rows."""

    def __init__(self, data_dir: Path):
        super().__init__(data_dir)
        self.memo: dict = {}

    def _run(self, sql, params):
        key = (sql, json.dumps(params, default=str))
        if key not in self.memo:
            self.memo[key] = super()._run(sql, params)
        return self.memo[key]


def _seeds() -> dict:
    return {s["id"]: s for s in SEEDS + HOLDOUT_SEEDS}


def _gold() -> dict:
    return json.loads((EVAL / "gold.json").read_text())


def _set_thresholds(t: dict) -> None:
    pipeline.THRESHOLDS.update(
        intent=t["intent"], detail=t["detail"], injection=t["refuse"], compound=t["refuse"], unanswerable=t["refuse"]
    )


def _score_all(questions, traces) -> list[dict]:
    seeds, gold = _seeds(), _gold()
    rows = []
    for q, trace in zip(questions, traces):
        seed = seeds[q["seed"]]
        result, why = outcome(seed, gold.get(seed["id"]), trace)
        routed = trace["intent"] is not None and seed.get("intent") == trace["intent"]["value"]
        extracted, wrong_details = extraction(seed, trace) if seed["expect"] == "answer" else (True, [])
        rows.append({**q, "outcome": result, "why": why, "routed": routed, "extracted": extracted, "wrong_details": wrong_details,
                     "declined": trace["declined"], "timings_ms": trace["timings_ms"], "reply_source": trace["reply_source"]})
    return rows


def _summary(rows: list[dict]) -> dict:
    count = lambda o: sum(r["outcome"] == o for r in rows)
    answered = count("correct") + count("wrong") + count("harmful")
    answerable = [r for r in rows if r["outcome"] in ("correct", "wrong", "missed")]
    return {
        "questions": len(rows),
        "answerable": len(answerable),
        "should_decline": len(rows) - len(answerable),
        "correct": count("correct"),
        "wrong": count("wrong"),
        "missed": count("missed"),
        "correct_decline": count("correct_decline"),
        "harmful": count("harmful"),
        "precision": count("correct") / answered if answered else None,
        "coverage": (count("correct") + count("wrong")) / len(answerable) if answerable else None,
        "routing_accuracy": sum(r["routed"] for r in answerable) / len(answerable) if answerable else None,
        "extraction_accuracy": sum(r["extracted"] for r in answerable) / len(answerable) if answerable else None,
    }


def _hardware() -> str:
    try:
        chip = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip()
        mem = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout) / 2**30
        return f"{chip}, {mem:.0f} GB, {platform.system()} {platform.release()}"
    except Exception:
        return platform.platform()


def _run_questions(questions, classifier, writer, db) -> list[dict]:
    traces = []
    for i, q in enumerate(questions, 1):
        traces.append(pipeline.run(q["question"], NOW, classifier=classifier, writer=writer, db=db))
        if i % 25 == 0:
            print(f"  {i}/{len(questions)}", flush=True)
    return traces


def collect(args) -> None:
    questions = [q for q in load() if q["split"] == "tuning"]
    CACHE.mkdir(exist_ok=True)
    classifier = JevClassifier(RecordingTransport(HttpTransport(JEV_URL, os.environ["TYPESAFE_API_KEY"]), CACHE / "jev-tuning.json"))
    _set_thresholds({"intent": 0, "detail": 0, "refuse": 1.01})
    _run_questions(questions, classifier, None, CachedDatabase(ROOT / "data"))
    print(f"cached Jev answers for {len(questions)} tuning questions")


def tune(args) -> None:
    questions = [q for q in load() if q["split"] == "tuning"]
    classifier = JevClassifier(ReplayTransport(CACHE / "jev-tuning.json"))
    db = CachedDatabase(ROOT / "data")
    table = []
    for intent, detail, refuse in product(GRID["intent"], GRID["detail"], GRID["refuse"]):
        t = {"intent": intent, "detail": detail, "refuse": refuse}
        _set_thresholds(t)
        s = _summary(_score_all(questions, _run_questions_quiet(questions, classifier, db)))
        table.append({**t, **s})
    meets = lambda r: r["harmful"] == 0 and r["precision"] is not None and r["precision"] >= TARGET_PRECISION
    by_point = {(r["intent"], r["detail"], r["refuse"]): r for r in table}
    feasible = [r for r in table if meets(r)]
    # A point that only just passes on 193 questions, next to settings that fail,
    # won't carry over to new questions. Only points whose every neighbour (one
    # grid step either way on each threshold) also meets the target are eligible.
    robust = [r for r in feasible if all(meets(by_point[n]) for n in _neighbours(r) if n in by_point)]
    if not robust:
        best = max(table, key=lambda r: (-(r["harmful"]), r["precision"] or 0))
        raise SystemExit(f"no thresholds robustly reach {TARGET_PRECISION:.0%} with zero harmful answers; closest: {best}")
    # Most questions answered correctly; then fewest wrong; then the more cautious thresholds.
    chosen = max(robust, key=lambda r: (r["correct"], -r["wrong"], r["intent"], r["detail"], -r["refuse"]))
    thresholds = {k: chosen[k] for k in ("intent", "detail", "refuse")}
    THRESHOLDS_FILE.write_text(json.dumps({"thresholds": thresholds, "tuning_summary": chosen, "chosen_at": datetime.now(timezone.utc).isoformat()}, indent=2))
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "tuning-sweep.json").write_text(json.dumps(table, indent=1))
    print(f"{len(feasible)} of {len(table)} combinations meet the target, {len(robust)} robustly; chose {thresholds}")
    print(json.dumps({k: chosen[k] for k in ("correct", "wrong", "missed", "correct_decline", "harmful", "precision", "coverage")}, indent=1))


def _neighbours(r: dict) -> list[tuple]:
    points = []
    for axis in ("intent", "detail", "refuse"):
        values = GRID[axis]
        i = values.index(r[axis])
        for j in (i - 1, i + 1):
            if 0 <= j < len(values):
                points.append(tuple(values[j] if a == axis else r[a] for a in ("intent", "detail", "refuse")))
    return points


def _run_questions_quiet(questions, classifier, db) -> list[dict]:
    return [pipeline.run(q["question"], NOW, classifier=classifier, writer=None, db=db) for q in questions]


def _live_run(split: str) -> dict:
    chosen = json.loads(THRESHOLDS_FILE.read_text())["thresholds"]
    _set_thresholds(chosen)
    questions = [q for q in load() if q["split"] == split]
    jev = Meter(HttpTransport(JEV_URL, os.environ["TYPESAFE_API_KEY"]))
    deepseek = Meter(HttpTransport(DEEPSEEK_URL, os.environ["DEEPSEEK_API_KEY"], timeout=60))
    started = time.perf_counter()
    traces = _run_questions(questions, JevClassifier(jev), DeepSeekWriter(deepseek), Database(ROOT / "data"))
    rows = _score_all(questions, traces)
    totals = [sum(r["timings_ms"].values()) for r in rows]
    n = len(rows)
    report = {
        "split": split,
        "thresholds": chosen,
        "summary": _summary(rows),
        "latency_ms": {"p50": statistics.median(totals), "p95": sorted(totals)[int(0.95 * (n - 1))]},
        "cost_per_question_usd": {
            "jev": jev.input * JEV_PER_TOKEN / n,
            "deepseek": (deepseek.input * DEEPSEEK_INPUT_PER_TOKEN + deepseek.output * DEEPSEEK_OUTPUT_PER_TOKEN) / n,
        },
        "tokens": {"jev_input": jev.input, "deepseek_input": deepseek.input, "deepseek_output": deepseek.output},
        "hardware": _hardware(),
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "wall_seconds": round(time.perf_counter() - started, 1),
        "rows": rows,
    }
    RESULTS.mkdir(exist_ok=True)
    return report


def _print(report: dict) -> None:
    s = report["summary"]
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=1))
    for r in report["rows"]:
        if r["outcome"] in ("wrong", "missed", "harmful") or (r["outcome"] == "correct_decline" and r["why"]):
            print(f"  {r['outcome']:<15} {r['id']:<12} {r['why'][:80]}  | {r['question'][:70]}")


def report(args) -> None:
    result = _live_run("tuning")
    (RESULTS / "tuning.json").write_text(json.dumps(result, indent=1, default=str))
    _print(result)


def final(args) -> None:
    marker = RESULTS / "holdout.json"
    if marker.exists() and not args.again:
        raise SystemExit("the held-out set has already been run; see eval/results/holdout.json (pass --again only to reproduce it, never after changing the system)")
    if not THRESHOLDS_FILE.exists():
        raise SystemExit("no tuned thresholds; run `tune` first")
    result = _live_run("holdout")
    marker.write_text(json.dumps(result, indent=1, default=str))
    _print(result)


def order(args) -> None:
    questions = [q for q in load() if q["split"] == "tuning"]
    plain = JevClassifier(ReplayTransport(CACHE / "jev-tuning.json"))
    shuffled = JevClassifier(HttpTransport(JEV_URL, os.environ["TYPESAFE_API_KEY"]), rng=random.Random(20261020))
    from taxichat.places import candidates

    changed, compared, examples = 0, 0, []
    for q in questions:
        places = candidates(q["question"])
        a, b = plain.classify(q["question"], places), shuffled.classify(q["question"], places)
        for name in ("intent", "measure", "service", "place", "place_role", "day", "time_of_day", "direction", "rank_unit",
                     "grain", "year", "month", "compare_by", "distribution_of"):
            x, y = getattr(a, name), getattr(b, name)
            if x.confidence >= 0.5 or y.confidence >= 0.5:  # only answers the gate could act on
                compared += 1
                if x.value != y.value:
                    changed += 1
                    examples.append(f"{name}: {x.value} ({x.confidence:.2f}) -> {y.value} ({y.confidence:.2f}) | {q['question'][:60]}")
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "option-order.json").write_text(json.dumps({"compared": compared, "changed": changed, "examples": examples}, indent=1))
    print(f"{changed} of {compared} confident Choice answers changed when the options were shuffled ({changed / compared:.1%})")
    for e in examples[:20]:
        print("  " + e)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["collect", "tune", "report", "order", "final"])
    parser.add_argument("--again", action="store_true", help="re-run the held-out set to reproduce it")
    args = parser.parse_args()
    {"collect": collect, "tune": tune, "report": report, "order": order, "final": final}[args.command](args)


if __name__ == "__main__":
    main()
