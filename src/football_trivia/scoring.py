"""Step 2 of the pipeline (spec §6-7): valid answers -> F, A, R, R', tier.

All parameters live here, each with the spec section that gives its reason.
Honors weights and HONORS_CAP are a proposal pending sign-off (§11).
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
HONORS_WEIGHTS = {"pro_bowls": 1, "afl_all_star": 1, "all_pro_2nd": 1, "all_pro_1st": 2, "hof": 6}  # proposal
HONORS_CAP = 20                                # median HOF honors points under HONORS_WEIGHTS (proposal)
CAREER_CAP = 15                                # seasons

# §7 Association / crowding
DELTA = 0.15
PEAK_POSITIONS = {"QB": "passing_yards", "RB": "scrimmage_yards", "WR": "scrimmage_yards", "TE": "scrimmage_yards"}
PEAK_FIRST_SEASON = 1999

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
    """peak = best in-context season / career-best season, QB/RB/WR/TE only, careers starting 1999+ (§7)."""
    f = prompt.filters
    teams = _as_list(f.get("teams_all", f.get("team", []))) or None
    where, _ = _context_where(f, teams)
    con.register("_ids", answers.select("player_id").to_arrow())
    out = con.sql(f"""
        WITH pos AS (  -- the player's position group in context decides the production metric
            SELECT t.player_id, mode(t.pos_group) AS pos_group, min(t.season) AS ctx_first
            FROM player_team_seasons t WHERE t.player_id IN (SELECT player_id FROM _ids) AND {where} AND t.counted
            GROUP BY 1),
        first AS (SELECT player_id, min(season) AS career_first FROM player_team_seasons
                  WHERE counted AND player_id IN (SELECT player_id FROM _ids) GROUP BY 1),
        prod AS (
            SELECT p.player_id, p.season, p.franchise,
                   CASE pos.pos_group WHEN 'QB' THEN p.passing_yards ELSE p.scrimmage_yards END AS y
            FROM player_season_production p JOIN pos USING (player_id)
            WHERE pos.pos_group IN ('QB', 'RB', 'WR', 'TE')),
        career AS (SELECT player_id, max(y) AS best FROM (SELECT player_id, season, sum(y) y FROM prod GROUP BY 1, 2) GROUP BY 1),
        ctx AS (
            SELECT prod.player_id, max(prod.y) AS best_ctx
            FROM prod JOIN player_team_seasons t
              ON t.player_id = prod.player_id AND t.season = prod.season AND t.franchise = prod.franchise
            WHERE {where}
            GROUP BY 1)
        SELECT pos.player_id,
               CASE WHEN first.career_first >= {PEAK_FIRST_SEASON} AND career.best > 0
                    THEN least(1.0, coalesce(ctx.best_ctx, 0) / career.best) END AS peak
        FROM pos JOIN first USING (player_id) LEFT JOIN career USING (player_id) LEFT JOIN ctx USING (player_id)
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
        # §7 one unit per prompt: QB starts unless any valid answer lacks starts (pre-1950 QBs)
        unit = "starts" if is_qb and not a["pre1950_qb"].any() else "seasons"
        if is_qb and unit == "seasons":
            info["notes"].append("QB prompt scored with seasons: it includes pre-1950 QBs, who have no starts (§7 one-unit rule)")
        info["unit"] = unit
        num, den = ("ctx_qb_starts", "career_qb_starts") if unit == "starts" else ("ctx_seasons", "career_seasons")

        if "per_team" in a.columns:  # two-team: A = max over the teams
            a = a.with_columns(share=pl.col("per_team").list.eval(pl.element().struct.field(num)).list.max() / pl.col(den))
        else:
            a = a.with_columns(share=pl.col(num) / pl.col(den))
        a = a.with_columns(pl.col("share").fill_nan(None).clip(0, 1))
        a = a.join(_peak(con, p, a), on="player_id", how="left")
        a = a.with_columns(A=pl.max_horizontal(pl.col("share").fill_null(0).sqrt(), pl.col("peak").fill_null(0)))

    a = a.with_columns(R=pl.col("F") * pl.col("A"))
    # §7 crowding: n = answers in this prompt with a higher R
    a = a.with_columns(n_higher=(pl.col("R").rank("min", descending=True) - 1).cast(pl.Int64))
    a = a.with_columns(R_prime=pl.col("R") * (1 + pl.col("n_higher")) ** (-DELTA))
    a = a.with_columns(tier=_tier_expr())
    return a.sort("R_prime", descending=True), info


# -------------------------------------------------------------------- tiers

def load_thresholds() -> dict | None:
    try:
        return json.loads(THRESHOLDS_FILE.read_text())
    except FileNotFoundError:
        return None


def _tier_expr() -> pl.Expr:
    t = load_thresholds()
    if not t:
        return pl.lit(None, pl.Utf8)
    c = t["thresholds"]  # lower bounds on R' for Starter, Backup, Hidden Gem
    return (pl.when(pl.col("R_prime") >= c["Starter"]).then(pl.lit("Starter"))
            .when(pl.col("R_prime") >= c["Backup"]).then(pl.lit("Backup"))
            .when(pl.col("R_prime") >= c["Hidden Gem"]).then(pl.lit("Hidden Gem"))
            .otherwise(pl.lit("Sleeper Pick")))


def calibrate(pooled_r_prime: list[float]) -> dict:
    """§7: thresholds at pooled percentiles (top 10% / next 35% / next 35% / bottom 20%)."""
    s = pl.Series(pooled_r_prime)
    cum = 0.0
    out = {}
    for tier, share in zip(TIERS[:-1], CALIBRATION_SHARES[:-1]):
        cum += share
        out[tier] = float(s.quantile(1 - cum, interpolation="linear"))
    return out
