"""Build step 7: prompt scheduling + publish flow (spec §6 export format, §9 Drive #).

    uv run publish build                 # all scheduled drives -> public/ (hard stop if any prompt
                                         # has < 25 answers or < 3 Sleeper Picks besides the YKB Kid)
    uv run publish build --drive 3       # one drive
    uv run publish diff                  # weekly refresh diff report vs the last published public/
    uv run publish schedule --launch 2026-11-09   # (re)write the schedule from the prompt queue

Frozen drives (§6): a drive is frozen once it goes live (00:00 ET on its date), and every drive
up to `frozen_through` in prompts/schedule.json is frozen too. Frozen drives are never rebuilt:
build/diff read them back from public/days/<n>.json (their YKB Kids still count for the window).

Weekly flow in season: `refresh --skip pageviews` (or full) -> `publish diff` (review) -> `publish build`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from .answers import MIN_ANSWERS, STATS, TIGHT_MARGIN, Prompt, _as_list, _context_where, build_answers
from .db import ROOT, connect
from .matching import NAME_GROUPS, allowed_edits, bank_aliases
from .scoring import TIERS, fame, load_thresholds, score_answers, threshold_kind
from .teams import FRANCHISE_NAMES

FORMAT_VERSION = 1
DIST = ROOT / "public"   # deployed as-is; the UI fetches these files
ROLLOVER = {"time": "00:00", "timezone": "America/New_York"}  # §9: new drive at midnight Eastern
SCHEDULE = ROOT / "prompts" / "schedule.json"
QUEUE = ROOT / "prompts" / "prompts_14_days.jsonl"
REPORTS = ROOT / "reports"
MIN_SLEEPERS = 3  # §6: a prompt ships only with at least 3 Sleeper Picks besides the YKB Kid
YKB_WINDOW = 14   # §2: a player is YKB Kid at most once in any 14-day window

# §2 points, §9 yards (= points / 5) and share squares
TIER_INFO = {
    "Starter": {"points": 10, "square": "⬜"},
    "Botched Trick Play": {"points": 15, "square": "🟧"},
    "Backup": {"points": 30, "square": "🟦"},
    "Hidden Gem": {"points": 60, "square": "🟩"},
    "Sleeper Pick": {"points": 85, "square": "🟪"},
    "YKB Kid": {"points": 100, "square": "🟨"},
    "Incomplete": {"points": 0, "square": "⬛"},
}
for v in TIER_INFO.values():
    v["yards"] = v["points"] // 5

STAT_UNIT = {"passing_yards": "yds", "rushing_yards": "yds", "receiving_yards": "yds", "scrimmage_yards": "yds",
             "passing_tds": "TD", "rushing_tds": "TD", "receiving_tds": "TD", "receptions": "rec",
             "sacks": "sacks", "interceptions": "INT", "field_goals": "FG"}


# ------------------------------------------------------------------ schedule

def today_et() -> dt.date:
    return dt.datetime.now(ZoneInfo(ROLLOVER["timezone"])).date()


def is_frozen(drive: dict, sched: dict, today: dt.date | None = None) -> bool:
    """§6: a drive is frozen once it goes live (00:00 ET on its date), or if it is at or before
    the schedule's `frozen_through`. A frozen drive is never regenerated."""
    today = today or today_et()
    return dt.date.fromisoformat(drive["date"]) <= today or drive["drive"] <= int(sched.get("frozen_through", 0))


def drive_number(day: dt.date, launch: dt.date) -> int:
    """§9: Drive # = days since launch, the same for everyone. Launch day is Drive #1."""
    return (day - launch).days + 1


def write_schedule(launch: dt.date, queue: Path = QUEUE) -> dict:
    """One drive per queue day, in order: Day d of the queue -> Drive #d on launch + d - 1."""
    days: dict[int, list[str]] = {}
    for line in queue.read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            p = json.loads(line)
            days.setdefault(int(p["day"]), []).append(p["id"])
    sched = {"launch_date": launch.isoformat(), "rollover": ROLLOVER, "queue": str(queue.relative_to(ROOT)),
             "drives": [{"drive": d, "date": (launch + dt.timedelta(days=d - 1)).isoformat(), "prompt_ids": ids}
                        for d, ids in sorted(days.items())]}
    if SCHEDULE.exists():  # §6: never move or change a frozen drive
        old = json.loads(SCHEDULE.read_text())
        if "frozen_through" in old:
            sched["frozen_through"] = old["frozen_through"]
        new = {d["drive"]: d for d in sched["drives"]}
        for d in old["drives"]:
            if is_frozen(d, old) and new.get(d["drive"]) != d:
                sys.exit(f"drive {d['drive']} is frozen (§6); the new schedule would change it")
    SCHEDULE.write_text(json.dumps(sched, indent=2) + "\n")
    return sched


