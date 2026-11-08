"""Derive clean tables from raw_* tables. Pure local; no network.

Tables produced
  players          one row per person; player_id is gsis_id when known, else
                   'pfr:<id>' (matched via Wikidata) or 'nm:<name>|<dob>'
  player_seasons   player x season x franchise x position (roster membership)
  player_games     player x game actually played (1999+; see coverage)
  qb_starts        starting QB per team-game (1999+)
  player_awards    long table: player_id, award, season
  player_honors    pro bowls, all-pro, HOF, award counts, pageviews
  aliases          generated + data/aliases.csv
  coverage         per-season data availability report
"""

from __future__ import annotations

import polars as pl

from .db import DATA_DIR, run, write_table
from .names import norm_name
from .sources.wikipedia import parse_highlights


def _franchise_sql(code: str, season: str) -> str:
    return f"""(SELECT f.franchise FROM team_franchises f
                WHERE f.code = {code} AND {season} BETWEEN f.season_min AND f.season_max LIMIT 1)"""


def build_identity(con, log=print) -> None:
    write_table(con, "team_franchises", pl.read_csv(DATA_DIR / "team_franchises.csv", infer_schema_length=0)
                .with_columns(pl.col("season_min", "season_max").cast(pl.Int32)))
    _identity(con, log)


def build(con, log=print) -> None:
    build_identity(con, log)
    _seasons_games(con, log)
    _honors(con, log)
    _aliases(con, log)
    _coverage(con, log)


# ------------------------------------------------------------------ identity

def _nkey(name_col: str, dob_col: str) -> pl.Expr:
    return pl.col(name_col).map_elements(norm_name, return_dtype=pl.Utf8) + "|" + pl.col(dob_col).cast(pl.Utf8).fill_null("")


