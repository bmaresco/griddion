"""Build step 7: prompt scheduling + publish flow (spec §6 export format, §9 Drive #).

    uv run publish build                 # all scheduled drives -> public/ (hard stop if any prompt < 25)
    uv run publish build --drive 3       # one drive
    uv run publish diff                  # weekly refresh diff report vs the last published public/
    uv run publish schedule --launch 2026-11-09   # (re)write the schedule from the prompt queue

Weekly flow in season: `refresh --skip pageviews` (or full) -> `publish diff` (review) -> `publish build`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

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
             "sacks": "sacks", "interceptions": "INT"}


# ------------------------------------------------------------------ schedule

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

def export_prompt(con, obj: dict, slot: int, f_df: pl.DataFrame) -> tuple[dict, list[str]]:
    """One prompt's answer bank in the §6 export format, plus publish warnings."""
    p = Prompt.from_json(obj)
    r = build_answers(con, p)
    scored, info = score_answers(con, r, f_df)
    warnings = list(r.warnings)
    if r.n < MIN_ANSWERS:
        warnings.append(f"HARD STOP: {r.n} answers")
    ykb = info.get("ykb_kid")
    if p.ykb_kid and p.ykb_kid not in scored["player_id"].to_list():
        warnings.append(f"ykb_kid override {p.ykb_kid} is not a valid answer")
    if not ykb:
        warnings.append("no YKB Kid (no Sleeper Pick or Hidden Gem)")
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


def build_drive(con, drive: dict, prompts: dict[str, dict], f_df: pl.DataFrame) -> tuple[dict, dict[str, list[str]]]:
    out, warns = [], {}
    for slot, pid in enumerate(drive["prompt_ids"], 1):
        e, w = export_prompt(con, prompts[pid], slot, f_df)
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
    }, warns


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
    for d in sched["drives"]:
        if drive_filter and d["drive"] != drive_filter:
            continue
        data, warns = build_drive(con, d, prompts, f_df)
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
    today = dt.date.today()
    lines = [f"# Diff report — {today.isoformat()}", "",
             "Current build vs last published `public/`. Upcoming drives only. "
             f"Tight = within {TIGHT_MARGIN} of the {MIN_ANSWERS}-answer minimum.", ""]
    flags = []
    for d in sched["drives"]:
        if dt.date.fromisoformat(d["date"]) < today:
            continue
        old_path = DIST / "days" / f"{d['drive']}.json"
        old = {p["id"]: p for p in json.loads(old_path.read_text())["prompts"]} if old_path.exists() else {}
        new, warns = build_drive(con, d, prompts, f_df)
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