def load_schedule() -> dict:
    if not SCHEDULE.exists():
        sys.exit("no prompts/schedule.json; run `publish schedule --launch YYYY-MM-DD` first")
    return json.loads(SCHEDULE.read_text())


def load_prompts(path: Path) -> dict[str, dict]:
    return {json.loads(l)["id"]: json.loads(l) for l in path.read_text().splitlines() if l.strip() and not l.startswith("#")}


# ------------------------------------------------------------- context lines

def _span(a: int, b: int) -> str:
    """2009-16 style; full years when the century changes; one year alone."""
    if a == b:
        return str(a)
    return f"{a}–{str(b)[2:]}" if a // 100 == b // 100 else f"{a}–{b}"


def _games_complete(rows: pl.DataFrame) -> bool:
    """§6: games are trusted only where data is complete: every counted season 2013+ (snap
    counts), or 1999+ for QB/RB/WR/TE (whose stat rows track appearances)."""
    return all(s >= 2013 or (s >= 1999 and g in ("QB", "RB", "WR", "TE"))
               for s, g in rows.select("season", "pos_group").iter_rows())


def context_lines(con, prompt: Prompt, scored: pl.DataFrame) -> dict[str, str]:
    """§6 context line per answer, from Step 1 evidence."""
    f = prompt.filters
    ids = scored["player_id"].to_list()
    if not ids:
        return {}
    con.register("_ids", pl.DataFrame({"player_id": ids}).to_arrow())
    try:
        if "award" in f:
            awards = _as_list(f["award"])
            rows = con.execute(f"""
                SELECT player_id, list(DISTINCT season ORDER BY season) FROM player_awards
                WHERE player_id IN (SELECT player_id FROM _ids) AND award IN ({', '.join('?' * len(awards))})
                  AND season BETWEEN ? AND ? GROUP BY 1""",
                awards + [int(f.get("season_min", 0)), int(f.get("season_max", 9999))]).fetchall()
            return {pid: "Won " + ", ".join(str(s) for s in seasons) for pid, seasons in rows}
        if st := f.get("stat_threshold"):
            expr, unit = STATS[st["stat"]], STAT_UNIT[st["stat"]]
            rows = con.execute(f"""
                SELECT player_id, arg_max(season, v), max(v) FROM (
                    SELECT player_id, season, sum({expr}) v FROM raw_player_week
                    WHERE season_type = 'REG' AND player_id IN (SELECT player_id FROM _ids)
                      AND season BETWEEN ? AND ? GROUP BY 1, 2)
                WHERE v >= ? GROUP BY 1""", [int(f.get("season_min", 1999)), int(f.get("season_max", 9999)), st["min"]]).fetchall()
            fmt = lambda v: f"{v:,.1f}".rstrip("0").rstrip(".") if v != int(v) else f"{int(v):,}"
            return {pid: f"{fmt(v)} {unit} · {season}" for pid, season, v in rows}

        teams = _as_list(f.get("teams_all", f.get("team", []))) or None
        where, _ = _context_where(f, teams)
        ev = con.sql(f"""
            SELECT t.player_id, t.franchise, t.season, t.pos_group, t.games, t.qb_starts
            FROM player_team_seasons t
            WHERE t.player_id IN (SELECT player_id FROM _ids) AND {where} AND (t.counted OR t.qb_starts > 0)
        """).pl()
    finally:
        con.unregister("_ids")

    is_qb = [x.upper() for x in _as_list(f.get("position", []))] == ["QB"]
    unit = dict(zip(scored["player_id"], scored["unit"])) if "unit" in scored.columns else {}
    out = {}
    for (pid,), rows in ev.group_by(["player_id"]):
        if "teams_all" in f:  # "Raiders 2004–07 · Chiefs 2008"
            parts = []
            for t in _as_list(f["teams_all"]):
                r = rows.filter(pl.col("franchise") == t)
                if r.height:
                    parts.append(f"{FRANCHISE_NAMES.get(t, t)} {_span(r['season'].min(), r['season'].max())}")
            out[pid] = " · ".join(parts)
        elif "team" in f:
            span = _span(rows["season"].min(), rows["season"].max())
            if is_qb and unit.get(pid) == "starts":
                n = int(rows["qb_starts"].sum())
                out[pid] = f"{n} start{'s' * (n != 1)} · {span}"
            elif _games_complete(rows):
                n = int(rows["games"].sum())
                out[pid] = f"{n} game{'s' * (n != 1)} · {span}"
            else:
                n = rows["season"].n_unique()
                out[pid] = f"{n} season{'s' * (n != 1)} · {span}"
        else:  # era / conference / division: "Colts, Bills · 1990–97"
            order = rows.group_by("franchise").agg(pl.col("season").min()).sort("season")["franchise"].to_list()
            names = [FRANCHISE_NAMES.get(t, t) for t in order]
            label = ", ".join(names[:3]) + (f" +{len(names) - 3}" if len(names) > 3 else "")
            out[pid] = f"{label} · {_span(rows['season'].min(), rows['season'].max())}"
    return out