def _identity(con, log) -> None:
    log("build: player identity")
    rosters = pl.concat(
        [
            con.sql("SELECT full_name, first_name, last_name, football_name, birth_date, college, gsis_id, pfr_id, season FROM raw_rosters_weekly").pl(),
            con.sql("SELECT full_name, first_name, last_name, NULL::VARCHAR AS football_name, birth_date, college, gsis_id, pfr_id, season FROM raw_rosters").pl(),
        ],
        how="vertical_relaxed",
    ).with_columns(pl.col("birth_date").cast(pl.Utf8).str.slice(0, 10))
    rosters = rosters.with_columns(nkey=_nkey("full_name", "birth_date"))

    players = con.sql("SELECT gsis_id, pfr_id, display_name, first_name, last_name, football_name, birth_date, college_name FROM raw_players").pl()
    players = players.with_columns(pl.col("birth_date").cast(pl.Utf8).str.slice(0, 10)).with_columns(nkey=_nkey("display_name", "birth_date"))

    wd = con.sql("SELECT qid, pfr_id, title, birth_date FROM raw_wikidata WHERE title IS NOT NULL").pl()
    wd = wd.with_columns(
        nkey=pl.col("title").str.replace(r"\s*\(.*\)$", "").map_elements(norm_name, return_dtype=pl.Utf8) + "|" + pl.col("birth_date").fill_null("")
    )

    def unique_map(df: pl.DataFrame, k: str, v: str) -> dict:
        g = df.filter(pl.col(k).is_not_null() & pl.col(v).is_not_null()).group_by(k).agg(pl.col(v).unique())
        return {a: b[0] for a, b in g.iter_rows() if len(b) == 1}

    nkey_to_gsis = unique_map(pl.concat([rosters.select("nkey", "gsis_id"), players.select("nkey", "gsis_id")]), "nkey", "gsis_id")
    gsis_to_pfr = unique_map(pl.concat([players.select("gsis_id", "pfr_id"), rosters.select("gsis_id", "pfr_id")]), "gsis_id", "pfr_id")
    nkey_to_pfr_wd = unique_map(wd.filter(~pl.col("nkey").str.ends_with("|")), "nkey", "pfr_id")
    pfr_to_wd = {r[1]: (r[0], r[2]) for r in wd.iter_rows()}

    def resolve(gsis, pfr, nkey):
        gsis = gsis or nkey_to_gsis.get(nkey)
        pfr = pfr or (gsis_to_pfr.get(gsis) if gsis else None) or nkey_to_pfr_wd.get(nkey)
        pid = gsis or (f"pfr:{pfr}" if pfr else f"nm:{nkey}")
        qid, title = pfr_to_wd.get(pfr, (None, None)) if pfr else (None, None)
        return pid, gsis, pfr, qid, title

    rosters = rosters.with_columns(
        pl.struct("gsis_id", "pfr_id", "nkey").map_elements(
            lambda r: dict(zip(("player_id", "gsis", "pfr", "qid", "wiki_title"), resolve(r["gsis_id"], r["pfr_id"], r["nkey"]))),
            return_dtype=pl.Struct({"player_id": pl.Utf8, "gsis": pl.Utf8, "pfr": pl.Utf8, "qid": pl.Utf8, "wiki_title": pl.Utf8}),
        ).alias("r")
    ).unnest("r")
    # nkey -> player_id map for roster rows (used to key raw_rosters rows below)
    write_table(con, "_roster_ids", rosters.select("nkey", "gsis_id", "season", "player_id").unique())

    # one row per person: latest roster row wins for names
    from_rosters = (
        rosters.sort("season", descending=True)
        .group_by("player_id", maintain_order=True)
        .agg(
            pl.col("gsis").drop_nulls().first().alias("gsis_id"),
            pl.col("pfr").drop_nulls().first().alias("pfr_id"),
            pl.col("full_name").first().alias("display_name"),
            pl.col("first_name").first(),
            pl.col("last_name").first(),
            pl.col("football_name").drop_nulls().first(),
            pl.col("birth_date").drop_nulls().first(),
            pl.col("college").drop_nulls().first(),
            pl.col("qid").drop_nulls().first(),
            pl.col("wiki_title").drop_nulls().first(),
        )
    )
    # players who appear in nflverse players but never on a roster (rare)
    extra = players.filter(~pl.col("gsis_id").is_in(from_rosters["gsis_id"].drop_nulls().implode()) & pl.col("gsis_id").is_not_null())
    extra = extra.with_columns(
        pfr_id=pl.coalesce("pfr_id", pl.col("nkey").replace_strict(nkey_to_pfr_wd, default=None)),
    ).with_columns(
        player_id=pl.col("gsis_id"),
        qid=pl.col("pfr_id").replace_strict({k: v[0] for k, v in pfr_to_wd.items()}, default=None),
        wiki_title=pl.col("pfr_id").replace_strict({k: v[1] for k, v in pfr_to_wd.items()}, default=None),
    ).select(from_rosters.columns[:8] + ["college_name", "qid", "wiki_title"]).rename({"college_name": "college"})
    allp = pl.concat([from_rosters, extra.select(from_rosters.columns)], how="vertical_relaxed")
    write_table(con, "players", allp)
    log(f"  {allp.height} players; {allp['gsis_id'].is_not_null().sum()} gsis, "
        f"{allp['wiki_title'].is_not_null().sum()} with Wikipedia article")


# ------------------------------------------------------------- seasons/games

