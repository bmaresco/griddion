"""Generate prompts_14_days.jsonl (filter JSON for probe); prompts_14_days.md is written from it.

Slot plan of 2026-11-11 (end of file): Drives 3-14 get P3 college, P4 new stat types, P7 honors.

Kept as code so the translation is reviewable: one tuple per prompt, in day/slot order.
Revisions approved after the first probe: two-team prompts are "skill player" (RB/WR/TE) where
that reaches 25 answers, otherwise any position; TE stat 1,000 -> 800 yds; QB rushing 500 -> 400 yds.
Launch-day changes (Drive #1): P4 Jets+Patriots any position; P6 WR 1,200+ receiving yds.
Duplicates replaced: 13.3 Patriots+Jets -> Bills+Patriots, 10.3 Rams+Cardinals -> Seahawks+Rams (any position; skill version had 21).
"""
import json
from pathlib import Path

ALL = "All seasons (franchise history)"
QB = "QBs must have started a regular-season game"
G = "Must have played in a regular-season game"
G99 = "Must have played in a regular-season game (on an active roster before 1999)"
BOTH = "Must have played a regular-season game for both"
ACT = "Must have been on an active regular-season roster"
STAT = "Single season, 1999–2026 regular season"

def team(t, pos, smin=None, sub=None):
    f = {"team": t, "position": pos}
    if smin: f["season_min"] = smin
    return ("team", f, sub)

def div(d, pos):
    return ("era", {"division": d, "position": pos, "season_min": 2002}, f"2002–2026 seasons · {QB if pos == 'QB' else G}")

def two(a, b, pos, smin=None):
    f = {"teams_all": [a, b]}
    if pos: f["position"] = pos  # ["RB", "WR", "TE"] = skill player; None = any position
    if smin: f["season_min"] = smin
    return ("two_team", f, f"{f'{smin}–2026 seasons' if smin else ALL} · {BOTH}")

def era(lo, hi, pos, conf=None, sub_extra=""):
    f = {"position": pos, "season_min": lo, "season_max": hi}
    if conf: f["conference"] = conf
    return ("era", f, f"{lo}–{hi} seasons{sub_extra} · {QB if pos == 'QB' else ACT}")

def stat(s, n, pos=None):
    f = {"stat_threshold": {"stat": s, "min": n}, "season_min": 1999}
    if pos: f["position"] = pos
    return ("trait", f, STAT)

def article(n):
    t = str(n)
    return "an" if t.startswith("8") or n in (11, 18) else "a"


# Stat thresholds for the Drive 3-13 replacements, stepped down where needed so each prompt
# has >= 3 Sleeper Picks besides the YKB Kid (user rule: up to 2 steps of the listed size).
STAT_OVERRIDES: dict[tuple[str, str], int] = {
    ("QB", "rushing_yards"): 200,  # D13: 300 -> 250 -> 200 (2 steps of 50)
}


def stat_p(pos, stat_name, n, label):
    n = STAT_OVERRIDES.get((pos, stat_name), n)
    return (f"Name a {pos} with {article(n)} {n:,}+ {label} season", stat(stat_name, n, pos))


def kicker_fg(n):
    n = STAT_OVERRIDES.get(("K", "field_goals"), n)
    return (f"Name a kicker with {article(n)} {n}+ field goal season", stat("field_goals", n, "K"))


def award(a, lo):
    return ("trait", {"award": a, "season_min": lo, "season_max": 2025}, f"{lo}–2025 seasons")