# ------------------------------------------------------------------- export

def export_prompt(con, obj: dict, slot: int, f_df: pl.DataFrame,
                  ykb_exclude: set[str] | None = None) -> tuple[dict, list[str]]:
    """One prompt's answer bank in the §6 export format, plus publish warnings."""
    p = Prompt.from_json(obj)
    r = build_answers(con, p)
    scored, info = score_answers(con, r, f_df, ykb_exclude)
    warnings = list(r.warnings)
    if r.n < MIN_ANSWERS:
        warnings.append(f"HARD STOP: {r.n} answers")
    ykb = info.get("ykb_kid")
    if p.ykb_kid and p.ykb_kid not in scored["player_id"].to_list():
        warnings.append(f"ykb_kid override {p.ykb_kid} is not a valid answer")
    if p.ykb_kid and ykb_exclude and p.ykb_kid in ykb_exclude:
        warnings.append(f"ykb_kid override {p.ykb_kid} was already YKB Kid in the last {YKB_WINDOW} days")
    if not ykb:
        warnings.append("no YKB Kid (no Sleeper Pick or Hidden Gem)")
    n_sleepers = int((scored["tier"] == "Sleeper Pick").sum())  # YKB Kid already re-tiered
    if n_sleepers < MIN_SLEEPERS:
        warnings.append(f"HARD STOP: {n_sleepers} Sleeper Picks besides the YKB Kid (< {MIN_SLEEPERS})")
    ctx = context_lines(con, p, scored)
    aliases = bank_aliases(con, scored["player_id"].to_list())
    answers = []
    for row in scored.iter_rows(named=True):
        al = aliases.get(row["player_id"], [])
        answers.append({
            "id": row["player_id"],
            "name": row["display_name"],
            "tier": row["tier"],
            "context": ctx.get(row["player_id"], ""),
            "names": sorted({a for a, k in al if k != "last_only"}),
            "last_names": sorted({a for a, k in al if k == "last_only"}),
            "r": round(row["R_prime"], 4),
        })
    missing = [a["name"] for a in answers if not a["context"]]
    if missing:
        warnings.append(f"{len(missing)} answers without a context line (e.g. {missing[0]})")
    return {
        "slot": slot, "id": p.id, "text": p.text, "subtitle": p.subtitle, "type": p.type,
        "tier_group": threshold_kind(p), "answer_count": len(answers),
        "ykb_kid": ykb, "ykb_source": info.get("ykb_source"), "botched_trick_play": p.botched_trick_play,
        "answers": answers,
    }, warnings


def built_drives(con, sched: dict, prompts: dict[str, dict], f_df: pl.DataFrame):
    """Yield (drive, data, warnings) for every scheduled drive in order. YKB Kids are chosen
    with the §2 window rule, so earlier drives are always built first."""
    hist: dict[int, list[str]] = {}
    today = today_et()
    for d in sched["drives"]:
        if is_frozen(d, sched, today):
            # §6: frozen drives are read back as published, never rebuilt
            path = DIST / "days" / f"{d['drive']}.json"
            if not path.exists():
                sys.exit(f"drive {d['drive']} is frozen (§6) but {path} is missing")
            data = json.loads(path.read_text())
            hist[d["drive"]] = [e["ykb_kid"] for e in data["prompts"] if e["ykb_kid"]]
            yield {**d, "frozen": True}, data, {}
            continue
        data, warns, picks = build_drive(con, d, prompts, f_df, window_exclude(hist, d["drive"]))
        hist[d["drive"]] = picks
        yield d, data, warns