def _seasons_games(con, log) -> None:
    log("build: player_seasons, player_games, qb_starts")
    # roster rows are keyed via nkey, which is computed in Python (norm_name)
    r = pl.concat(
        [
            con.sql("SELECT season, team, position, depth_chart_position, status, full_name, CAST(birth_date AS VARCHAR) AS birth_date, gsis_id FROM raw_rosters").pl(),
            con.sql("SELECT season, team, position, depth_chart_position, status, full_name, CAST(birth_date AS VARCHAR) AS birth_date, gsis_id FROM raw_rosters_weekly WHERE game_type = 'REG'").pl(),
        ],
        how="vertical_relaxed",
    ).with_columns(pl.col("birth_date").str.slice(0, 10)).with_columns(nkey=_nkey("full_name", "birth_date"))
    ids = con.sql("SELECT * FROM _roster_ids").pl()
    r = r.join(ids, on=["nkey", "gsis_id", "season"], how="left", nulls_equal=True)
    write_table(con, "_roster_rows", r.select("player_id", "season", "team", "position", "depth_chart_position", "status"))

    fr = _franchise_sql
    run(con, f"""
    CREATE OR REPLACE TABLE player_seasons AS
    SELECT player_id, season, team AS team_code, {fr('team', 'season')} AS franchise,
           mode(position) AS position, mode(depth_chart_position) AS depth_chart_position,
           list_distinct(list(status)) AS statuses
    FROM _roster_rows
    WHERE player_id IS NOT NULL
    GROUP BY ALL
    """)

    # games actually played: any recorded stat (1999+), any snap (2012+), or QB start (1999+)
    run(con, f"""
    CREATE OR REPLACE TABLE qb_starts AS
    SELECT game_id, season, week, game_type, home_team AS team_code, {fr('home_team', 'season')} AS franchise,
           home_qb_id AS player_id
    FROM raw_schedules WHERE home_qb_id IS NOT NULL AND home_score IS NOT NULL
    UNION ALL
    SELECT game_id, season, week, game_type, away_team, {fr('away_team', 'season')}, away_qb_id
    FROM raw_schedules WHERE away_qb_id IS NOT NULL AND away_score IS NOT NULL
    """)

    run(con, f"""
    CREATE OR REPLACE TABLE player_games AS
    WITH sched AS (SELECT game_id, season, week, game_type FROM raw_schedules),
    pfr_map AS (SELECT pfr_id, any_value(player_id) AS player_id FROM players WHERE pfr_id IS NOT NULL GROUP BY pfr_id HAVING count(*) = 1),
    src AS (
        SELECT player_id, game_id, team AS team_code, 'stats' AS source
        FROM raw_player_week WHERE game_id IS NOT NULL
        UNION ALL
        SELECT m.player_id, s.game_id, s.team, 'snaps'
        FROM raw_snap_counts s JOIN pfr_map m ON m.pfr_id = s.pfr_player_id
        WHERE coalesce(s.offense_snaps, 0) + coalesce(s.defense_snaps, 0) + coalesce(s.st_snaps, 0) > 0
        UNION ALL
        SELECT player_id, game_id, team_code, 'qb_start' FROM qb_starts
    )
    SELECT src.player_id, src.game_id, sched.season, sched.week, sched.game_type,
           any_value(src.team_code) AS team_code,
           {fr('any_value(src.team_code)', 'sched.season')} AS franchise,
           list_distinct(list(src.source)) AS sources
    FROM src JOIN sched USING (game_id)
    GROUP BY src.player_id, src.game_id, sched.season, sched.week, sched.game_type
    """)
    unmapped = con.execute("""
        SELECT count(DISTINCT pfr_player_id) FROM raw_snap_counts
        WHERE pfr_player_id NOT IN (SELECT pfr_id FROM players WHERE pfr_id IS NOT NULL)""").fetchall()[0][0]
    n = con.execute("SELECT count(*), count(DISTINCT player_id) FROM player_games").fetchall()[0]
    log(f"  player_games: {n[0]} rows, {n[1]} players; {unmapped} snap-count PFR ids unmapped to a player")


# ------------------------------------------------------------------- honors

