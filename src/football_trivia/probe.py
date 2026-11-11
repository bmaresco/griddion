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

from .answers import DAY_AVG_MAX, MIN_ANSWERS, TIGHT_MARGIN, Prompt, Result, build_answers
from .db import connect
from .scoring import TIERS, fame, load_thresholds, score_answers, spread_warnings

SAMPLE = 8


def _describe(f: dict) -> str:
    parts = []
    for k in ("team", "teams_all", "position", "conference", "division", "league", "award", "award_any", "college", "position_not"):  # lists join with +
        if k in f:
            v = f[k]
            parts.append(f"{k}={'+'.join(v) if isinstance(v, list) else v}")
    if "season_min" in f or "season_max" in f:
        parts.append(f"seasons {f.get('season_min', '…')}–{f.get('season_max', 'now')}")
    if st := f.get("stat_threshold"):
        parts.append(f"{st['stat']} ≥ {st['min']} in a season")
    if st := f.get("rookie_stat"):
        parts.append(f"{st['stat']} ≥ {st['min']} in his rookie season")
    if st := f.get("game_stat"):
        parts.append(f"{st['stat']} ≥ {st['min']} in a game" + (f" ({st['games_min']}+ games)" if st.get("games_min", 1) > 1 else ""))
    if st := f.get("window_stat"):
        parts.append(f"{st['stat']} total ≥ {st['min']}")
    return ", ".join(parts)


def _names(df: pl.DataFrame, n: int) -> str:
    return ", ".join(df["display_name"].head(n).to_list()) or "—"


def report(r: Result, show_all: bool = False, scored: pl.DataFrame | None = None, info: dict | None = None) -> str:
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
    if scored is not None and scored.height and scored["tier"].null_count() < scored.height:
        counts = scored["tier"].value_counts()
        c = {t: n for t, n in counts.iter_rows()}
        out.append("Tier preview: " + " · ".join(f"{t} {c.get(t, 0)}" for t in TIERS) + f"   (unit: {info['unit']})")
    elif scored is not None and scored.height:
        out.append(f"Tier preview: thresholds not frozen yet (run `probe --calibrate`); unit: {info['unit']}")
    for n in (info or {}).get("notes", []):
        out.append(f"Note: {n}")
    out += [f"⚠️  {w}" for w in r.warnings]
    if show_all and r.n:
        src = scored if scored is not None else a
        cols = ["display_name", "first_season", "last_season", "ctx_seasons", "ctx_qb_starts", "career_seasons",
                "career_qb_starts", "F", "share", "prominence", "peak", "A", "R_prime", "tier", "bases"]
        with pl.Config(tbl_rows=-1, tbl_width_chars=220, fmt_str_lengths=40, float_precision=3):
            out.append(str(src.select([c for c in cols if c in src.columns])))
    return "\n".join(out)


def batch(con, path: str) -> str:
    """One prompt JSON per line; an optional "day" key groups prompts for the per-day check."""
    rows = []
    f = fame(con)
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        obj = json.loads(line)
        p = Prompt.from_json(obj)
        row = {"day": obj.get("day"), "prompt": (p.text or p.id)[:52]}
        try:
            r = build_answers(con, p)
            status = "STOP" if r.n < MIN_ANSWERS else ("tight" if r.n <= MIN_ANSWERS + TIGHT_MARGIN else "ok")
            scored, _ = score_answers(con, r, f)
            c = {t: int((scored["tier"] == t).sum()) for t in TIERS} if r.n else {}
            row |= {"answers": r.n, "status": status,
                    "S·B·HG·SP": " · ".join(str(c.get(t, 0)) for t in TIERS),
                    "spread_warnings": "; ".join(spread_warnings(scored)),
                    "warnings": "; ".join(r.warnings)[:60]}
        except Exception as ex:  # keep going; report the bad prompt
            row |= {"answers": None, "status": "error", "S·B·HG·SP": "", "spread_warnings": "", "warnings": str(ex)[:60]}
        rows.append(row)
    df = pl.DataFrame(rows)
    out = []
    with pl.Config(tbl_rows=-1, tbl_width_chars=260, fmt_str_lengths=70):
        out.append(str(df))
        if df["day"].drop_nulls().len():
            days = df.group_by("day", maintain_order=True).agg(
                pl.len().alias("prompts"), pl.col("answers").mean().round(1).alias("avg_answers"),
                pl.col("status").is_in(["STOP", "error"]).sum().alias("below_min_or_error"),
                (pl.col("status") == "tight").sum().alias("tight"))
            days = days.with_columns(check=pl.when(pl.col("avg_answers") > DAY_AVG_MAX)
                                     .then(pl.lit(f"⚠️ avg > {DAY_AVG_MAX}")).otherwise(pl.lit("ok")))
            out.append(str(days))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="probe", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prompt", nargs="?", help="prompt JSON (or just the filters object)")
    ap.add_argument("--file", help="batch mode: JSON-lines file of prompts")
    ap.add_argument("--all", action="store_true", help="list every valid answer")
    ap.add_argument("--calibrate", metavar="FILE", help="pool R' over the prompts in FILE and print §7 thresholds")
    ap.add_argument("--freeze", action="store_true", help="with --calibrate: write data/tier_thresholds.json")
    ap.add_argument("--groups", help="with --freeze: comma-separated threshold groups to rewrite "
                    "(e.g. award); the other groups keep their frozen values")
    ap.add_argument("--db")
    args = ap.parse_args(argv)
    con = connect(args.db, read_only=True)
    if args.calibrate:
        print(calibrate_file(con, args.calibrate, args.freeze,
                             groups=set(args.groups.split(",")) if args.groups else None))
        return
    if args.file:
        print(batch(con, args.file))
        return
    if not args.prompt:
        ap.error("give a prompt JSON or --file")
    obj = json.loads(args.prompt)
    if "filters" not in obj:
        obj = {"filters": obj}
    try:
        r = build_answers(con, Prompt.from_json(obj))
        scored, info = score_answers(con, r)
        print(report(r, args.all, scored, info))
    except ValueError as ex:
        sys.exit(f"probe: {ex}")