def window_exclude(hist: dict[int, list[str]], drive: int) -> set[str]:
    return {pid for n, picks in hist.items() if drive - YKB_WINDOW < n < drive for pid in picks}


def build_drive(con, drive: dict, prompts: dict[str, dict], f_df: pl.DataFrame,
                ykb_exclude: set[str] | None = None) -> tuple[dict, dict[str, list[str]], list[str]]:
    """-> (drive file, warnings per prompt, YKB Kid ids)."""
    out, warns = [], {}
    used = set(ykb_exclude or set())
    for slot, pid in enumerate(drive["prompt_ids"], 1):
        e, w = export_prompt(con, prompts[pid], slot, f_df, used)
        if e["ykb_kid"]:
            used.add(e["ykb_kid"])  # also unique within the drive
        out.append(e)
        if w:
            warns[pid] = w
    data_version = con.execute("SELECT max(finished_at) FROM refresh_log").fetchall()[0][0]
    return {
        "format": FORMAT_VERSION,
        "drive": drive["drive"],
        "date": drive["date"],
        "data_version": data_version.isoformat() if data_version else None,
        "thresholds_frozen_at": (load_thresholds() or {}).get("frozen_at"),
        "prompts": out,
    }, warns, [e["ykb_kid"] for e in out if e["ykb_kid"]]


def write_static(con) -> None:
    """Files every drive shares: tiers + drive rules, matching rules, and the non-bank name index."""
    DIST.mkdir(parents=True, exist_ok=True)
    (DIST / "game.json").write_text(json.dumps({
        "format": FORMAT_VERSION,
        "tiers": TIER_INFO,
        "drive": {"start_yardline": 25, "touchdown_yards": 75, "trail": [17, 21], "win": [24, 21],
                  "clock_start_seconds": 175, "seconds_per_play": 25, "plays": 7},
    }, ensure_ascii=False, indent=1))
    others: dict[str, list[str]] = {}
    for pid, alias in con.execute("SELECT player_id, alias FROM aliases WHERE kind <> 'last_only'").fetchall():
        others.setdefault(alias, []).append(pid)
    (DIST / "matching.json").write_text(json.dumps({
        "format": FORMAT_VERSION,
        "first_name_groups": [sorted(g) for g in NAME_GROUPS],
        "edit_budget": [{"max_chars": n, "edits": allowed_edits(n)} for n in (3, 6, 12)] + [{"max_chars": None, "edits": 3}],
        "all_player_names": others,
    }, ensure_ascii=False, separators=(",", ":")))


