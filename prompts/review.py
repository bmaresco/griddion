"""Write a review sheet for a prompt file: counts, tier spread, §6 warnings, Botched Trick Play suggestion.

    uv run python prompts/review.py prompts/prompts_14_days.jsonl > prompts/review_14_days.md
"""
import json
import sys

from football_trivia.answers import MIN_ANSWERS, TIGHT_MARGIN, Prompt, build_answers
from football_trivia.db import connect
from football_trivia.scoring import TIERS, fame, score_answers, spread_warnings, suggest_botched

con = connect(read_only=True)
f = fame(con)
rows = []
for line in open(sys.argv[1]):
    if not line.strip() or line.startswith("#"):
        continue
    obj = json.loads(line)
    p = Prompt.from_json(obj)
    r = build_answers(con, p)
    s, _ = score_answers(con, r, f)
    c = {t: int((s["tier"] == t).sum()) for t in TIERS}
    b = suggest_botched(s)
    flags = spread_warnings(s) + (["tight"] if r.n <= MIN_ANSWERS + TIGHT_MARGIN else [])
    rows.append((obj.get("day"), obj.get("slot"), p.id, p.text, r.n, c, flags, b))

print("# 14-day review: tiers, warnings, Botched Trick Play suggestions\n")
print("Frozen thresholds (data/tier_thresholds.json). Spread = Starter · Backup · Hidden Gem · Sleeper Pick.")
print("Botched Trick Play suggestion = most famous answer with F ≥ 0.58 and A ≤ 0.35 (§2). Approve or reject each.\n")
print("| Day | # | Prompt | n | Spread | Warnings | Botched Trick Play suggestion |")
print("|---|---|---|---:|---|---|---|")
for day, slot, pid, text, n, c, flags, b in rows:
    spread = " · ".join(str(c[t]) for t in TIERS)
    sug = f"{b['display_name']} (F {b['F']:.2f}, A {b['A']:.2f})" if b else "—"
    print(f"| {day} | {slot} | {text} | {n} | {spread} | {'; '.join(flags) or '—'} | {sug} |")