DAYS = [
 [("Name a Browns QB", team("CLE", "QB", sub=f"{ALL} · {QB}")),
  ("Name an NFC North WR", div("NFC North", "WR")),
  ("Name a player who played for the Raiders and the Chiefs", two("LV", "KC", None)),
  ("Name a player who played for the Jets and the Patriots", two("NYJ", "NE", None)),
  ("Name an AFC QB from the 1990s", era(1990, 1999, "QB", "AFC")),
  ("Name a WR with a 1,200+ receiving yard season", stat("receiving_yards", 1200, "WR")),
  ("Name an AP MVP", award("mvp", 1957))],
 [("Name a Cowboys RB", team("DAL", "RB", 2000, f"2000–2026 seasons · {G}")),
  ("Name a Packers WR", team("GB", "WR", sub=f"{ALL} · {G99}")),
  ("Name a player who played for the Cowboys and the Eagles", two("DAL", "PHI", None)),
  ("Name a skill player (RB/WR/TE) who played for the Bills and the Jets", two("BUF", "NYJ", ["RB", "WR", "TE"])),
  ("Name an NFC RB from the 1980s", era(1980, 1989, "RB", "NFC")),
  ("Name a player with a 10+ sack season", stat("sacks", 10)),
  ("Name an AP Defensive Player of the Year", award("dpoy", 1971))],
 [("Name a Jets QB", team("NYJ", "QB", sub=f"{ALL} · {QB}")),
  ("Name an AFC South RB", div("AFC South", "RB")),
  ("Name a skill player (RB/WR/TE) who played for the Bears and the Packers", two("CHI", "GB", ["RB", "WR", "TE"])),
  ("Name a skill player (RB/WR/TE) who played for the Giants and Washington", two("NYG", "WAS", ["RB", "WR", "TE"])),
  ("Name a QB from the 1970s", era(1970, 1979, "QB")),
  kicker_fg(30),
  ("Name an AP Offensive Rookie of the Year", award("oroy", 1967))],
 [("Name a Chiefs TE", team("KC", "TE", 2000, f"2000–2026 seasons · {G}")),
  ("Name an NFC East QB", div("NFC East", "QB")),
  ("Name a skill player (RB/WR/TE) who played for the Bills and the Dolphins", two("BUF", "MIA", ["RB", "WR", "TE"])),
  ("Name a player who played for the Broncos and the Raiders", two("DEN", "LV", None)),
  ("Name a kicker from the 1980s", era(1980, 1989, "K")),
  ("Name a RB with a 1,000+ rushing yard season", stat("rushing_yards", 1000, "RB")),
  ("Name an AP Offensive Player of the Year", award("opoy", 1972))],
 [("Name a Lions QB", team("DET", "QB", sub=f"{ALL} · {QB}")),
  ("Name a Colts WR", team("IND", "WR", sub=f"All seasons (Baltimore & Indianapolis) · {G99}")),
  ("Name a player who played for the Cardinals and the Rams", two("ARI", "LA", None)),
  ("Name a player who played for the Steelers and the Browns", two("PIT", "CLE", None)),
  ("Name an AFC WR from the 1990s", era(1990, 1999, "WR", "AFC")),
  ("Name a DB with a 5+ interception season", stat("interceptions", 5, "DB")),
  ("Name an AP Defensive Rookie of the Year", award("droy", 1967))],
 [("Name a Steelers LB", team("PIT", "LB", sub=f"{ALL} · {G99}")),
  ("Name an AFC West TE", div("AFC West", "TE")),
  ("Name a player who played for the Cowboys and the Giants", two("DAL", "NYG", None)),
  ("Name a player who played for the Vikings and the Packers", two("MIN", "GB", None)),
  ("Name a QB from the 1960s", era(1960, 1969, "QB", sub_extra=", NFL & AFL")),
  stat_p("TE", "receiving_yards", 700, "receiving yard"),
  ("Name an AP Comeback Player of the Year", award("comeback", 1998))],
 [("Name a Washington QB", team("WAS", "QB", sub=f"{ALL} · {QB}")),
  ("Name a Patriots RB", team("NE", "RB", 2000, f"2000–2026 seasons · {G}")),
  ("Name a player who played for the Seahawks and the 49ers", two("SEA", "SF", None)),
  ("Name a player who played for the Chargers and the Chiefs", two("LAC", "KC", None)),
  ("Name an AFC TE from the 1980s", era(1980, 1989, "TE", "AFC")),
  stat_p("RB", "rushing_tds", 10, "rushing TD"),
  ("Name an AP MVP", award("mvp", 1957))],
 [("Name a Bengals WR", team("CIN", "WR", 2000, f"2000–2026 seasons · {G}")),
  ("Name an NFC South QB", div("NFC South", "QB")),
  ("Name a player who played for the Broncos and the Chargers", two("DEN", "LAC", None)),
  ("Name a player who played for the Colts and the Titans", two("IND", "TEN", None)),
  ("Name a QB from the 1980s", era(1980, 1989, "QB")),
  stat_p("WR", "receptions", 85, "reception"),
  ("Name an AP Defensive Player of the Year", award("dpoy", 1971))],
 [("Name a Cardinals QB", team("ARI", "QB", sub=f"{ALL} · {QB}")),
  ("Name a Titans RB", team("TEN", "RB", 2000, f"2000–2026 seasons · {G}")),
  ("Name a player who played for the Falcons and the Saints", two("ATL", "NO", None)),
  ("Name a player who played for the Lions and the Vikings", two("DET", "MIN", None)),
  ("Name an AFC RB from the 1970s", era(1970, 1979, "RB", "AFC")),
  stat_p("TE", "receptions", 65, "reception"),
  ("Name an AP Offensive Rookie of the Year", award("oroy", 1967))],
 [("Name an Eagles TE", team("PHI", "TE", 2000, f"2000–2026 seasons · {G}")),
  ("Name an AFC North RB", div("AFC North", "RB")),
  ("Name a player who played for the Seahawks and the Rams", two("SEA", "LA", None)),
  ("Name a player who played for the Bengals and the Steelers", two("CIN", "PIT", None)),
  ("Name an NFC QB from the 1990s", era(1990, 1999, "QB", "NFC")),
  stat_p("TE", "receiving_tds", 7, "receiving TD"),
  ("Name an AP Offensive Player of the Year", award("opoy", 1972))],
 [("Name a 49ers QB", team("SF", "QB", sub=f"{ALL} · {QB}")),
  ("Name a Vikings WR", team("MIN", "WR", sub=f"{ALL} · {G99}")),
  ("Name a player who played for the Falcons and the Panthers", two("ATL", "CAR", None, 1995)),
  ("Name a player who played for the Giants and the Eagles", two("NYG", "PHI", None)),
  ("Name an NFC WR from the 1980s", era(1980, 1989, "WR", "NFC")),
  stat_p("RB", "receiving_yards", 500, "receiving yard"),
  ("Name an AP Defensive Rookie of the Year", award("droy", 1967))],
 [("Name a Seahawks RB", team("SEA", "RB", 2000, f"2000–2026 seasons · {G}")),
  ("Name an AFC East QB", div("AFC East", "QB")),
  ("Name a skill player (RB/WR/TE) who played for the Eagles and Washington", two("PHI", "WAS", ["RB", "WR", "TE"])),
  ("Name a skill player (RB/WR/TE) who played for the Bears and the Lions", two("CHI", "DET", ["RB", "WR", "TE"])),
  ("Name a kicker from the 1990s", era(1990, 1999, "K")),
  stat_p("WR", "receiving_tds", 9, "receiving TD"),
  ("Name an AP Comeback Player of the Year", award("comeback", 1998))],
 [("Name a Dolphins QB", team("MIA", "QB", sub=f"{ALL} · {QB}")),
  ("Name a Saints WR", team("NO", "WR", sub=f"{ALL} · {G99}")),
  ("Name a skill player (RB/WR/TE) who played for the Bills and the Patriots", two("BUF", "NE", ["RB", "WR", "TE"])),
  ("Name a player who played for the Saints and the Buccaneers", two("NO", "TB", None)),
  ("Name an NFC TE from the 1990s", era(1990, 1999, "TE", "NFC")),
  stat_p("QB", "rushing_yards", 300, "rushing yard"),
  ("Name an AP MVP", award("mvp", 1957))],
 [("Name a Bears QB", team("CHI", "QB", sub=f"{ALL} · {QB}")),
  ("Name an NFC West TE", div("NFC West", "TE")),
  ("Name a player who played for the Broncos and the Chiefs", two("DEN", "KC", None)),
  ("Name a player who played for the Packers and the Lions", two("GB", "DET", None)),
  ("Name an AFC QB from the 1980s", era(1980, 1989, "QB", "AFC")),
  ("Name a RB with a 60+ reception season", stat("receptions", 60, "RB")),
  ("Name an AP Defensive Player of the Year", award("dpoy", 1971))],
]