def cmd_build(drive_filter: int | None, force: bool) -> None:
    con = connect(read_only=True)
    sched = load_schedule()
    prompts = load_prompts(ROOT / sched["queue"])
    f_df = fame(con)
    (DIST / "days").mkdir(parents=True, exist_ok=True)
    write_static(con)
    index, stops = [], []
    for d, data, warns in built_drives(con, sched, prompts, f_df):
        if drive_filter and d["drive"] != drive_filter:
            continue
        if d.get("frozen"):  # §6: never rewritten, not even with --force
            index.append({"drive": d["drive"], "date": d["date"], "file": f"days/{d['drive']}.json"})
            print(f"  drive {d['drive']}: frozen, left as published")
            continue
        hard = {k: w for k, w in warns.items() if any(x.startswith("HARD STOP") for x in w)}
        if hard and not force:
            stops.append((d["drive"], hard))
            continue
        (DIST / "days" / f"{d['drive']}.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
        index.append({"drive": d["drive"], "date": d["date"], "file": f"days/{d['drive']}.json"})
        for pid, w in warns.items():
            print(f"  drive {d['drive']} {pid}: {'; '.join(w)}")
    if not drive_filter:
        (DIST / "schedule.json").write_text(json.dumps({"format": FORMAT_VERSION, "launch_date": sched["launch_date"],
                                                        "rollover": ROLLOVER, "drives": index}, indent=1))
    print(f"wrote {len(index)} drive(s) to {DIST}")
    if stops:
        for drv, hard in stops:
            print(f"  NOT PUBLISHED drive {drv}: {hard}")
        sys.exit(1)


# -------------------------------------------------------------- diff report

def cmd_diff(out: Path | None) -> None:
    """§6 weekly diff report: current build vs the last published public/ for every scheduled drive."""
    con = connect(read_only=True)
    sched = load_schedule()
    prompts = load_prompts(ROOT / sched["queue"])
    f_df = fame(con)
    today = today_et()
    lines = [f"# Diff report — {today.isoformat()}", "",
             "Current build vs last published `public/`. Unfrozen drives only (§6). "
             f"Tight = within {TIGHT_MARGIN} of the {MIN_ANSWERS}-answer minimum.", ""]
    flags = []
    for d, new, warns in built_drives(con, sched, prompts, f_df):
        if d.get("frozen"):  # §6: live, past, or frozen_through — nothing to diff
            continue
        old_path = DIST / "days" / f"{d['drive']}.json"
        old = {p["id"]: p for p in json.loads(old_path.read_text())["prompts"]} if old_path.exists() else {}
        lines.append(f"## Drive {d['drive']} — {d['date']}" + ("" if old else " (not published yet)"))
        for p in new["prompts"]:
            n = p["answer_count"]
            tags = []
            if n < MIN_ANSWERS:
                tags.append("⛔ below minimum")
            elif n <= MIN_ANSWERS + TIGHT_MARGIN:
                tags.append("⚠️ tight")
            o = old.get(p["id"])
            if o:
                oa = {a["id"]: a for a in o["answers"]}
                na = {a["id"]: a for a in p["answers"]}
                added = [na[i]["name"] for i in na.keys() - oa.keys()]
                removed = [oa[i]["name"] for i in oa.keys() - na.keys()]
                moved = [f"{na[i]['name']} {oa[i]['tier']}→{na[i]['tier']}" for i in na.keys() & oa.keys()
                         if oa[i]["tier"] != na[i]["tier"]]
                delta = f"{o['answer_count']} → {n}" if o["answer_count"] != n else f"{n}"
            else:
                added = removed = moved = []
                delta = f"{n}"
            qb_flags = [w for w in warns.get(p["id"], []) if "mismatch" in w]
            lines.append(f"- **{p['text']}** — {delta} answers {' '.join(tags)}")
            for label, items in (("new", added), ("removed", removed), ("tier changes", moved)):
                if items:
                    lines.append(f"  - {label} ({len(items)}): {', '.join(items[:15])}{' …' if len(items) > 15 else ''}")
            if tags:
                flags.append(f"Drive {d['drive']} · {p['text']} · {n} {' '.join(tags)}")
            for q in qb_flags:
                lines.append(f"  - {q}")
        lines.append("")
    # §3: current-season QB source mismatches are flagged here, never silently resolved
    season = con.execute("SELECT max(season) FROM qb_starts").fetchall()[0][0]
    mm = con.execute("""SELECT x.franchise, coalesce(x.wiki_name, p.display_name), x.wiki_starts, x.nflverse_starts, x.status
                        FROM qb_list_crosscheck x LEFT JOIN players p USING (player_id)
                        WHERE x.season = ? AND x.status IN ('count_differs','missing_in_wikipedia','missing_in_nflverse')
                        ORDER BY 1""", [season]).fetchall()
    lines += [f"## {season} QB starts: Wikipedia vs nflverse ({len(mm)} mismatches, flagged not resolved)"]
    lines += [f"- {fr} {name}: Wikipedia {w} vs nflverse {n} ({s})" for fr, name, w, n, s in mm] or ["- none"]
    lines = lines[:4] + ["## Flags", *(f"- {x}" for x in flags or ["none"]), ""] + lines[4:]
    text = "\n".join(lines) + "\n"
    REPORTS.mkdir(exist_ok=True)
    out = out or REPORTS / f"diff_{today.isoformat()}.md"
    out.write_text(text)
    print(f"wrote {out}  ({len(flags)} flag(s), {len(mm)} QB mismatch(es))")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="publish", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--drive", type=int)
    b.add_argument("--force", action="store_true", help="publish even with prompts under the minimum")
    dfp = sub.add_parser("diff")
    dfp.add_argument("--out", type=Path)
    s = sub.add_parser("schedule")
    s.add_argument("--launch", required=True, type=dt.date.fromisoformat)
    args = ap.parse_args(argv)
    if args.cmd == "build":
        cmd_build(args.drive, args.force)
    elif args.cmd == "diff":
        cmd_diff(args.out)
    else:
        sched = write_schedule(args.launch)
        print(f"wrote {SCHEDULE}: {len(sched['drives'])} drives from {sched['launch_date']}")


if __name__ == "__main__":
    main()
