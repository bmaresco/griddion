"""Step 2 of the pipeline (spec §6-7): valid answers -> F, A, R, R', tier.

All parameters live here, each with the spec section that gives its reason.

"""

from __future__ import annotations

import json
import math

import polars as pl

from .answers import AWARD_KEYS, Prompt, Result, _as_list, _context_where
from .db import DATA_DIR

# §7 Fame
W_PV, W_HONORS, W_CAREER = 0.60, 0.25, 0.15
PV_FLOOR, PV_CEILING = 30, 300_000            # avg monthly views, last 24 months
# share of the lifetime monthly average (since 2015, or since the article's first month) blended
# into the pageview signal; 0 = 24-month average only (§7). Under test, see §11.
PV_LIFETIME_BLEND = 0.0
HONORS_WEIGHTS = {"pro_bowls": 1, "afl_all_star": 1, "all_pro_2nd": 1, "all_pro_1st": 2, "hof": 6}
HONORS_CAP = 20                                # median HOF honors points under HONORS_WEIGHTS
CAREER_CAP = 15                                # seasons
# threshold groups whose F is the pageview signal alone (F = s_pv): award prompts (§7)
PV_ONLY_FAME_GROUPS = {"award"}

# §7 Association / crowding
DELTA = 0.15
# peak = min(1, best qualifying-season production / benchmark); season stats exist from 1999
PEAK_BENCHMARK = {"QB": ("passing_yards", 4000), "RB": ("scrimmage_yards", 1200),
                  "WR": ("scrimmage_yards", 1200), "TE": ("scrimmage_yards", 1200)}
PRE_1950 = 1950  # QBs with a career season before this use seasons share (the §7 one-unit exception)
# prominence = min(1, stint / benchmark) in the prompt's unit: how long he was the guy there (§7)
PROMINENCE_BENCHMARK = {"starts": 32, "games": 32, "seasons": 2}

THRESHOLDS_FILE = DATA_DIR / "tier_thresholds.json"
TIERS = ["Starter", "Backup", "Hidden Gem", "Sleeper Pick"]
CALIBRATION_SHARES = [0.10, 0.35, 0.35, 0.20]  # §7: top 10% / next 35% / next 35% / bottom 20%


# --------------------------------------------------------------------- fame