# award slot: 5-award cycle (OPOY dropped: its fixed pool can't meet the Sleeper rule)
AWARD_CYCLE = ["mvp", "dpoy", "oroy", "droy", "comeback"]
AWARD_TEXT = {"mvp": ("Name an AP MVP", 1957), "dpoy": ("Name an AP Defensive Player of the Year", 1971),
              "oroy": ("Name an AP Offensive Rookie of the Year", 1967), "droy": ("Name an AP Defensive Rookie of the Year", 1967),
              "comeback": ("Name an AP Comeback Player of the Year", 1998)}
# AP Comeback is retired (2026-11-08, spec §6): its 27-winner pool can't meet the Sleeper rule
# under award F = s_pv. Its two slots take the first two "either award" candidates that passed
# both publish rules, in the order probed: ROY (O or D), then MVP or OPOY.
def award_any(awards, lo):
    return ("trait", {"award_any": awards, "season_min": lo, "season_max": 2025}, f"{lo}–2025 seasons")

COMEBACK_REPLACEMENTS = [
    ("Name an AP Rookie of the Year (offense or defense)", award_any(["oroy", "droy"], 1967)),   # Day 5
    ("Name an AP MVP or Offensive Player of the Year", award_any(["mvp", "opoy"], 1957)),          # Day 10
]
replaced = 0
for i, day in enumerate(DAYS):
    a = AWARD_CYCLE[i % 5]
    if a == "comeback":
        day[6] = COMEBACK_REPLACEMENTS[replaced]
        replaced += 1
        continue
    text, lo = AWARD_TEXT[a]
    day[6] = (text, award(a, lo))
