"""Step 2 of the pipeline (spec §6-7): valid answers -> F, A, R, R', tier.

All parameters live here, each with the spec section that gives its reason.

"""

from __future__ import annotations

import json
import math

import polars as pl

from .answers import Prompt, Result, _as_list, _context_where
from .db import DATA_DIR

# §7 Fame
W_PV, W_HONORS, W_CAREER = 0.60, 0.25, 0.15
PV_FLOOR, PV_CEILING = 30, 300_000            # avg monthly views, last 24 months
HONORS_WEIGHTS = {"pro_bowls": 1, "afl_all_star": 1, "all_pro_2nd": 1, "all_pro_1st": 2, "hof": 6}
HONORS_CAP = 20                                # median HOF honors points under HONORS_WEIGHTS
CAREER_CAP = 15                                # seasons

# §7 Association / crowding
DELTA = 0.15
# peak = min(1, best qualifying-season production / benchmark); season stats exist from 1999
PEAK_BENCHMARK = {"QB": ("passing_yards", 4000), "RB": ("scrimmage_yards", 1200),
                  "WR": ("scrimmage_yards", 1200), "TE": ("scrimmage_yards", 1200)}
PRE_1950 = 1950  # QBs with a career season before this use seasons share (the §7 one-unit exception)

THRESHOLDS_FILE = DATA_DIR / "tier_thresholds.json"
TIERS = ["Starter", "Backup", "Hidden Gem", "Sleeper Pick"]
CALIBRATION_SHARES = [0.10, 0.35, 0.35, 0.20]  # §7: top 10% / next 35% / next 35% / bottom 20%


# --------------------------------------------------------------------- fame

def fame(con) -> pl.DataFrame:
    """F for every player (same for every prompt)."""
    hp = " + ".join(f"{w} * {'hof::INT' if c == 'hof' else c}" for c, w in HONORS_WEIGHTS.items())
    lo, hi = math.log10(PV_FLOOR), math.log10(PV_CEILING)
    return con.sql(f"""
        WITH c AS (SELECT player_id, count(DISTINCT season) FILTER (WHERE counted) AS seasons
                   FROM player_team_seasons GROUP BY 1)
        SELECT h.player_id,
               greatest(0, least(1, (log10(greatest(h.pv24, 1)) - {lo}) / ({hi} - {lo}))) AS s_pv,
               greatest(0, least(1, ({hp}) / {HONORS_CAP})) AS s_honors,
               greatest(0, least(1, coalesce(c.seasons, 0) / {CAREER_CAP})) AS s_career,
               ({hp}) AS honors_points
        FROM player_honors h LEFT JOIN c USING (player_id)
    """).pl().with_columns(
        F=W_PV * pl.col("s_pv") + W_HONORS * pl.col("s_honors") + W_CAREER * pl.col("s_career"))


# -------------------------------------------------------------- association

def _peak(con, prompt: Prompt, answers: pl.DataFrame) -> pl.DataFrame:
    """peak = min(1, best in-context season / benchmark), QB/RB/WR/TE, seasons 1999+ (§7)."""
    f = prompt.filters
    teams = _as_list(f.get("teams_all", f.get("team", []))) or None
    where, _ = _context_where(f, teams)
    qb_col, qb_bench = PEAK_BENCHMARK["QB"]
    sk_col, sk_bench = PEAK_BENCHMARK["RB"]
    con.register("_ids", answers.select("player_id").to_arrow())
    out = con.sql(f"""
        WITH ctx AS (  -- in-context seasons; the season's listed position picks the metric
            SELECT t.player_id, t.season, t.franchise, t.pos_group FROM player_team_seasons t
            WHERE t.player_id IN (SELECT player_id FROM _ids) AND {where} AND t.counted
              AND t.pos_group IN ('QB', 'RB', 'WR', 'TE'))
        SELECT ctx.player_id,
               least(1.0, max(CASE ctx.pos_group WHEN 'QB' THEN p.{qb_col} / {qb_bench}
                                                 ELSE p.{sk_col} / {sk_bench} END)) AS peak
        FROM ctx JOIN player_season_production p
          ON p.player_id = ctx.player_id AND p.season = ctx.season AND p.franchise = ctx.franchise
        GROUP BY 1
    """).pl()
    con.unregister("_ids")
    return out


