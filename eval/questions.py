"""The benchmark's questions: every seed plus its kept rewordings, with its split.

The reviewed eval/paraphrases.md is the source of truth for rewordings: `[x]`
lines are kept (edited text included), `[ ]` lines are dropped. A rewording
always takes its seed's split, so no held-out question rewords a tuning one.
"""

from __future__ import annotations

import re
from pathlib import Path

from .holdout import HOLDOUT_SEEDS
from .seeds import SEEDS

PARAPHRASES = Path(__file__).parent / "paraphrases.md"


def load() -> list[dict]:
    seeds = {s["id"]: (s, "tuning") for s in SEEDS} | {s["id"]: (s, "holdout") for s in HOLDOUT_SEEDS}
    rewordings: dict[str, list[str]] = {}
    current = None
    for line in PARAPHRASES.read_text().splitlines():
        if match := re.match(r"### (\S+) ", line):
            current = match.group(1)
        elif line.startswith("- [x] ") and current:
            rewordings.setdefault(current, []).append(line[6:].split("  — ")[0].strip())

    questions = []
    for seed_id, (seed, split) in seeds.items():
        for i, text in enumerate([seed["question"], *rewordings.get(seed_id, [])]):
            questions.append({"id": f"{seed_id}.{i}", "seed": seed_id, "question": text, "split": split})
    return questions


if __name__ == "__main__":
    qs = load()
    for split in ("tuning", "holdout"):
        print(split, sum(q["split"] == split for q in qs))