assert replaced == len(COMEBACK_REPLACEMENTS)

# ---------------------------------------------------------------------------------------------
# Slot plan of 2026-11-11 (spec §6): the two-team slots are gone. Drives 1-2 stay frozen as
# published; Drives 3-14 get P3 college, P4 new stat types, P7 honors. P1, P2, P5, P6 unchanged.
# Every prompt below passed both publish rules in the probes (prompts/college_*.jsonl,
# weekly_stat_probe.jsonl, honors_probe.jsonl). Rules applied: no school two days running (all 12
# differ), at most one 250+-answer prompt per day across all slots (the fixed slots already have one
# on Days 3, 5, 9, 11), P7 never the same type two days running.
SINCE74 = "Since 1974 · Must have played in an NFL regular-season game"
SINCE99 = "Since 1999 · Regular season"


def college(school, pos):
    a = "an" if pos in ("OL", "LB", "RB") else "a"
    return (f"Name {a} {pos} who played college football at {school}",
            ("trait", {"season_min": 1974, "college": school, "position": pos}, SINCE74))


def weekly(text, key, stat_name, n, pos=None, pos_not=None, sub=SINCE99):
    f = {"season_min": 1999, key: {"stat": stat_name, "min": n}}
    if pos: f["position"] = pos
    if pos_not: f["position_not"] = pos_not
    return (text, ("trait", f, sub))


def honor(text, filters, sub):
    return (text, ("trait", filters, sub))


