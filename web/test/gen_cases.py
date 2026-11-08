"""Generate matcher parity cases from the Python reference on published data."""
import json, random, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from football_trivia.matching import Matcher, first_name_variants
from football_trivia.names import norm_name

pub = Path(__file__).resolve().parents[2] / "public"
m = json.loads((pub / "matching.json").read_text())
others = {}
for name, ids in m["all_player_names"].items():
    n = norm_name(name)
    if n and " " in n:
        for v in first_name_variants(n):
            others.setdefault(v, set()).update(ids)
all_names = list(m["all_player_names"])
rng = random.Random(7)

def typo(s):
    i = rng.randrange(len(s))
    op = rng.choice("dsit")
    c = rng.choice("abcdefghijklmnopqrstuvwxyz")
    if op == "d": return s[:i] + s[i+1:]
    if op == "s": return s[:i] + c + s[i+1:]
    if op == "i": return s[:i] + c + s[i:]
    return s[:i] + s[i+1:i+2] + s[i:i+1] + s[i+2:] if i < len(s) - 1 else s

cases = []
for drive in (1, 2, 3, 6):
    day = json.loads((pub / "days" / f"{drive}.json").read_text())
    for p in day["prompts"]:
        bank = {a["id"]: list(a["names"]) + list(a["last_names"]) for a in p["answers"]}
        mt = Matcher(bank, others)
        typed = []
        for a in rng.sample(p["answers"], min(15, len(p["answers"]))):
            typed += [a["name"], a["last_names"][0] if a["last_names"] else a["name"], typo(a["name"]), a["name"].upper()]
        typed += rng.sample(all_names, 10) + [typo(n) for n in rng.sample(all_names, 5)] + ["", "zzzz", "Smith", "Mike Smith", "Y. A. Tittle", "Joe Montana"]
        for t in typed:
            r = mt.match(t)
            cases.append({"drive": drive, "slot": p["slot"], "typed": t, "status": r.status, "id": r.player_id, "method": r.method, "candidates": r.candidates})
json.dump(cases, open(Path(__file__).with_name("cases.json"), "w"))
print(len(cases), "cases")
