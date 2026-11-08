"""Step 1 of the pipeline (spec §6): prompt filters -> every valid answer, with evidence.

A prompt is structured filters (spec §5):

    {"id": "bears-qb-since-2000", "text": "Name a Bears QB since 2000", "type": "team",
     "filters": {"team": "CHI", "position": "QB", "season_min": 2000}}

Filters
    team            franchise code ("CHI"); AFL seasons count, AAFC seasons don't
    teams_all       ["NYJ", "MIN"]: valid for every listed team
    position        group (QB RB WR TE OL DL LB DB K P LS) or a specific code (CB, FS, ...)
    conference      "AFC" | "NFC" (1970+)
    division        "NFC North", "AFC Central", "Coastal", ...
    league          "NFL" | "AFL"
    season_min/max  inclusive
    award           "mvp" or ["oroy", "mvp"] ("won X and Y"), AP only
    stat_threshold  {"stat": "receiving_yards", "min": 1500} in one regular season (1999+)

Validity (spec §3): QBs need a regular-season start in context (pre-1950: active roster
as a QB). Everyone else needs a counted season in context (player_team_seasons.counted).
Trait prompts: the trait alone qualifies.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import polars as pl

from .sources.wikipedia import AP_FIRST_SEASON

MIN_ANSWERS, MAX_ANSWERS = 25, 300
QB_LIST_FIRST_SEASON = 1950
STATS_FIRST_SEASON = 1999
POSITION_GROUPS = {"QB", "RB", "WR", "TE", "OL", "DL", "LB", "DB", "K", "P", "LS"}
STATS = {  # stat_threshold names -> raw_player_week expression
    "passing_yards": "passing_yards", "passing_tds": "passing_tds",
    "rushing_yards": "rushing_yards", "rushing_tds": "rushing_tds",
    "receiving_yards": "receiving_yards", "receiving_tds": "receiving_tds", "receptions": "receptions",
    "scrimmage_yards": "coalesce(rushing_yards,0) + coalesce(receiving_yards,0)",
    "sacks": "def_sacks", "interceptions": "def_interceptions",
}


@dataclass
class Prompt:
    filters: dict
    text: str = ""
    id: str = ""
    type: str = ""
    subtitle: str = ""

    @classmethod
    def from_json(cls, obj: dict | str) -> "Prompt":
        d = json.loads(obj) if isinstance(obj, str) else obj
        return cls(filters=d.get("filters", {}), text=d.get("text", ""), id=d.get("id", ""),
                   type=d.get("type", ""), subtitle=d.get("subtitle", ""))

    @property
    def is_trait(self) -> bool:
        f = self.filters
        return self.type == "trait" or ("award" in f or "stat_threshold" in f) and not (
            "team" in f or "teams_all" in f or "conference" in f or "division" in f)


@dataclass
class Result:
    prompt: Prompt
    answers: pl.DataFrame
    edge_cases: dict[str, pl.DataFrame] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def n(self) -> int:
        return self.answers.height


# ------------------------------------------------------------------ helpers

def _as_list(v) -> list:
    return v if isinstance(v, list) else [v]


def _position_clause(pos: str, alias: str = "t") -> str:
    p = pos.upper()
    if p in POSITION_GROUPS:
        return f"{alias}.pos_group = '{p}'"
    return f"({alias}.position = '{p}' OR {alias}.depth_chart_position = '{p}')"


def _context_where(f: dict, teams: list[str] | None, alias: str = "t") -> tuple[str, list[str]]:
    """WHERE clause over player_team_seasons for the non-trait filters."""
    w = [f"{alias}.franchise IS NOT NULL", f"coalesce({alias}.league, 'NFL') <> 'AAFC'"]
    warn: list[str] = []
    if teams:
        w.append(f"{alias}.franchise IN ({', '.join(repr(t.upper()) for t in teams)})")
    if "season_min" in f:
        w.append(f"{alias}.season >= {int(f['season_min'])}")
    if "season_max" in f:
        w.append(f"{alias}.season <= {int(f['season_max'])}")
    if "conference" in f:
        w.append(f"{alias}.conference = {f['conference'].upper()!r}")
        if int(f.get("season_min", 0)) < 1970:
            warn.append("conference prompts start in 1970 (§5); earlier seasons have no AFC/NFC")
    if "division" in f:
        w.append(f"{alias}.division = {f['division']!r}")
    if "league" in f:
        w.append(f"{alias}.league = {f['league'].upper()!r}")
    return " AND ".join(w), warn


# ---------------------------------------------------------- build_answers

def build_answers(con, prompt: Prompt) -> Result:
    f = prompt.filters
    unknown = set(f) - {"team", "teams_all", "position", "conference", "division", "league",
                        "season_min", "season_max", "award", "stat_threshold"}
    if unknown:
        raise ValueError(f"unknown filters: {sorted(unknown)}")
    warnings: list[str] = []

    trait_ids = _trait_players(con, f, warnings) if ("award" in f or "stat_threshold" in f) else None
    if prompt.is_trait:
        answers = _trait_answers(con, trait_ids, f)
        return Result(prompt, answers, {}, warnings + _range_warnings(answers.height))

    team_sets = [[t] for t in _as_list(f["teams_all"])] if "teams_all" in f else [
        _as_list(f["team"]) if "team" in f else None]
    pos = f.get("position")
    is_qb = pos is not None and pos.upper() == "QB"

    per_team, edge = [], {}
    for teams in team_sets:
        where, warn = _context_where(f, teams)
        warnings += warn
        df, e = _valid_in_context(con, where, pos, is_qb)
        per_team.append(df)
        for k, v in e.items():
            edge[k] = pl.concat([edge[k], v]).unique() if k in edge else v

    answers = per_team[0]
    if len(per_team) > 1:  # teams_all: valid for every listed team; sum the stints
        keep = set.intersection(*(set(d["player_id"].to_list()) for d in per_team))
        answers = (pl.concat([d.filter(pl.col("player_id").is_in(list(keep))) for d in per_team])
                   .group_by("player_id").agg(
                       pl.col("ctx_seasons").sum(), pl.col("ctx_games").sum(), pl.col("ctx_qb_starts").sum(),
                       pl.col("first_season").min(), pl.col("last_season").max(),
                       pl.col("bases").explode().unique(), pl.col("pre1950_qb").any()))
    if trait_ids is not None:
        answers = answers.filter(pl.col("player_id").is_in(list(trait_ids)))

    answers = _with_career_and_names(con, answers)
    if is_qb:
        edge["qb_source_mismatch"] = _qb_mismatches(con, f, answers)
    return Result(prompt, answers, edge, warnings + _range_warnings(answers.height))


def _valid_in_context(con, where: str, pos: str | None, is_qb: bool) -> tuple[pl.DataFrame, dict]:
    pos_clause = _position_clause(pos) if pos else "true"
    if is_qb:
        # §3: a regular-season start in context; before 1950 (no QB lists) active roster as a QB
        valid_row = f"(t.qb_starts > 0 OR (t.season < {QB_LIST_FIRST_SEASON} AND t.counted AND t.pos_group = 'QB'))"
    else:
        valid_row = f"(t.counted AND {pos_clause})"
    df = con.sql(f"""
        SELECT t.player_id,
               count(DISTINCT t.season) AS ctx_seasons,
               sum(t.games) AS ctx_games,
               sum(t.qb_starts) AS ctx_qb_starts,
               min(t.season) AS first_season, max(t.season) AS last_season,
               list_distinct(list(t.basis)) AS bases,
               bool_or(t.season < {QB_LIST_FIRST_SEASON} AND t.qb_starts = 0) AND {str(is_qb).lower()} AS pre1950_qb
        FROM player_team_seasons t
        WHERE {where} AND {valid_row}
        GROUP BY t.player_id
    """).pl()

    edge = {}
    if is_qb:
        # listed QBs on the roster in context with no start: excluded, worth a look
        edge["qb_no_start"] = con.sql(f"""
            SELECT t.player_id, min(t.season) first_season, max(t.season) last_season, sum(t.games) games
            FROM player_team_seasons t
            WHERE {where} AND t.pos_group = 'QB' AND t.qb_starts = 0 AND t.season >= {QB_LIST_FIRST_SEASON}
              AND t.player_id NOT IN (SELECT player_id FROM player_team_seasons t WHERE {where} AND {valid_row})
            GROUP BY 1""").pl()
    # pre-2002 seasons excluded only because the season-end status can't confirm play (§3)
    edge["unconfirmed_status"] = con.sql(f"""
        SELECT t.player_id, list(t.season ORDER BY t.season) seasons
        FROM player_team_seasons t
        WHERE {where} AND t.unconfirmed_status AND {pos_clause if not is_qb else "t.pos_group = 'QB'"}
          AND t.player_id NOT IN (SELECT player_id FROM player_team_seasons t WHERE {where} AND {valid_row})
        GROUP BY 1""").pl()
    return df, edge


def _with_career_and_names(con, answers: pl.DataFrame) -> pl.DataFrame:
    con.register("_ans", answers.to_arrow())
    out = con.sql("""
        WITH career AS (
            SELECT player_id, count(DISTINCT season) FILTER (WHERE counted) AS career_seasons,
                   sum(games) AS career_games, sum(qb_starts) AS career_qb_starts
            FROM player_team_seasons WHERE player_id IN (SELECT player_id FROM _ans) GROUP BY 1)
        SELECT p.display_name, a.*, c.career_seasons, c.career_games, c.career_qb_starts,
               h.pv24, h.pro_bowls, h.all_pro_1st, h.hof, p.wiki_title
        FROM _ans a JOIN players p USING (player_id)
        LEFT JOIN career c USING (player_id)
        LEFT JOIN player_honors h USING (player_id)
        ORDER BY h.pv24 DESC NULLS LAST, p.display_name
    """).pl()
    con.unregister("_ans")
    return out


# ------------------------------------------------------------------ traits

def _trait_players(con, f: dict, warnings: list[str]) -> set[str]:
    smin, smax = int(f.get("season_min", 0)), int(f.get("season_max", 9999))
    sets = []
    for award in _as_list(f.get("award", [])):
        a = award.lower()
        first = AP_FIRST_SEASON.get(a)
        if first is None:
            warnings.append(f"award {a!r} has no AP start season on record; using every listed season")
        lo = max(smin, first or 0)
        ids = {r[0] for r in con.execute(
            "SELECT DISTINCT player_id FROM player_awards WHERE award = ? AND season BETWEEN ? AND ?",
            [a, lo, smax]).fetchall()}
        undated = con.execute("SELECT count(*) FROM player_awards WHERE award = ? AND season IS NULL", [a]).fetchall()[0][0]
        if undated:
            warnings.append(f"{undated} {a} rows have no season on Wikipedia and were skipped")
        sets.append(ids)
    if st := f.get("stat_threshold"):
        stat = STATS.get(st["stat"])
        if stat is None:
            raise ValueError(f"unknown stat {st['stat']!r}; known: {sorted(STATS)}")
        if smin < STATS_FIRST_SEASON:
            warnings.append(f"season stats start in {STATS_FIRST_SEASON}; earlier seasons can't qualify yet")
        ids = {r[0] for r in con.execute(f"""
            SELECT player_id FROM raw_player_week
            WHERE season_type = 'REG' AND season BETWEEN ? AND ?
            GROUP BY player_id, season HAVING sum({stat}) >= ?""", [max(smin, STATS_FIRST_SEASON), smax, st["min"]]).fetchall()}
        sets.append(ids)
    return set.intersection(*sets) if sets else set()


def _trait_answers(con, ids: set[str], f: dict) -> pl.DataFrame:
    df = pl.DataFrame({"player_id": sorted(ids)}, schema={"player_id": pl.Utf8})
    if "position" in f:
        con.register("_ids", df.to_arrow())
        df = con.sql(f"""SELECT DISTINCT t.player_id FROM player_team_seasons t
                         WHERE t.player_id IN (SELECT player_id FROM _ids) AND {_position_clause(f['position'])}""").pl()
        con.unregister("_ids")
    df = df.with_columns(ctx_seasons=pl.lit(None, pl.Int64), ctx_games=pl.lit(None, pl.Int64),
                         ctx_qb_starts=pl.lit(None, pl.Float64), first_season=pl.lit(None, pl.Int32),
                         last_season=pl.lit(None, pl.Int32), bases=pl.lit(["trait"]), pre1950_qb=pl.lit(False))
    return _with_career_and_names(con, df)


# ------------------------------------------------------------------ checks

def _qb_mismatches(con, f: dict, answers: pl.DataFrame) -> pl.DataFrame:
    """Wikipedia vs nflverse disagreements in the prompt's seasons (§3: flag, never resolve)."""
    teams = _as_list(f.get("teams_all", f.get("team", []))) or None
    w = []
    if teams:
        w.append(f"franchise IN ({', '.join(repr(t.upper()) for t in teams)})")
    if "season_min" in f:
        w.append(f"season >= {int(f['season_min'])}")
    if "season_max" in f:
        w.append(f"season <= {int(f['season_max'])}")
    return con.sql(f"""
        SELECT x.franchise, x.season, coalesce(x.wiki_name, p.display_name) AS name,
               x.wiki_starts, x.nflverse_starts, x.status
        FROM qb_list_crosscheck x LEFT JOIN players p USING (player_id)
        WHERE x.status IN ('count_differs', 'missing_in_wikipedia', 'missing_in_nflverse')
          {"AND " + " AND ".join(w) if w else ""}
        ORDER BY x.season DESC, x.franchise""").pl()


def _range_warnings(n: int) -> list[str]:
    if n < MIN_ANSWERS:
        return [f"HARD STOP: {n} valid answers (< {MIN_ANSWERS}). Widen or drop the prompt."]
    if n > MAX_ANSWERS:
        return [f"{n} valid answers (> {MAX_ANSWERS}): too many to review and alias well."]
    return []