def fame(con, lifetime_blend: float | None = None) -> pl.DataFrame:
    """F for every player (same for every prompt)."""
    b = PV_LIFETIME_BLEND if lifetime_blend is None else lifetime_blend
    hp = " + ".join(f"{w} * {'hof::INT' if c == 'hof' else c}" for c, w in HONORS_WEIGHTS.items())
    lo, hi = math.log10(PV_FLOOR), math.log10(PV_CEILING)
    return con.sql(f"""
        WITH c AS (SELECT player_id, count(DISTINCT season) FILTER (WHERE counted) AS seasons
                   FROM player_team_seasons GROUP BY 1)
        , pv AS (SELECT h.player_id,
                        {1 - b} * h.pv24 + {b} * coalesce(h.pageviews / nullif(h.pv_months, 0), 0) AS pv
                 FROM player_honors h)
        SELECT h.player_id, pv.pv,
               greatest(0, least(1, (log10(greatest(pv.pv, 1)) - {lo}) / ({hi} - {lo}))) AS s_pv,
               greatest(0, least(1, ({hp}) / {HONORS_CAP})) AS s_honors,
               greatest(0, least(1, coalesce(c.seasons, 0) / {CAREER_CAP})) AS s_career,
               ({hp}) AS honors_points
        FROM player_honors h LEFT JOIN c USING (player_id) JOIN pv USING (player_id)
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


def score_answers(con, result: Result, fame_df: pl.DataFrame | None = None,
                  ykb_exclude: set[str] | None = None) -> tuple[pl.DataFrame, dict]:
    """-> (answers with F, A, R, R', tier), info {unit, notes}."""
    p, a = result.prompt, result.answers
    info: dict = {"notes": []}
    if a.height == 0:
        return a, info
    fame_df = fame(con) if fame_df is None else fame_df
    a = a.join(fame_df, on="player_id", how="left").with_columns(pl.col("F").fill_null(0.0))
    if threshold_kind(p) in PV_ONLY_FAME_GROUPS:
        # §7 (2026-11-08): award prompts use F = s_pv. The award already says why the player
        # is known, so honors and career length double-count and penalize recent winners.
        a = a.with_columns(F=pl.col("s_pv").fill_null(0.0))

    if p.is_trait:
        info["unit"] = "trait"
        a = a.with_columns(share=pl.lit(None, pl.Float64), prominence=pl.lit(None, pl.Float64),
                           tenure=pl.lit(None, pl.Float64), peak=pl.lit(None, pl.Float64), A=pl.lit(1.0))
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

        if "per_team" in a.columns:
            # explode the per-team stints, score each team, keep the best
            t = a.select("player_id", "unit", "career_qb_starts", "career_seasons", "per_team").explode("per_team").unnest("per_team")
            t = t.with_columns(
                stint=pl.when(pl.col("unit") == "starts").then(pl.col("ctx_qb_starts")).otherwise(pl.col("ctx_seasons")),
                career=pl.when(pl.col("unit") == "starts").then(pl.col("career_qb_starts")).otherwise(pl.col("career_seasons")),
                bench=pl.when(pl.col("unit") == "starts").then(PROMINENCE_BENCHMARK["starts"]).otherwise(PROMINENCE_BENCHMARK["seasons"]),
            ).with_columns(
                share_t=(pl.col("stint") / pl.col("career")).fill_nan(None).clip(0, 1),
                prom_t=(pl.col("stint") / pl.col("bench")).clip(0, 1),
            ).with_columns(ten=(pl.col("share_t") * pl.col("prom_t")).sqrt())
            best = t.sort("ten", descending=True).group_by("player_id").first().select(
                "player_id", pl.col("share_t").alias("share"), pl.col("prom_t").alias("prominence"), pl.col("ten").alias("tenure"))
            a = a.join(best, on="player_id", how="left")
        else:
            stint = pl.when(pl.col("unit") == "starts").then(pl.col("ctx_qb_starts")).otherwise(pl.col("ctx_seasons"))
            career = pl.when(pl.col("unit") == "starts").then(pl.col("career_qb_starts")).otherwise(pl.col("career_seasons"))
            bench = pl.when(pl.col("unit") == "starts").then(PROMINENCE_BENCHMARK["starts"]).otherwise(PROMINENCE_BENCHMARK["seasons"])
            a = a.with_columns(share=(stint / career).fill_nan(None).clip(0, 1), prominence=(stint / bench).clip(0, 1))
            a = a.with_columns(tenure=(pl.col("share") * pl.col("prominence")).sqrt())
        a = a.join(_peak(con, p, a), on="player_id", how="left")
        # §7: A = max(sqrt(share x prominence), peak)
        a = a.with_columns(A=pl.max_horizontal(pl.col("tenure").fill_null(0), pl.col("peak").fill_null(0)))

    a = a.with_columns(R=pl.col("F") * pl.col("A"))
    # §7 crowding: n = answers in this prompt with a higher R
    a = a.with_columns(n_higher=(pl.col("R").rank("min", descending=True) - 1).cast(pl.Int64))
    a = a.with_columns(R_prime=pl.col("R") * (1 + pl.col("n_higher")) ** (-DELTA))
    a = a.with_columns(tier=_tier_expr(threshold_kind(p)))
    # §2 YKB Kid: the prompt's override, else the highest-fame Sleeper Pick (else Hidden Gem)
    ykb = p.ykb_kid or default_ykb_kid(a, ykb_exclude)
    if ykb:
        a = a.with_columns(tier=pl.when(pl.col("player_id") == ykb).then(pl.lit("YKB Kid")).otherwise(pl.col("tier")))
    info["ykb_kid"] = ykb
    info["ykb_source"] = "override" if p.ykb_kid else ("default" if ykb else None)
    if p.botched_trick_play:
        # §2: manual only. The prompt names the player; the tier overrides the formula's.
        a = a.with_columns(tier=pl.when(pl.col("player_id") == p.botched_trick_play)
                           .then(pl.lit("Botched Trick Play")).otherwise(pl.col("tier")))
    return a.sort("R_prime", descending=True), info


# -------------------------------------------------------------------- tiers

def load_thresholds() -> dict | None:
    try:
        return json.loads(THRESHOLDS_FILE.read_text())
    except FileNotFoundError:
        return None


def threshold_kind(prompt: Prompt) -> str:
    """§7: four threshold groups. Trait prompts (A = 1) sit on a different scale from the rest,
    award winners are a much more famous pool than stat qualifiers, and college pools (every
    player from a school, no production bar) run deeper than either."""
    if not prompt.is_trait:
        return "other"
    if AWARD_KEYS & prompt.filters.keys():
        return "award"
    return "college" if "college" in prompt.filters else "stat"


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


def default_ykb_kid(scored: pl.DataFrame, exclude: set[str] | None = None) -> str | None:
    """§2: highest-fame Sleeper Pick; if the prompt has none, highest-fame Hidden Gem.
    Players in `exclude` (YKB Kids of the previous 13 drives) are skipped, so a player is
    YKB Kid at most once in any 14-day window."""
    exclude = exclude or set()
    for tier in ("Sleeper Pick", "Hidden Gem"):
        c = scored.filter((pl.col("tier") == tier) & ~pl.col("player_id").is_in(list(exclude)))
        if c.height:
            return c.sort(["F", "player_id"], descending=[True, False])["player_id"][0]
    return None


# -------------------------------------------------------- review helpers (§2, §6)

TOP_HEAVY, BOTTOM_HEAVY = 0.70, 0.85  # share of Starter+Backup / Hidden Gem+Sleeper that triggers a warning


def spread_warnings(scored: pl.DataFrame) -> list[str]:
    """§6 tier-spread warnings. Warnings only: the spread is never forced."""
    n = scored.height
    if n == 0 or scored["tier"].null_count() == n:
        return []
    c = {t: int((scored["tier"] == t).sum()) for t in TIERS}
    w = []
    if c["Starter"] == 0:
        w.append("zero Starters")
    if c["Sleeper Pick"] == 0:
        w.append("zero Sleepers")
    if (c["Starter"] + c["Backup"]) / n > TOP_HEAVY:
        w.append(f"top-heavy ({(c['Starter'] + c['Backup']) / n:.0%} Starter+Backup)")
    if (c["Hidden Gem"] + c["Sleeper Pick"]) / n > BOTTOM_HEAVY:
        w.append(f"bottom-heavy ({(c['Hidden Gem'] + c['Sleeper Pick']) / n:.0%} Hidden Gem+Sleeper)")
    return w
