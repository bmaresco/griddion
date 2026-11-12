"""Step 1 of the pipeline (spec §6): prompt filters -> every valid answer, with evidence.

A prompt is structured filters (spec §5):

    {"id": "bears-qb-since-2000", "text": "Name a Bears QB since 2000", "type": "team",
     "filters": {"team": "CHI", "position": "QB", "season_min": 2000}}

Filters
    team            franchise code ("CHI"); AFL seasons count, AAFC seasons don't
    teams_all       ["NYJ", "MIN"]: valid for every listed team
    position        group (QB RB WR TE OL DL LB DB K P LS), a specific code (CB, FS, ...), or a list
    conference      "AFC" | "NFC" (1970+)
    division        "NFC North", "AFC Central", "Coastal", ...
    league          "NFL" | "AFL"
    season_min/max  inclusive
    award           "mvp" or ["oroy", "mvp"] ("won X and Y"), AP only
    award_any       ["oroy", "droy"]: won any of them ("X or Y", the union of winners), AP only
    stat_threshold  {"stat": "receiving_yards", "min": 1500} in one regular season (1999+)
    rookie_stat     {"stat": "receptions", "min": 70}: in the player's first NFL season (1999+)
    game_stat       {"stat": "sacks", "min": 3.5, "games_min": 1}: single regular-season game(s) (1999+)
    window_stat     {"stat": "rushing_tds", "min": 1}: total over season_min..season_max (1999+)
    position_not    group/code or list, e.g. ["RB"] (RB group includes FB): with the three above only
                    The three weekly filters apply position / position_not to each stat row using the
                    player's listed position for that team-season (player_team_seasons), not his current one
    college         "Ohio State" or ["Ohio State", ...]: final college attended (player_college,
                    normalized via colleges.normalize). Trait prompt (A = 1), but validity still
                    needs a counted NFL season (QBs: a start), all eras

Validity (spec §3): QBs need a regular-season start in context (pre-1950: active roster
as a QB). Everyone else needs a counted season in context (player_team_seasons.counted).
Trait prompts: the trait alone qualifies.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import polars as pl

from .sources.ap_awards import ALL_PRO_FIRST_SEASON
from .sources.wikipedia import AP_FIRST_SEASON

TRAIT_KEYS = {"award", "award_any", "stat_threshold", "rookie_stat", "game_stat", "window_stat", "college",
              "hall_of_fame", "all_pro", "pro_bowl", "draft"}
MIN_ANSWERS = 25        # per prompt, hard stop (§6)
TIGHT_MARGIN = 3        # within this many of the minimum: flagged in batch probe and the diff report (§6)
DAY_AVG_MAX = 300       # average across a day's prompts, warning only (§6)
QB_LIST_FIRST_SEASON = 1950
STATS_FIRST_SEASON = 1999
DRAFT_FIRST_SEASON = 1980    # nflverse draft picks start with the 1980 draft (§5)
COLLEGE_FIRST_SEASON = 1974  # nflverse colleges cover ~99.6% of players with a 1974+ season, 0% before (§3)
POSITION_GROUPS = {"QB", "RB", "WR", "TE", "OL", "DL", "LB", "DB", "K", "P", "LS"}
STATS = {  # stat_threshold names -> raw_player_week expression
    "passing_yards": "passing_yards", "passing_tds": "passing_tds",
    "rushing_yards": "rushing_yards", "rushing_tds": "rushing_tds",
    "receiving_yards": "receiving_yards", "receiving_tds": "receiving_tds", "receptions": "receptions",
    "scrimmage_yards": "coalesce(rushing_yards,0) + coalesce(receiving_yards,0)",
    "sacks": "def_sacks", "interceptions": "def_interceptions", "field_goals": "fg_made",
}


@dataclass
class Prompt:
    filters: dict
    text: str = ""
    id: str = ""
    type: str = ""
    subtitle: str = ""
    botched_trick_play: str | None = None  # player_id, set by hand only (§2)
    ykb_kid: str | None = None             # player_id override; default chosen by scoring (§2)

    @classmethod
    def from_json(cls, obj: dict | str) -> "Prompt":
        d = json.loads(obj) if isinstance(obj, str) else obj
        return cls(filters=d.get("filters", {}), text=d.get("text", ""), id=d.get("id", ""),
                   type=d.get("type", ""), subtitle=d.get("subtitle", ""),
                   botched_trick_play=d.get("botched_trick_play"), ykb_kid=d.get("ykb_kid"))

    @property
    def is_trait(self) -> bool:
        f = self.filters
        # pro_bowl reads `team` itself (the selection season's team), so it stays a trait prompt
        return self.type == "trait" or (bool(TRAIT_KEYS & f.keys())) and not (
            ("team" in f and "pro_bowl" not in f) or "teams_all" in f or "conference" in f or "division" in f)


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


def _position_clause(pos: str | list[str], alias: str = "t") -> str:
    """One position (group or code) or a list of them, e.g. ["RB", "WR", "TE"] for skill players."""
    parts = []
    for p in (x.upper() for x in _as_list(pos)):
        if p in POSITION_GROUPS:
            parts.append(f"{alias}.pos_group = '{p}'")
        else:
            parts.append(f"({alias}.position = '{p}' OR {alias}.depth_chart_position = '{p}')")
    return "(" + " OR ".join(parts) + ")"


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


AWARD_KEYS = {"award", "award_any"}  # either makes a prompt an award prompt (§7 award group)
WEEKLY_STAT_KEYS = {"rookie_stat", "game_stat", "window_stat"}  # weekly player stats, 1999+ (§5)
STAT_KEYS = {"stat_threshold"} | WEEKLY_STAT_KEYS
HONOR_KEYS = {"hall_of_fame", "all_pro", "pro_bowl", "draft"}  # §5 honors filters (P7)
# these read `position` themselves (career, honor-season or draft position), not "ever listed there"
OWN_POSITION_KEYS = HONOR_KEYS
# awards whose winners need not have played in the NFL: answers must have a counted season (§3)
PLAY_REQUIRED_AWARDS = {"heisman"}


# ---------------------------------------------------------- build_answers

def build_answers(con, prompt: Prompt) -> Result:
    f = prompt.filters
    unknown = set(f) - {"team", "teams_all", "position", "conference", "division", "league",
                        "season_min", "season_max", "award", "award_any", "stat_threshold", "college",
                        "rookie_stat", "game_stat", "window_stat", "position_not",
                        "hall_of_fame", "all_pro", "pro_bowl", "draft"}
    if unknown:
        raise ValueError(f"unknown filters: {sorted(unknown)}")
    warnings: list[str] = []

    if "position_not" in f and not WEEKLY_STAT_KEYS & f.keys():
        raise ValueError("position_not works only with rookie_stat / game_stat / window_stat")
    if STAT_KEYS & f.keys():
        # §5: stat prompts are 1999+ and must say so, so right pre-1999 answers aren't marked wrong
        if int(f.get("season_min", 0)) < STATS_FIRST_SEASON:
            f = {**f, "season_min": STATS_FIRST_SEASON}
            warnings.append(f"stat prompt: season_min set to {STATS_FIRST_SEASON} (season stats start then)")
        if "1999" not in f"{prompt.text} {prompt.subtitle}" and int(f["season_min"]) == STATS_FIRST_SEASON:
            warnings.append('stat prompt must state the date in its text or subtitle, e.g. "(since 1999)"')
    if "college" in f:
        # §5: college data starts with players active in 1974; the text must say so (like stats/1999)
        if int(f.get("season_min", 0)) < COLLEGE_FIRST_SEASON:
            f = {**f, "season_min": COLLEGE_FIRST_SEASON}
            warnings.append(f"college prompt: season_min set to {COLLEGE_FIRST_SEASON} (college data starts then)")
        if "1974" not in f"{prompt.text} {prompt.subtitle}" and int(f["season_min"]) == COLLEGE_FIRST_SEASON:
            warnings.append('college prompt must state the date in its text or subtitle, e.g. "Since 1974"')
    if "draft" in f:
        # §5: draft data starts with the 1980 draft; season_min/max are draft years; text must say so
        if int(f.get("season_min", 0)) < DRAFT_FIRST_SEASON:
            f = {**f, "season_min": DRAFT_FIRST_SEASON}
            warnings.append(f"draft prompt: season_min set to {DRAFT_FIRST_SEASON} (draft data starts then)")
        if "1980" not in f"{prompt.text} {prompt.subtitle}" and int(f["season_min"]) == DRAFT_FIRST_SEASON:
            warnings.append('draft prompt must state the date in its text or subtitle, e.g. "Since 1980"')
    if f.get("all_pro") and int(f.get("season_min", 0)) < ALL_PRO_FIRST_SEASON:
        # §5: AP All-Pro season pages parse from 1968
        f = {**f, "season_min": ALL_PRO_FIRST_SEASON}
        warnings.append(f"all_pro prompt: season_min set to {ALL_PRO_FIRST_SEASON} (AP team pages parse from then)")
        if "1968" not in f"{prompt.text} {prompt.subtitle}":
            warnings.append('all_pro prompt must state the date in its text or subtitle, e.g. "Since 1968"')
    trait_ids = _trait_players(con, f, warnings) if (AWARD_KEYS | STAT_KEYS | HONOR_KEYS) & f.keys() else None
    if "college" in f:  # §3 college: the trait narrows the pool, validity still needs play
        college_ids = _college_players(con, f["college"], warnings)
        trait_ids = college_ids if trait_ids is None else trait_ids & college_ids
    if prompt.is_trait and "college" not in f:
        answers = _trait_answers(con, trait_ids, f)
        return Result(prompt, answers, {}, warnings + _range_warnings(answers.height))

    team_sets = [[t] for t in _as_list(f["teams_all"])] if "teams_all" in f else [
        _as_list(f["team"]) if "team" in f else None]
    pos = f.get("position")
    is_qb = pos is not None and [p.upper() for p in _as_list(pos)] == ["QB"]

    per_team, edge = [], {}
    for teams in team_sets:
        where, warn = _context_where(f, teams)
        warnings += warn
        df, e = _valid_in_context(con, where, pos, is_qb)
        per_team.append(df.with_columns(team=pl.lit(teams[0] if teams and len(team_sets) > 1 else None, pl.Utf8)))
        for k, v in e.items():
            edge[k] = pl.concat([edge[k], v]).unique() if k in edge else v

    answers = per_team[0].drop("team")
    if len(per_team) > 1:  # teams_all: valid for every listed team; sum the stints
        keep = set.intersection(*(set(d["player_id"].to_list()) for d in per_team))
        answers = (pl.concat([d.filter(pl.col("player_id").is_in(list(keep))) for d in per_team])
                   .group_by("player_id").agg(
                       pl.col("ctx_seasons").sum(), pl.col("ctx_games").sum(), pl.col("ctx_qb_starts").sum(),
                       pl.col("first_season").min(), pl.col("last_season").max(),
                       pl.col("bases").explode().unique(), pl.col("pre1950_qb").any(),
                       # per-team stints for two-team association: A = max(A_team1, A_team2) (§7)
                       pl.struct("team", "ctx_seasons", "ctx_qb_starts", "ctx_games").alias("per_team")))
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

    def winners(award: str) -> set[str]:
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
        return ids

    for award in _as_list(f.get("award", [])):  # "won X and Y": every award
        sets.append(winners(award))
    if "award_any" in f:  # "X or Y": the union of winners
        sets.append(set().union(*(winners(a) for a in _as_list(f["award_any"]))))
    if st := f.get("stat_threshold"):
        stat = STATS.get(st["stat"])
        if stat is None:
            raise ValueError(f"unknown stat {st['stat']!r}; known: {sorted(STATS)}")
        ids = {r[0] for r in con.execute(f"""
            SELECT player_id FROM raw_player_week
            WHERE season_type = 'REG' AND season BETWEEN ? AND ? AND player_id IS NOT NULL
            GROUP BY player_id, season HAVING sum({stat}) >= ?""", [max(smin, STATS_FIRST_SEASON), smax, st["min"]]).fetchall()}
        sets.append(ids)
    for key in WEEKLY_STAT_KEYS & f.keys():
        sets.append(set(weekly_stat_qualifiers(con, f, key)["player_id"].to_list()))
    for key in HONOR_KEYS & f.keys():
        sets.append(set(honor_qualifiers(con, f, key)["player_id"].to_list()))
    if PLAY_REQUIRED_AWARDS & {a.lower() for a in _as_list(f.get("award", [])) + _as_list(f.get("award_any", []))}:
        sets.append(_played(con, f))
    return set.intersection(*sets) if sets else set()


def _played(con, f: dict) -> set[str]:
    """§3 validity for traits that don't imply NFL play (Heisman, draft): a counted regular-season
    season; for a QB-only prompt, a start."""
    qb = "position" in f and [p.upper() for p in _as_list(f["position"])] == ["QB"]
    cond = "qb_starts > 0" if qb else "(counted OR qb_starts > 0)"
    return {r[0] for r in con.execute(
        f"SELECT DISTINCT player_id FROM player_team_seasons WHERE {cond} AND coalesce(league, 'NFL') <> 'AAFC'").fetchall()}


def honor_qualifiers(con, f: dict, key: str) -> pl.DataFrame:
    """Players meeting one honors filter (§5), with evidence for the context line.
    hall_of_fame: player_id, class, groups (inducted position groups), first/last season ·
    all_pro / pro_bowl: player_id, seasons (selection seasons in the window, listed position that
    season; pro_bowl with `team`: the team he played most games for that season) ·
    draft: player_id, season, round, pick, position (draft position; season_min/max = draft years)."""
    smin, smax = int(f.get("season_min", 0)), int(f.get("season_max", 9999))
    pos = f.get("position")
    if key == "hall_of_fame":
        # inducted as a player (coaches/contributors who also played, e.g. Bill Cowher, are out);
        # position = the position(s) he was inducted at, not roster data (which lists pre-modern
        # two-way ends like Don Hutson as DL)
        df = con.sql("""
            SELECT h.player_id, h.class, h.groups, min(t.season) AS first_season, max(t.season) AS last_season
            FROM player_hof h JOIN player_team_seasons t USING (player_id)
            WHERE (t.counted OR t.qb_starts > 0) AND coalesce(t.league, 'NFL') <> 'AAFC'
            GROUP BY ALL""").pl()
        df = df.filter((pl.col("last_season") >= smin) & (pl.col("first_season") <= smax))
        if pos:
            want = [p.upper() for p in _as_list(pos)]
            df = df.filter(pl.col("groups").list.eval(pl.element().is_in(want)).list.any())
        return df
    if key in ("all_pro", "pro_bowl"):
        honor = "all_pro_1st" if key == "all_pro" else "pro_bowl"
        team = f.get("team") if key == "pro_bowl" else None
        teams = [t.upper() for t in _as_list(team)] if team else None
        df = con.sql(f"""
            WITH main AS (  -- the selection season's team: most games that season, then latest listed
                SELECT player_id, season, franchise, pos_group, position, depth_chart_position
                FROM player_team_seasons WHERE (counted OR qb_starts > 0) AND coalesce(league, 'NFL') <> 'AAFC'
                QUALIFY row_number() OVER (PARTITION BY player_id, season ORDER BY games DESC NULLS LAST, franchise) = 1),
            x AS (  -- All-Pro: the AP position slot (edge rusher / flex: his listed group); Pro Bowl: listed group
                SELECT h.player_id, h.season, t.franchise, t.position, t.depth_chart_position,
                       CASE WHEN h.slot IS NULL OR h.slot_group = 'roster' THEN t.pos_group ELSE h.slot_group END AS pos_group,
                       h.slot IS NOT NULL AND h.slot_group IS NULL AS special_teams
                FROM player_honor_seasons h JOIN main t USING (player_id, season)
                WHERE h.honor = '{honor}' AND h.season BETWEEN {smin} AND {smax})
            SELECT * FROM x WHERE true
              {f"AND x.franchise IN ({', '.join(map(repr, teams))})" if teams else ""}
              {"AND NOT x.special_teams AND " + _position_clause(pos, "x") if pos else ""}""").pl()
        return df.group_by("player_id").agg(seasons=pl.col("season").unique().sort())
    if key == "draft":
        spec = f["draft"]
        w = [f"d.season BETWEEN {smin} AND {smax}"]
        if "pick" in spec:
            w.append(f"d.pick = {int(spec['pick'])}")
        if "pick_max" in spec:
            w.append(f"d.pick <= {int(spec['pick_max'])}")
        if "round" in spec:
            w.append(f"d.round = {int(spec['round'])}")
        if pos:
            w.append(_position_clause(pos, "d"))
        df = con.sql(f"""
            WITH x AS (
                SELECT p.player_id, d.season, d.round, d.pick, d.position,
                       coalesce(g.pos_group, d.position) AS pos_group, d.position AS depth_chart_position
                FROM raw_draft_picks d
                JOIN players p ON (d.gsis_id IS NOT NULL AND d.gsis_id = p.gsis_id)
                               OR (d.pfr_player_id IS NOT NULL AND d.pfr_player_id = p.pfr_id)
                LEFT JOIN position_groups g ON g.code = d.position)
            SELECT DISTINCT player_id, season, round, pick, position FROM x d
            WHERE {" AND ".join(w)}""").pl()
        played = _played(con, f)
        return df.filter(pl.col("player_id").is_in(list(played)))
    raise ValueError(key)


def weekly_stat_rows(con, f: dict, stat: str) -> pl.DataFrame:
    """Regular-season stat rows (one per player-game), 1999+, in the prompt's seasons, kept only
    where the player's listed position for that team-season passes position / position_not.
    Columns: player_id, season, week, v."""
    expr = STATS.get(stat)
    if expr is None:
        raise ValueError(f"unknown stat {stat!r}; known: {sorted(STATS)}")
    smin, smax = max(int(f.get("season_min", 0)), STATS_FIRST_SEASON), int(f.get("season_max", 9999))
    mask = []
    if "position" in f:
        mask.append(_position_clause(f["position"], "x"))
    if "position_not" in f:
        mask.append("NOT " + _position_clause(f["position_not"], "x"))
    return con.sql(f"""
        WITH x AS (
            SELECT w.player_id, w.season, w.week, ({expr}) AS v,
                   -- listed position that team-season; the weekly row's own position is the
                   -- player's current one (Cordarrelle Patterson "RB" in 2014), so it's only a fallback
                   coalesce(t.pos_group, g.pos_group) AS pos_group, coalesce(t.position, w.position) AS position,
                   t.depth_chart_position
            FROM raw_player_week w
            LEFT JOIN team_franchises fr ON fr.code = w.team AND w.season BETWEEN fr.season_min AND fr.season_max
            LEFT JOIN player_team_seasons t ON t.player_id = w.player_id AND t.season = w.season AND t.franchise = fr.franchise
            LEFT JOIN position_groups g ON g.code = w.position
            WHERE w.season_type = 'REG' AND w.player_id IS NOT NULL AND w.season BETWEEN {smin} AND {smax})
        SELECT player_id, season, week, v FROM x
        WHERE v IS NOT NULL {"AND " + " AND ".join(mask) if mask else ""}
    """).pl()


def weekly_stat_qualifiers(con, f: dict, key: str) -> pl.DataFrame:
    """Players meeting one weekly filter, with the evidence for the context line (§6).
    rookie_stat: player_id, season, total · game_stat: player_id, games, best, best_season, best_week
    · window_stat: player_id, total, first_season, last_season (seasons that contributed)."""
    spec = f[key]
    rows = weekly_stat_rows(con, f, spec["stat"])
    if key == "game_stat":
        hit = rows.filter(pl.col("v") >= spec["min"]).sort(["v", "season", "week"], descending=[True, False, False])
        return (hit.group_by("player_id", maintain_order=True)
                .agg(games=pl.len(), best=pl.col("v").first(), best_season=pl.col("season").first(),
                     best_week=pl.col("week").first())
                .filter(pl.col("games") >= int(spec.get("games_min", 1))))
    if key == "window_stat":
        return (rows.group_by("player_id").agg(total=pl.col("v").sum(),
                                               first_season=pl.col("season").filter(pl.col("v") > 0).min(),
                                               last_season=pl.col("season").filter(pl.col("v") > 0).max())
                .filter(pl.col("total") >= spec["min"]))
    if key == "rookie_stat":
        # first NFL season = first counted season (a game, or the §3 roster rule), any era; only
        # 1999+ rookies can qualify since weekly stats start then
        first = con.sql("SELECT player_id, min(season) AS season FROM player_team_seasons "
                        "WHERE counted OR qb_starts > 0 GROUP BY 1").pl()
        return (rows.join(first, on=["player_id", "season"]).group_by("player_id", "season")
                .agg(total=pl.col("v").sum()).filter(pl.col("total") >= spec["min"]))
    raise ValueError(key)


def _college_players(con, college, warnings: list[str]) -> set[str]:
    from .colleges import normalize
    from .db import table_exists
    if not table_exists(con, "player_college"):
        raise RuntimeError("no player_college table: run `build` (needs raw_draft_picks from refresh)")
    wanted = [normalize(c) for c in _as_list(college)]
    known = {r[0] for r in con.execute("SELECT DISTINCT college FROM player_college").fetchall()}
    for w in wanted:
        if w not in known:
            warnings.append(f"college {w!r} has no players; check data/college_aliases.csv")
    return {r[0] for r in con.execute(
        f"SELECT player_id FROM player_college WHERE college IN ({', '.join('?' * len(wanted))})", wanted).fetchall()}


def _trait_answers(con, ids: set[str], f: dict) -> pl.DataFrame:
    df = pl.DataFrame({"player_id": sorted(ids)}, schema={"player_id": pl.Utf8})
    if "position" in f and not OWN_POSITION_KEYS & f.keys():
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
    return []
