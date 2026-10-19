"""Generate rewordings of every seed, and flag any that may have changed its meaning.

    uv run --env-file .env python -m eval.paraphrase

Writes eval/paraphrases.md for review: one line per rewording, ticked to keep.
Untick to drop, or edit the text in place. Lines marked CHECK were judged by a
second model as possibly not meaning the same as their seed.

Rewordings come from DeepSeek, and the meaning check from DeepSeek in thinking
mode. Neither is the system under test: using Jev here would let the system
choose its own test questions.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from taxichat.transport import HttpTransport
from taxichat.writer import DEEPSEEK_URL

from .holdout import HOLDOUT_SEEDS
from .seeds import REFERENCE_DATE, SEEDS

OUT = Path(__file__).parent / "paraphrases.md"

# 50 held-out questions: 12 seeds + 3 rewordings each + 2 spare; 200 tuning: 60 seeds + 140.
HOLDOUT_EXTRA = {"hold-01", "hold-05"}
TUNING_THREE = 20  # the first 20 tuning seeds get 3 rewordings, the rest 2

REWORD = f"""You write test questions for a chatbot about NYC taxi and rideshare trip data (Jan 2019 to Dec 2025).
Today is {REFERENCE_DATE:%d %B %Y}.

Reword the QUESTION {{n}} different ways, the way different real people might type it. Vary the style: casual,
terse, typos or missing punctuation, slang ("cabs", "rides", "ubers"), neighbourhood nicknames (Billyburg,
Hell's Kitchen, FiDi, UES, UWS, LES), or a relative date that means exactly the same period given today's date
("last year" for 2025 only; never relative for other years).

Each rewording must ask EXACTLY the same thing: the same period, place, pickup or drop-off, service or company,
measure, time of day, number of results and comparison order. Don't add, drop or soften anything. If the question
is something the bot should refuse, the rewording must be refusable for the same reason.

Reply as JSON: {{{{"rewordings": ["...", "..."]}}}}"""

JUDGE = """Do these two questions about NYC taxi trip data ask for exactly the same answer: the same period, place,
pickup or drop-off, service, measure, time of day, number of results and comparison order? Today is {today}.
For questions that should be refused, do they deserve refusing for the same reason?

A: {a}
B: {b}

Reply as JSON: {{"same": true or false, "why": "one short sentence"}}"""


def _chat(transport, prompt: str, *, thinking: bool) -> dict:
    response = transport(
        {
            "model": "deepseek-flash",
            "messages": [{"role": "user", "content": prompt}],
            "thinking": {"type": "enabled" if thinking else "disabled"},
            "response_format": {"type": "json_object"},
            "max_tokens": 2000,
        }
    )
    return json.loads(response["choices"][0]["message"]["content"])


def main() -> None:
    transport = HttpTransport(DEEPSEEK_URL, os.environ["DEEPSEEK_API_KEY"], timeout=120)
    jobs = []
    for i, seed in enumerate(SEEDS):
        jobs.append((seed, "tuning", 3 if i < TUNING_THREE else 2))
    for seed in HOLDOUT_SEEDS:
        jobs.append((seed, "holdout", 4 if seed["id"] in HOLDOUT_EXTRA else 3))

    def reword(job):
        seed, split, n = job
        rewordings = _chat(transport, REWORD.format(n=n) + f"\n\nQUESTION: {seed['question']}", thinking=False)["rewordings"][:n]
        checked = []
        for text in rewordings:
            verdict = _chat(transport, JUDGE.format(today=f"{REFERENCE_DATE:%d %B %Y}", a=seed["question"], b=text), thinking=True)
            checked.append((text, verdict.get("same", False), verdict.get("why", "")))
        return seed, split, checked

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(reword, jobs))

    lines = [
        "# Paraphrases for review",
        "",
        "Keep a rewording by leaving `[x]`; drop it with `[ ]`; edit the text in place if it's close but off.",
        "`CHECK` marks ones a second model thought may not mean the same as the seed.",
        "",
    ]
    for split in ("holdout", "tuning"):
        lines += [f"## {split.title()}", ""]
        for seed, s, checked in results:
            if s != split:
                continue
            expect = seed["expect"] if isinstance(seed["expect"], str) else " / ".join(seed["expect"])
            lines.append(f"### {seed['id']} ({expect}): {seed['question']}")
            for text, same, why in checked:
                flag = "" if same else f"  — CHECK: {why}"
                lines.append(f"- [x] {text}{flag}")
            lines.append("")
    OUT.write_text("\n".join(lines))
    flagged = sum(not same for _, _, checked in results for _, same, _ in checked)
    total = sum(len(checked) for _, _, checked in results)
    print(f"{total} rewordings, {flagged} flagged for a closer look -> {OUT}")


if __name__ == "__main__":
    main()