def _honors(con, log) -> None:
    log("build: honors")
    pages = con.sql("""
        SELECT p.player_id, w.highlights, w.is_hof
        FROM players p JOIN raw_wiki_pages w ON w.title = p.wiki_title""").pl()
    awards, rows = [], []
    for pid, text, hof in pages.iter_rows():
        h = parse_highlights(text)
        rows.append({"player_id": pid, "pro_bowls": h["pro_bowls"], "all_pro_1st": h["all_pro_1st"],
                     "all_pro_2nd": h["all_pro_2nd"], "afl_all_star": h["afl_all_star"], "hof": bool(hof),
                     "has_highlights": text is not None})
        awards.extend({"player_id": pid, "award": k, "season": s} for k, s in h["awards"])
    write_table(con, "player_awards", pl.DataFrame(awards, schema={"player_id": pl.Utf8, "award": pl.Utf8, "season": pl.Int32}))
    write_table(con, "_honors", pl.DataFrame(rows))
    run(con, """
    CREATE OR REPLACE TABLE player_honors AS
    WITH pv AS (
        SELECT title, sum(views) AS pageviews, min(month) AS pv_first_month, count(*) AS pv_months
        FROM raw_pageviews GROUP BY title
    )
    SELECT p.player_id, p.wiki_title,
           coalesce(h.pro_bowls, 0) AS pro_bowls, coalesce(h.all_pro_1st, 0) AS all_pro_1st,
           coalesce(h.all_pro_2nd, 0) AS all_pro_2nd, coalesce(h.afl_all_star, 0) AS afl_all_star,
           coalesce(h.hof, false) AS hof, coalesce(h.has_highlights, false) AS has_highlights,
           coalesce(pv.pageviews, 0) AS pageviews, pv.pv_first_month, pv.pv_months
    FROM players p
    LEFT JOIN _honors h USING (player_id)
    LEFT JOIN pv ON pv.title = p.wiki_title
    """)
    # sanity: each major award should have ~1 winner per season
    bad = con.execute("""
        WITH c AS (SELECT award, season, count(*) n FROM player_awards
                   WHERE award IN ('mvp','opoy','dpoy','oroy','droy') AND season IS NOT NULL GROUP BY ALL)
        SELECT award, season, n FROM c WHERE n > 2 ORDER BY award, season""").fetchall()
    log(f"  {pages.height} wiki pages parsed; {len(awards)} award rows; seasons with >2 winners: {bad[:10]}")


# ------------------------------------------------------------------ aliases

def _aliases(con, log) -> None:
    log("build: aliases")
    p = con.sql("SELECT player_id, display_name, first_name, last_name, football_name FROM players").pl()
    rows = []
    for pid, disp, first, last, fb in p.iter_rows():
        cands = {
            (disp, "display"),
            (f"{first} {last}" if first and last else None, "first_last"),
            (f"{fb} {last}" if fb and last else None, "common_first_last"),
            (last, "last_only"),  # matcher only uses this when unambiguous within a prompt
        }
        for a, kind in cands:
            if a and a.strip():
                rows.append((pid, a.strip(), norm_name(a), kind))
    manual = pl.read_csv(DATA_DIR / "aliases.csv", infer_schema_length=0)
    for pid, alias, _ in manual.iter_rows():
        rows.append((pid, alias, norm_name(alias), "manual"))
    df = pl.DataFrame(rows, schema={"player_id": pl.Utf8, "alias": pl.Utf8, "alias_norm": pl.Utf8, "kind": pl.Utf8}, orient="row").unique()
    write_table(con, "aliases", df)
    log(f"  {df.height} aliases ({manual.height} manual)")


# ----------------------------------------------------------------- coverage

def _coverage(con, log) -> None:
    run(con, """
    CREATE OR REPLACE TABLE coverage AS
    WITH ps AS (SELECT season, count(DISTINCT player_id) roster_players,
                       count(DISTINCT player_id) FILTER (WHERE NOT starts_with(player_id, 'nm:')) id_matched
                FROM player_seasons GROUP BY season),
    g AS (SELECT season, count(DISTINCT player_id) players_with_games,
                 count(DISTINCT player_id) FILTER (WHERE list_contains(sources, 'snaps')) players_with_snaps
          FROM player_games WHERE game_type = 'REG' GROUP BY season),
    q AS (SELECT season, count(*) qb_start_rows FROM qb_starts WHERE game_type = 'REG' GROUP BY season),
    w AS (SELECT s.season, avg((h.wiki_title IS NOT NULL)::INT) pct_wiki, avg((h.pageviews > 0)::INT) pct_pageviews
          FROM (SELECT DISTINCT season, player_id FROM player_seasons) s JOIN player_honors h USING (player_id) GROUP BY s.season)
    SELECT ps.season, roster_players, round(id_matched / roster_players, 3) pct_id_matched,
           coalesce(players_with_games, 0) players_with_games, coalesce(players_with_snaps, 0) players_with_snaps,
           coalesce(qb_start_rows, 0) qb_start_rows, round(pct_wiki, 3) pct_wiki, round(pct_pageviews, 3) pct_pageviews
    FROM ps LEFT JOIN g USING (season) LEFT JOIN q USING (season) LEFT JOIN w USING (season)
    ORDER BY season
    """)