if __name__ == "__main__":
    main()


def calibrate_file(con, path: str, freeze: bool, lifetime_blend: float | None = None,
                   groups: set[str] | None = None) -> str:
    """§7 threshold calibration, per prompt type (trait vs other): pool R' with every prompt
    weighted equally, cut at 10/35/35/20."""
    import datetime as dt

    from .scoring import CALIBRATION_SHARES, THRESHOLDS_FILE, calibrate, fame, threshold_kind
    f = fame(con, lifetime_blend)
    pooled: dict[str, list] = {}
    per = []
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        p = Prompt.from_json(line)
        scored, _ = score_answers(con, build_answers(con, p), f)
        kind = threshold_kind(p)
        n = max(scored.height, 1)
        pooled.setdefault(kind, []).extend((x, 1.0 / n) for x in scored["R_prime"].to_list())  # every prompt weighs the same
        per.append((p.id or p.text, kind, scored))
    th = {k: calibrate(v) for k, v in pooled.items() if v}
    lines = []
    for k, v in th.items():
        n_prompts = sum(1 for _, kind, _ in per if kind == k)
        lines.append(f"[{k}] {len(pooled[k])} answers from {n_prompts} prompts (equal weight). Lower bounds on R':")
        lines += [f"  {t:<12} R' ≥ {x:.4f}" for t, x in v.items()]
    lines.append("Per prompt (Starter · Backup · Hidden Gem · Sleeper Pick):")
    for name, kind, sc in per:
        c = {t: 0 for t in TIERS}
        for x in sc["R_prime"].to_list():
            c[next((t for t, v in th[kind].items() if x >= v), "Sleeper Pick")] += 1
        lines.append(f"  {name:<12} {kind:<6} " + " · ".join(str(c[t]) for t in TIERS) + f"   (n={sc.height})")
    if freeze:
        today = dt.date.today().isoformat()
        if groups:  # rewrite only these groups; the rest keep their frozen values and counts
            cur = json.loads(THRESHOLDS_FILE.read_text())
            if unknown := groups - th.keys():
                raise ValueError(f"no calibration prompts for group(s) {sorted(unknown)}")
            for k in groups:
                cur["by_type"][k] = th[k]
                cur["pooled_answers"][k] = len(pooled[k])
                cur.setdefault("group_frozen_at", {})[k] = today
            THRESHOLDS_FILE.write_text(json.dumps(cur, indent=2))
            lines.append(f"Froze {sorted(groups)} to {THRESHOLDS_FILE}; other groups unchanged")
        else:
            THRESHOLDS_FILE.write_text(json.dumps({"by_type": th, "shares": CALIBRATION_SHARES, "prompts_file": path,
                                                   "pooled_answers": {k: len(v) for k, v in pooled.items()},
                                                   "frozen_at": today}, indent=2))
            lines.append(f"Frozen to {THRESHOLDS_FILE}")
    return "\n".join(lines)
