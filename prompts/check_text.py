"""Check that each prompt's text + subtitle agree with its filters. Prints disagreements."""
import json
import re
import sys
from pathlib import Path

TEAM = {"CLE": "Browns", "LV": "Raiders", "KC": "Chiefs", "NYJ": "Jets", "NE": "Patriots", "DAL": "Cowboys", "GB": "Packers",
        "PHI": "Eagles", "BUF": "Bills", "CHI": "Bears", "NYG": "Giants", "WAS": "Washington", "MIA": "Dolphins", "DEN": "Broncos",
        "DET": "Lions", "IND": "Colts", "ARI": "Cardinals", "LA": "Rams", "PIT": "Steelers", "MIN": "Vikings", "SEA": "Seahawks",
        "SF": "49ers", "LAC": "Chargers", "CIN": "Bengals", "TEN": "Titans", "ATL": "Falcons", "NO": "Saints", "CAR": "Panthers",
        "JAX": "Jaguars", "HOU": "Texans", "TB": "Buccaneers", "BAL": "Ravens"}
POS_WORD = {"QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE", "LB": "LB", "DB": "DB", "K": "kicker"}
STAT_WORD = {"receiving_yards": "receiving yard", "rushing_yards": "rushing yard", "passing_yards": "passing yard",
             "sacks": "sack", "interceptions": "interception", "receptions": "reception", "rushing_tds": "rushing TD",
             "receiving_tds": "receiving TD", "passing_tds": "passing TD"}
AWARD_WORD = {"mvp": "MVP", "dpoy": "Defensive Player of the Year", "opoy": "Offensive Player of the Year",
              "oroy": "Offensive Rookie of the Year", "droy": "Defensive Rookie of the Year", "comeback": "Comeback Player"}


def problems(p: dict) -> list[str]:
    f, text, sub = p["filters"], p["text"], p.get("subtitle", "")
    out = []
    teams = f.get("teams_all") or ([f["team"]] if "team" in f else [])
    for t in teams:
        if TEAM[t] not in text:
            out.append(f"filter team {t} ({TEAM[t]}) not in text")
    for code, name in TEAM.items():
        if re.search(rf"\b{re.escape(name)}\b", text) and code not in teams:
            out.append(f"text names {name} but filters don't")
    pos = f.get("position")
    if isinstance(pos, list):
        if sorted(pos) == ["RB", "TE", "WR"] and "skill player (RB/WR/TE)" not in text:
            out.append("filter is RB/WR/TE but text doesn't say 'skill player (RB/WR/TE)'")
    elif pos:
        if not re.search(rf"\b{POS_WORD[pos]}\b", text):
            out.append(f"filter position {pos} not in text")
    elif "teams_all" in f and not re.search(r"\ba player\b", text):
        out.append("no position filter but text names a position")
    for w in ("QB", "RB", "WR", "TE", "LB", "DB", "kicker", "skill player"):
        if re.search(rf"\b{re.escape(w)}\b", text) and w not in str(pos) and not (w == "kicker" and pos == "K") \
                and not (w == "skill player" and isinstance(pos, list)):
            out.append(f"text says {w} but filter position is {pos}")
    lo, hi = f.get("season_min"), f.get("season_max")
    if m := re.search(r"(\d{4})s\b", text):
        d = int(m.group(1))
        if (lo, hi) != (d, d + 9):
            out.append(f"text says {d}s but seasons are {lo}–{hi}")
    if m := re.search(r"(\d{4})–(\d{4}) (?:seasons|regular season)", sub):
        a, b = int(m.group(1)), int(m.group(2))
        if lo != a:
            out.append(f"subtitle starts {a} but season_min is {lo}")
        if b != 2026 and hi != b:
            out.append(f"subtitle ends {b} but season_max is {hi}")
    if "All seasons" in sub and (lo or hi):
        out.append(f"subtitle says all seasons but filters set {lo}–{hi}")
    for k in ("conference", "division"):
        if k in f and f[k] not in text:
            out.append(f"filter {k} {f[k]} not in text")
    for c in ("AFC", "NFC"):
        if re.search(rf"\b{c}\b", text) and c not in f.get("conference", "") + f.get("division", ""):
            out.append(f"text says {c} but filters don't")
    if st := f.get("stat_threshold"):
        n = f"{st['min']:,}+"
        if n not in text:
            out.append(f"stat min {n} not in text")
        if STAT_WORD[st["stat"]] not in text:
            out.append(f"stat {st['stat']} not described in text")
    for a in (f["award"] if isinstance(f.get("award"), list) else [f["award"]] if "award" in f else []):
        if AWARD_WORD[a] not in text:
            out.append(f"award {a} not in text")
    return out


def filter_key(f: dict) -> str:
    """Canonical filters: team order and list order don't matter."""
    g = {k: (sorted(v) if isinstance(v, list) else v) for k, v in f.items()}
    return json.dumps(g, sort_keys=True)


# intentional repeats (e.g. the award slot rotates through the same six awards)
ALLOWED_REPEAT_TYPES = {"trait"}

path = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / "prompts_14_days.jsonl")
bad = 0
seen: dict[str, str] = {}
for line in path.read_text().splitlines():
    if not line.strip() or line.startswith("#"):
        continue
    p = json.loads(line)
    for msg in problems(p):
        bad += 1
        print(f"{p['id']}: {p['text']!r} -> {msg}")
    k = filter_key(p["filters"])
    if k in seen and p.get("type") not in ALLOWED_REPEAT_TYPES:
        bad += 1
        print(f"{p['id']}: {p['text']!r} -> same filters as {seen[k]}")
    seen.setdefault(k, p["id"])
print(f"{bad} problem(s)")
