"""`probe`: dry-run a prompt (spec §8). Local DB only, no web calls.

    uv run probe '{"text": "Name a Bears QB since 2000", "filters": {"team": "CHI", "position": "QB", "season_min": 2000}}'
    uv run probe --file prompts.jsonl          # batch: one prompt JSON per line -> summary table
    uv run probe '...' --all                   # list every valid answer
"""

from __future__ import annotations

import argparse
import json
import sys

import polars as pl

from .answers import DAY_AVG_MAX, MIN_ANSWERS, Prompt, Result, build_answers
from .db import connect

SAMPLE = 8


def _describe(f: dict) -> str:
    parts = []
    for k in ("team", "teams_all", "position", "conference", "division", "league", "award"):
        if k in f:
            v = f[k]
            parts.append(f"{k}={'+'.join(v) if isinstance(v, list) else v}")
    if "season_min" in f or "season_max" in f:
        parts.append(f"seasons {f.get('season_min', '…')}–{f.get('season_max', 'now')}")
    if st := f.get("stat_threshold"):
        parts.append(f"{st['stat']} ≥ {st['min']} in a season")
    return ", ".join(parts)


def _names(df: pl.DataFrame, n: int) -> str:
    return ", ".join(df["display_name"].head(n).to_list()) or "—"


def report(r: Result, show_all: bool = False) -> str:
    p, a = r.prompt, r.answers
    ok = f"✅ (≥ {MIN_ANSWERS})" if r.n >= MIN_ANSWERS else f"⛔ below minimum ({MIN_ANSWERS})"
    out = [f'"{p.text or p.id}"  →  {_describe(p.filters)}', f"Valid answers: {r.n}   {ok}"]
    if r.n:
        out += [f"Sample (most known): {_names(a, SAMPLE)}",
                f"Sample (least known): {_names(a.reverse(), SAMPLE)}"]
        basis = a.explode("bases")["bases"].value_counts().sort("count", descending=True)
        out.append("Validity basis: " + ", ".join(f"{b} {c}" for b, c in basis.iter_rows()))
    pre = a.filter(pl.col("pre1950_qb")) if r.n else a
    if pre.height:
        out.append(f"Pre-1950 QBs (roster rule, review): {_names(pre, 50)}")
    e = r.edge_cases
    if (q := e.get("qb_no_start")) is not None and q.height:
        out.append(f"Edge cases: {q.height} listed QBs with 0 starts in context excluded")
    if (u := e.get("unconfirmed_status")) is not None and u.height:
        out.append(f"Edge cases: {u.height} pre-2002 players excluded (season-end RES/CUT/etc. can't confirm play)")
    if (m := e.get("qb_source_mismatch")) is not None and m.height:
        out.append(f"QB source mismatches (Wikipedia vs nflverse, flagged not resolved): {m.height}")
        for row in m.head(10).iter_rows(named=True):
            out.append(f"    {row['season']} {row['franchise']} {row['name']}: wiki {row['wiki_starts']} vs nflverse {row['nflverse_starts']} ({row['status']})")
    out.append("Tier preview: n/a until step 3 (score_answers)")
    out += [f"⚠️  {w}" for w in r.warnings]
    if show_all and r.n:
        cols = ["display_name", "first_season", "last_season", "ctx_seasons", "ctx_games", "ctx_qb_starts",
                "career_seasons", "career_qb_starts", "pv24", "bases"]
        with pl.Config(tbl_rows=-1, tbl_width_chars=200, fmt_str_lengths=40):
            out.append(str(a.select([c for c in cols if c in a.columns])))
    return "\n".join(out)


def batch(con, path: str) -> str:
    """One prompt JSON per line; an optional "day" key groups prompts for the per-day check."""
    rows = []
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        obj = json.loads(line)
        p = Prompt.from_json(obj)
        row = {"day": obj.get("day"), "prompt": (p.text or p.id)[:52]}
        try:
            r = build_answers(con, p)
            row |= {"answers": r.n, "status": "ok" if r.n >= MIN_ANSWERS else "STOP",
                    "top": _names(r.answers, 3)[:40], "warnings": "; ".join(r.warnings)[:60]}
        except Exception as ex:  # keep going; report the bad prompt
            row |= {"answers": None, "status": "error", "top": "", "warnings": str(ex)[:60]}
        rows.append(row)
    df = pl.DataFrame(rows)
    out = []
    with pl.Config(tbl_rows=-1, tbl_width_chars=220, fmt_str_lengths=60):
        out.append(str(df))
        if df["day"].drop_nulls().len():
            days = df.group_by("day", maintain_order=True).agg(
                pl.len().alias("prompts"), pl.col("answers").mean().round(1).alias("avg_answers"),
                (pl.col("status") != "ok").sum().alias("below_min_or_error"))
            days = days.with_columns(check=pl.when(pl.col("avg_answers") > DAY_AVG_MAX)
                                     .then(pl.lit(f"⚠️ avg > {DAY_AVG_MAX}")).otherwise(pl.lit("ok")))
            out.append(str(days))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="probe", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prompt", nargs="?", help="prompt JSON (or just the filters object)")
    ap.add_argument("--file", help="batch mode: JSON-lines file of prompts")
    ap.add_argument("--all", action="store_true", help="list every valid answer")
    ap.add_argument("--db")
    args = ap.parse_args(argv)
    con = connect(args.db, read_only=True)
    if args.file:
        print(batch(con, args.file))
        return
    if not args.prompt:
        ap.error("give a prompt JSON or --file")
    obj = json.loads(args.prompt)
    if "filters" not in obj:
        obj = {"filters": obj}
    try:
        print(report(build_answers(con, Prompt.from_json(obj)), args.all))
    except ValueError as ex:
        sys.exit(f"probe: {ex}")


if __name__ == "__main__":
    main()
