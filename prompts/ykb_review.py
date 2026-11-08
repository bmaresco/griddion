"""One line per prompt: the YKB Kid pick (default or override) and its context line.

    uv run python prompts/ykb_review.py > prompts/ykb_review.md
Override by adding "ykb_kid": "<player_id>" to the prompt in build_14_days.py's output.
"""
import json

from football_trivia.db import ROOT
from football_trivia.publish import load_prompts, load_schedule, export_prompt
from football_trivia.db import connect
from football_trivia.scoring import fame

con = connect(read_only=True)
sched = load_schedule()
prompts = load_prompts(ROOT / sched["queue"])
f = fame(con)
print("# YKB Kid review\n")
print("Default (§2): highest-fame Sleeper Pick, else highest-fame Hidden Gem. Override with `\"ykb_kid\": \"<player_id>\"`.\n")
print("| Drive | Date | # | Prompt | YKB Kid | Context | Source | Player id |")
print("|---|---|---|---|---|---|---|---|")
for d in sched["drives"]:
    for slot, pid in enumerate(d["prompt_ids"], 1):
        e, _ = export_prompt(con, prompts[pid], slot, f)
        k = next((a for a in e["answers"] if a["id"] == e["ykb_kid"]), None)
        print(f"| {d['drive']} | {d['date']} | {slot} | {e['text']} | {k['name'] if k else '—'} | "
              f"{k['context'] if k else ''} | {e['ykb_source'] or '—'} | {e['ykb_kid'] or ''} |")