def score_answers(con, result: Result, fame_df: pl.DataFrame | None = None) -> tuple[pl.DataFrame, dict]:
    """-> (answers with F, A, R, R', tier), info {unit, notes}."""
    p, a = result.prompt, result.answers
    info: dict = {"notes": []}
    if a.height == 0:
        return a, info
    fame_df = fame(con) if fame_df is None else fame_df
    a = a.join(fame_df, on="player_id", how="left").with_columns(pl.col("F").fill_null(0.0))

    if p.is_trait:
        info["unit"] = "trait"
        a = a.with_columns(share=pl.lit(None, pl.Float64), peak=pl.lit(None, pl.Float64), A=pl.lit(1.0))
    else:
        pos = p.filters.get("position")
        is_qb = pos is not None and [x.upper() for x in _as_list(pos)] == ["QB"]
        if is_qb:
            # §7: QB prompts use starts share; the one exception is QBs with any pre-1950 career
            # season (no starts data), who use seasons share
            first = con.sql("SELECT player_id, min(season) AS career_first FROM player_team_seasons "
                            "WHERE counted GROUP BY 1").pl()
            a = a.join(first, on="player_id", how="left").with_columns(
                unit=pl.when(pl.col("career_first") < PRE_1950).then(pl.lit("seasons")).otherwise(pl.lit("starts")))
            n_pre = int((a["unit"] == "seasons").sum())
            info["unit"] = "starts" + (f" ({n_pre} pre-1950 QBs on seasons)" if n_pre else "")
        else:
            a = a.with_columns(unit=pl.lit("seasons"))
            info["unit"] = "seasons"

        def share(num: str, den: str) -> pl.Expr:
            if "per_team" in a.columns:  # two-team: A = max over the teams
                return pl.col("per_team").list.eval(pl.element().struct.field(num)).list.max() / pl.col(den)
            return pl.col(num) / pl.col(den)

        a = a.with_columns(share=pl.when(pl.col("unit") == "starts")
                           .then(share("ctx_qb_starts", "career_qb_starts"))
                           .otherwise(share("ctx_seasons", "career_seasons")))
        a = a.with_columns(pl.col("share").fill_nan(None).clip(0, 1))
        a = a.join(_peak(con, p, a), on="player_id", how="left")
        a = a.with_columns(A=pl.max_horizontal(pl.col("share").fill_null(0).sqrt(), pl.col("peak").fill_null(0)))

    a = a.with_columns(R=pl.col("F") * pl.col("A"))
    # §7 crowding: n = answers in this prompt with a higher R
    a = a.with_columns(n_higher=(pl.col("R").rank("min", descending=True) - 1).cast(pl.Int64))
    a = a.with_columns(R_prime=pl.col("R") * (1 + pl.col("n_higher")) ** (-DELTA))
    a = a.with_columns(tier=_tier_expr(threshold_kind(p)))
    return a.sort("R_prime", descending=True), info


# -------------------------------------------------------------------- tiers

def load_thresholds() -> dict | None:
    try:
        return json.loads(THRESHOLDS_FILE.read_text())
    except FileNotFoundError:
        return None


def threshold_kind(prompt: Prompt) -> str:
    """§7: trait prompts (A = 1) sit on a different scale, so they get their own thresholds."""
    return "trait" if prompt.is_trait else "other"


def _tier_expr(kind: str) -> pl.Expr:
    t = load_thresholds()
    if not t or kind not in t.get("by_type", {}):
        return pl.lit(None, pl.Utf8)
    c = t["by_type"][kind]  # lower bounds on R' for Starter, Backup, Hidden Gem
    return (pl.when(pl.col("R_prime") >= c["Starter"]).then(pl.lit("Starter"))
            .when(pl.col("R_prime") >= c["Backup"]).then(pl.lit("Backup"))
            .when(pl.col("R_prime") >= c["Hidden Gem"]).then(pl.lit("Hidden Gem"))
            .otherwise(pl.lit("Sleeper Pick")))


def calibrate(pooled: list[tuple[float, float]]) -> dict:
    """§7: thresholds at pooled percentiles (top 10% / next 35% / next 35% / bottom 20%).

    `pooled` is (R', weight) pairs; each answer is weighted 1 / its prompt's pool size so
    every calibration prompt counts equally and big pools don't set the thresholds.
    """
    df = pl.DataFrame(pooled, schema={"r": pl.Float64, "w": pl.Float64}, orient="row").sort("r", descending=True)
    df = df.with_columns(cum=pl.col("w").cum_sum() / pl.col("w").sum())
    out, cum = {}, 0.0
    for tier, share in zip(TIERS[:-1], CALIBRATION_SHARES[:-1]):
        cum += share
        # lowest R' still inside the top `cum` share of weight
        out[tier] = float(df.filter(pl.col("cum") <= cum + 1e-12)["r"].min() if df.filter(pl.col("cum") <= cum + 1e-12).height else df["r"].max())
    return out