P3 = {  # day -> college prompt
    3: college("LSU", "DB"), 4: college("Florida", "WR"), 5: college("Penn State", "LB"),
    6: college("Wisconsin", "OL"), 7: college("Oklahoma", "RB"), 8: college("Clemson", "DL"),
    9: college("UCLA", "DB"), 10: college("USC", "WR"), 11: college("Georgia", "LB"),
    12: college("Notre Dame", "OL"), 13: college("Auburn", "RB"), 14: college("Michigan", "LB"),
}
P4 = {  # day -> weekly stat prompt (250+ answers: Day 4 non-RB rushing TD 412)
    3: weekly("Name a player with 3.5+ sacks in a game", "game_stat", "sacks", 3.5),
    4: weekly("Name a non-running back with a rushing TD", "window_stat", "rushing_tds", 1, pos_not=["RB"],
              sub="Since 1999 · QBs count · Fullbacks count as running backs"),
    5: weekly("Name an RB with 800+ rushing yards in his rookie season", "rookie_stat", "rushing_yards", 800, pos="RB"),
    6: weekly("Name a player with a 3+ interception game", "game_stat", "interceptions", 3),
    7: weekly("Name a player with 200+ receiving yards in a game", "game_stat", "receiving_yards", 200),
    8: weekly("Name a player with 7+ sacks in his rookie season", "rookie_stat", "sacks", 7),
    9: weekly("Name a QB with 4+ passing TDs in a game", "game_stat", "passing_tds", 4, pos="QB"),
    10: weekly("Name an RB with 100+ receiving yards in a game", "game_stat", "receiving_yards", 100, pos="RB"),
    11: weekly("Name a non-QB who threw a TD pass", "window_stat", "passing_tds", 1, pos_not=["QB"]),
    12: weekly("Name a player with 200+ rushing yards in a game", "game_stat", "rushing_yards", 200),
    13: weekly("Name a WR who threw a TD pass", "window_stat", "passing_tds", 1, pos="WR"),  # was DL with an INT (326)
    14: weekly("Name a player with 4+ interceptions in his rookie season", "rookie_stat", "interceptions", 4),
}
AP1 = "AP first team, 2000–2025 seasons"
P7 = {  # day -> honors prompt; types: AP · HOF · Pro Bowl · draft · All-Pro · Heisman · HOF · Pro Bowl · AP · All-Pro · SB MVP · draft
    3: ("Name an AP Offensive Rookie of the Year", award("oroy", 1967)),
    4: honor("Name a Hall of Fame defensive lineman", {"hall_of_fame": True, "position": "DL"},
             "Pro Football Hall of Fame · inducted as a defensive lineman"),
    5: honor("Name a Steelers Pro Bowler since 2000", {"pro_bowl": True, "team": "PIT", "season_min": 2000, "season_max": 2025},
             "2000–2025 seasons · selected while with the Steelers"),
    6: honor("Name a first-round QB drafted since 2000", {"draft": {"round": 1}, "position": "QB", "season_min": 2000},
             "2000–2026 drafts · must have started a regular-season game"),
    7: honor("Name a first-team All-Pro LB since 2000", {"all_pro": True, "position": "LB", "season_min": 2000, "season_max": 2025},
             f"{AP1} · at LB"),
    8: honor("Name a Heisman Trophy winner who played in the NFL", {"award": "heisman"},
             "1935–2025 winners · must have played in an NFL regular-season game"),
    9: honor("Name a Hall of Fame WR", {"hall_of_fame": True, "position": "WR"},
             "Pro Football Hall of Fame · inducted as a receiver or end"),
    10: honor("Name a Cowboys Pro Bowler since 2000", {"pro_bowl": True, "team": "DAL", "season_min": 2000, "season_max": 2025},
              "2000–2025 seasons · selected while with the Cowboys"),
    11: ("Name an AP Defensive Rookie of the Year", award("droy", 1967)),
    12: honor("Name a first-team All-Pro DB since 2000", {"all_pro": True, "position": "DB", "season_min": 2000, "season_max": 2025},
              f"{AP1} · at CB or S"),
    13: honor("Name a Super Bowl MVP", {"award": "sb_mvp"}, "Super Bowl I–LX"),
    14: honor("Name a #1 overall draft pick", {"draft": {"pick": 1}, "season_min": 1980},
              "Since 1980 · must have played in an NFL regular-season game"),
}
for d in range(3, 15):
    DAYS[d - 1][2], DAYS[d - 1][3], DAYS[d - 1][6] = P3[d], P4[d], P7[d]

assert len(DAYS) == 14 and all(len(d) == 7 for d in DAYS)
out = Path(__file__).with_suffix("").parent / "prompts_14_days.jsonl"
with open(out, "w") as fh:
    for d, prompts in enumerate(DAYS, 1):
        for s, (text, (ptype, filters, sub)) in enumerate(prompts, 1):
            fh.write(json.dumps({"day": d, "slot": s, "id": f"d{d:02d}-{s}", "text": text, "subtitle": sub,
                                 "type": ptype, "filters": filters}, ensure_ascii=False) + "\n")
print(f"wrote {out} ({sum(len(d) for d in DAYS)} prompts)")
