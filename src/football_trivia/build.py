"""Derive clean tables from raw_* tables. Pure local; no network.

Tables produced
  players          one row per person; player_id is gsis_id when known, else
                   'pfr:<id>' (matched via Wikidata) or 'nm:<name>|<dob>'
  player_seasons   player x season x franchise x position (roster membership)
  player_games     player x game actually played (1999+; see coverage)
  qb_starts        starting QB per team-game (1999+)
  player_awards    long table: player_id, award, season
  player_honors    pro bowls, all-pro, HOF, award counts, pageviews
  player_honor_seasons  player x Pro Bowl / All-Pro season (infobox years)
  player_hof       HOF inductees inducted as players: class, inducted position(s) and groups
  aliases          generated from nflverse name fields
  coverage         per-season data availability report
"""

from __future__ import annotations

import re

import polars as pl

from .db import DATA_DIR, run, table_exists, write_table
from .names import norm_name
from .sources import ap_awards, qb_lists
from .sources.wikipedia import honor_seasons, parse_highlights


def _franchise_sql(code: str, season: str) -> str:
    return f"""(SELECT f.franchise FROM team_franchises f
                WHERE f.code = {code} AND {season} BETWEEN f.season_min AND f.season_max LIMIT 1)"""


def build_identity(con, log=print) -> None:
    write_table(con, "team_franchises", pl.read_csv(DATA_DIR / "team_franchises.csv", infer_schema_length=0)
                .with_columns(pl.col("season_min", "season_max").cast(pl.Int32)))
    write_table(con, "team_alignment", pl.read_csv(DATA_DIR / "team_alignment.csv", infer_schema_length=0, comment_prefix="#")
                .with_columns(pl.col("season_min", "season_max").cast(pl.Int32)))
    _identity(con, log)


def build(con, log=print) -> None:
    build_identity(con, log)
    _seasons_games(con, log)
    _honors(con, log)
    log("build: QB lists")
    qb_lists.build(con, log)
    _team_seasons(con, log)
    _production(con, log)
    _aliases(con, log)
    build_colleges(con, log)
    _coverage(con, log)


# ------------------------------------------------------------------ identity

def _nkey(name_col: str, dob_col: str) -> pl.Expr:
    return pl.col(name_col).map_elements(norm_name, return_dtype=pl.Utf8) + "|" + pl.col(dob_col).cast(pl.Utf8).fill_null("")


def _last_key(nkey: str | None) -> str | None:
    """'billy wade|1930-10-04' -> 'wade|1930-10-04' (None without a name or DOB)."""
    if not nkey or "|" not in nkey:
        return None
    name, dob = nkey.rsplit("|", 1)
    return f"{name.split()[-1]}|{dob}" if name and dob else None


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
    # fallback for nickname variants ("Billy Wade" vs "Bill Wade"): last name + birth date, if unique
    wd = wd.with_columns(lkey=pl.col("nkey").map_elements(_last_key, return_dtype=pl.Utf8))
    lkey_to_pfr_wd = unique_map(wd, "lkey", "pfr_id")
    # ...and only when exactly one person on the nflverse side has that last name + DOB
    people = pl.concat([rosters.select("nkey"), players.select("nkey")]).unique()
    people = people.with_columns(lkey=pl.col("nkey").map_elements(_last_key, return_dtype=pl.Utf8))
    shared = set(people.group_by("lkey").len().filter(pl.col("len") > 1)["lkey"].drop_nulls().to_list())
    lkey_to_pfr_wd = {k: v for k, v in lkey_to_pfr_wd.items() if k not in shared}
    pfr_to_wd = {r[1]: (r[0], r[2]) for r in wd.iter_rows()}

    def resolve(gsis, pfr, nkey):
        gsis = gsis or nkey_to_gsis.get(nkey)
        pfr = (pfr or (gsis_to_pfr.get(gsis) if gsis else None) or nkey_to_pfr_wd.get(nkey)
               or lkey_to_pfr_wd.get(_last_key(nkey)))
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
    # several players claiming one article (bad pfr ids upstream, e.g. a son given his
    # father's id): keep the one whose DOB matches Wikidata, unlink the rest
    wd_dob = {r[1]: r[3] for r in wd.select("qid", "pfr_id", "title", "birth_date").iter_rows()}
    dup = allp.filter(pl.col("wiki_title").is_not_null()).group_by("wiki_title").len().filter(pl.col("len") > 1)["wiki_title"]
    keep = allp.filter(pl.col("wiki_title").is_in(dup.implode())).filter(
        pl.col("birth_date") == pl.col("pfr_id").replace_strict(wd_dob, default=None))
    keep = keep.group_by("wiki_title").agg(pl.col("player_id")).filter(pl.col("player_id").list.len() == 1)
    keep_ids = set(keep["player_id"].list.first().to_list())
    unlink = pl.col("wiki_title").is_in(dup.implode()) & ~pl.col("player_id").is_in(list(keep_ids))
    allp = allp.with_columns(
        **{c: pl.when(unlink).then(None).otherwise(pl.col(c)) for c in ("pfr_id", "qid", "wiki_title")})
    log(f"  {dup.len()} articles claimed by several players; {len(keep_ids)} resolved by DOB, rest unlinked")
    write_table(con, "players", allp)
    log(f"  {allp.height} players; {allp['gsis_id'].is_not_null().sum()} gsis, "
        f"{allp['wiki_title'].is_not_null().sum()} with Wikipedia article")


# ------------------------------------------------------------- seasons/games

def _seasons_games(con, log) -> None:
    log("build: player_seasons, player_games, qb_starts")
    # roster rows are keyed via nkey, which is computed in Python (norm_name)
    r = pl.concat(
        [
            con.sql("SELECT season, NULL::INT AS week, team, position, depth_chart_position, status, full_name, CAST(birth_date AS VARCHAR) AS birth_date, gsis_id FROM raw_rosters").pl(),
            con.sql("SELECT season, week, team, position, depth_chart_position, status, full_name, CAST(birth_date AS VARCHAR) AS birth_date, gsis_id FROM raw_rosters_weekly WHERE game_type = 'REG'").pl(),
        ],
        how="vertical_relaxed",
    ).with_columns(pl.col("birth_date").str.slice(0, 10)).with_columns(nkey=_nkey("full_name", "birth_date"))
    ids = con.sql("SELECT * FROM _roster_ids").pl()
    r = r.join(ids, on=["nkey", "gsis_id", "season"], how="left", nulls_equal=True)
    write_table(con, "_roster_rows", r.select("player_id", "season", "week", "team", "position", "depth_chart_position", "status"))

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
    -- nflverse weekly stats sometimes swap team/opponent (mostly 2001-02, e.g. Renaldo Wynn's
    -- JAX road games filed under the home team). If the row's team isn't one the player was
    -- rostered with that season but the opponent is, use the opponent.
    rostered AS (SELECT DISTINCT player_id, season, {fr('team', 'season')} AS franchise
                 FROM _roster_rows WHERE player_id IS NOT NULL),
    wk AS (
        SELECT w.player_id, w.game_id, w.season, w.team, w.opponent_team,
               {fr('w.team', 'w.season')} AS fr_team,
               {fr('w.opponent_team', 'w.season')} AS fr_opp
        FROM raw_player_week w WHERE w.game_id IS NOT NULL),
    src AS (
        SELECT wk.player_id, wk.game_id,
               CASE WHEN rt.player_id IS NULL AND ro.player_id IS NOT NULL THEN wk.opponent_team ELSE wk.team END AS team_code,
               'stats' AS source
        FROM wk
        LEFT JOIN rostered rt ON rt.player_id = wk.player_id AND rt.season = wk.season AND rt.franchise = wk.fr_team
        LEFT JOIN rostered ro ON ro.player_id = wk.player_id AND ro.season = wk.season AND ro.franchise = wk.fr_opp
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
    awards, rows, honor_rows = [], [], []
    for pid, text, hof in pages.iter_rows():
        h = parse_highlights(text)
        honor_rows.extend({"player_id": pid, "honor": k, "season": s} for k, s in honor_seasons(text))
        rows.append({"player_id": pid, "pro_bowls": h["pro_bowls"], "all_pro_1st": h["all_pro_1st"],
                     "all_pro_2nd": h["all_pro_2nd"], "afl_all_star": h["afl_all_star"], "hof": bool(hof),
                     "has_highlights": text is not None})
        awards.extend({"player_id": pid, "award": k, "season": s} for k, s in h["awards"])
    infobox = pl.DataFrame(awards, schema={"player_id": pl.Utf8, "award": pl.Utf8, "season": pl.Int32})
    # the six AP awards, Super Bowl MVP and the Heisman come from their list pages (spec §5: AP
    # only); infoboxes keep the rest
    ap = ap_awards.parse_all(con)
    redirects = dict(con.execute("SELECT link_title, canonical_title FROM raw_ap_award_redirects").fetchall())
    by_title = dict(con.execute("SELECT wiki_title, player_id FROM players WHERE wiki_title IS NOT NULL").fetchall())
    ap = ap.with_columns(player_id=pl.col("wiki_title").map_elements(
        lambda t: by_title.get(redirects.get(t, t)) or by_title.get(t), return_dtype=pl.Utf8))
    unmatched = ap.filter(pl.col("player_id").is_null())
    if unmatched.height:
        log(f"  AP winners not matched to a player: {unmatched.select('award', 'season', 'name').rows()}")
    awards_df = pl.concat([
        infobox.filter(~pl.col("award").is_in(list(ap_awards.PAGES) + ["roy"])).with_columns(source=pl.lit("infobox")),
        ap.filter(pl.col("player_id").is_not_null()).select("player_id", "award", "season").with_columns(source=pl.lit("list")),
    ])
    write_table(con, "player_awards", awards_df)
    # Hall of Fame inductees inducted as players, with the position(s) they were inducted at (§5)
    # fallback for players whose article never linked in identity (old-timers with no Wikidata
    # crosswalk): the link title equals the display name of exactly one player with no article
    unlinked: dict[str, list[str]] = {}
    for pid, name in con.execute("SELECT player_id, display_name FROM players WHERE wiki_title IS NULL").fetchall():
        unlinked.setdefault(norm_name(name), []).append(pid)

    def hof_pid(t: str) -> str | None:
        hit = by_title.get(redirects.get(t, t)) or by_title.get(t)
        if hit:
            return hit
        c = unlinked.get(norm_name(re.sub(r"\s*\(.*?\)", "", redirects.get(t, t))), [])
        return c[0] if len(c) == 1 else None
    hof = ap_awards.parse_hof(con).with_columns(
        player_id=pl.col("wiki_title").map_elements(hof_pid, return_dtype=pl.Utf8),
        groups=pl.col("position").map_elements(ap_awards.hof_groups, return_dtype=pl.List(pl.Utf8)))
    players_hof = (hof.filter(pl.col("player_id").is_not_null()).group_by("player_id")
                   .agg(pl.col("class").min(), pl.col("position").unique().sort(), pl.col("groups").list.explode(keep_nulls=False, empty_as_null=False).unique().sort())
                   .filter(pl.col("groups").list.len() > 0))
    unmatched_hof = hof.filter(pl.col("player_id").is_null() & (pl.col("groups").list.len() > 0))["name"].unique().sort().to_list()
    log(f"  HOF: {players_hof.height} inducted as players and matched; unmatched players: {unmatched_hof}")
    write_table(con, "player_hof", players_hof)
    # per-season honors for the filters (§5): Pro Bowl from infobox years; first-team All-Pro from
    # the AP season pages (AP only, with the position slot, so a special-teams pick never counts as
    # an LB/DB/WR All-Pro). Infobox All-Pro rows are kept as all_pro_*_infobox for comparison only.
    ib = pl.DataFrame(honor_rows, schema={"player_id": pl.Utf8, "honor": pl.Utf8, "season": pl.Int32}).with_columns(
        honor=pl.when(pl.col("honor").str.starts_with("all_pro")).then(pl.col("honor") + "_infobox").otherwise(pl.col("honor")),
        slot=pl.lit(None, pl.Utf8), slot_group=pl.lit(None, pl.Utf8))
    ap_teams = ap_awards.parse_all_pro(con).with_columns(
        player_id=pl.col("wiki_title").map_elements(hof_pid, return_dtype=pl.Utf8),
        slot_group=pl.col("slot").map_elements(ap_awards.all_pro_group, return_dtype=pl.Utf8))
    miss = ap_teams.filter(pl.col("player_id").is_null())
    log(f"  AP All-Pro first team: {ap_teams.height} selections, {ap_teams['season'].n_unique()} seasons; "
        f"unmatched {miss.height}: {miss.select('season', 'name').rows()[:15]}")
    write_table(con, "player_honor_seasons", pl.concat([
        ib, ap_teams.filter(pl.col("player_id").is_not_null())
              .select("player_id", pl.lit("all_pro_1st").alias("honor"), "season", "slot", "slot_group")]).unique())
    write_table(con, "_honors", pl.DataFrame(rows))
    run(con, """
    CREATE OR REPLACE TABLE player_honors AS
    WITH pv AS (
        SELECT title, sum(views) AS pageviews, min(month) AS pv_first_month, count(*) AS pv_months
        FROM raw_pageviews GROUP BY title
    ),
    win AS (SELECT max(month) - INTERVAL 23 MONTH AS start FROM raw_pageviews),
    pv24 AS (
        SELECT title, sum(views) / 24.0 AS pv24, sum(moved) AS pv24_from_former_titles
        FROM (
            -- current title: only months since the article moved onto it (else it was another page)
            SELECT v.title, v.views, 0 AS moved FROM raw_pageviews v, win
            LEFT JOIN raw_title_segments c ON c.title = v.title AND c.segment_title = v.title AND c.left_at IS NULL
            WHERE v.month >= win.start AND (c.arrived_at IS NULL OR v.month >= date_trunc('month', c.arrived_at))
            UNION ALL
            SELECT title, views, views FROM raw_pageviews_moved, win WHERE month >= win.start
        ) GROUP BY title
    )
    SELECT p.player_id, p.wiki_title,
           coalesce(h.pro_bowls, 0) AS pro_bowls, coalesce(h.all_pro_1st, 0) AS all_pro_1st,
           coalesce(h.all_pro_2nd, 0) AS all_pro_2nd, coalesce(h.afl_all_star, 0) AS afl_all_star,
           coalesce(h.hof, false) AS hof, coalesce(h.has_highlights, false) AS has_highlights,
           coalesce(pv.pageviews, 0) AS pageviews, pv.pv_first_month, pv.pv_months,
           coalesce(pv24.pv24, 0) AS pv24, coalesce(pv24.pv24_from_former_titles, 0) AS pv24_from_former_titles
    FROM players p
    LEFT JOIN _honors h USING (player_id)
    LEFT JOIN pv ON pv.title = p.wiki_title
    LEFT JOIN pv24 ON pv24.title = p.wiki_title
    """)
    # sanity: each major award should have ~1 winner per season
    bad = con.execute("""
        WITH c AS (SELECT award, season, count(*) n FROM player_awards
                   WHERE award IN ('mvp','opoy','dpoy','oroy','droy') AND season IS NOT NULL GROUP BY ALL)
        SELECT award, season, n FROM c WHERE n > 2 ORDER BY award, season""").fetchall()
    log(f"  {pages.height} wiki pages parsed; {awards_df.height} award rows ({ap.height} from AP pages); seasons with >2 winners: {bad[:10]}")


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
    df = pl.DataFrame(rows, schema={"player_id": pl.Utf8, "alias": pl.Utf8, "alias_norm": pl.Utf8, "kind": pl.Utf8}, orient="row").unique()
    write_table(con, "aliases", df)
    log(f"  {df.height} aliases")


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


# ---------------------------------------------------------- team seasons (§3)

# roster position code -> group; filters accept a group or a specific code
POSITION_GROUPS = {
    "QB": "QB",
    "RB": "RB", "FB": "RB", "HB": "RB", "TB": "RB", "WB": "RB", "BB": "RB",
    "WR": "WR", "TE": "TE",
    "OL": "OL", "T": "OL", "G": "OL", "C": "OL", "OT": "OL", "OG": "OL",
    "DL": "DL", "DE": "DL", "DT": "DL", "NT": "DL", "DG": "DL",
    "LB": "LB", "OLB": "LB", "ILB": "LB", "MLB": "LB",
    "DB": "DB", "CB": "DB", "S": "DB", "SS": "DB", "FS": "DB", "SAF": "DB",
    "K": "K", "P": "P", "LS": "LS",
}
ACTIVE = "('ACT')"
# §3: the current season's Wikipedia rows lag in season, so its QB starts come from nflverse.
# Set to False once the current season's Wikipedia rows are complete (the mismatch flag stays on).
QB_CURRENT_SEASON_FROM_NFLVERSE = True
ACTIVE_PRE_1989 = "('ACT', 'TRC', 'TRD', 'TRT')"  # no practice squads before 1989 (§3)
UNCONFIRMED = "('RES', 'PUP', 'RSN', 'CUT', 'INA', 'NWT', 'SUS', 'EXE', 'TRC', 'TRD', 'TRT')"


def _team_seasons(con, log) -> None:
    """player_team_seasons: one row per player x franchise x season with the §3 verdict.

    counted  - the season counts (validity for non-QBs, seasons unit for association)
    basis    - qb_start | games | active_week | season_status | none
    qb_starts- regular-season starts (Wikipedia primary; nflverse for GB/LA 1999+)
    unconfirmed_status - excluded pre-2002 season whose status (RES/CUT/...) can't say if he played
    """
    log("build: player_team_seasons")
    groups = pl.DataFrame({"code": list(POSITION_GROUPS), "pos_group": list(POSITION_GROUPS.values())})
    write_table(con, "position_groups", groups)

    # QB starts per §3: Wikipedia every season, except GB/LA from 1999 and (while its rows lag)
    # the current season, which come from nflverse
    current = con.execute("SELECT max(season) FROM raw_schedules WHERE home_score IS NOT NULL").fetchall()[0][0]
    cur = current if QB_CURRENT_SEASON_FROM_NFLVERSE else -1
    run(con, f"""
    CREATE OR REPLACE TABLE qb_starts_final AS
    SELECT player_id, franchise, season, starts, 'wikipedia' AS source, basis
    FROM (SELECT player_id, franchise, season, sum(starts) starts, string_agg(DISTINCT basis, ',') basis
          FROM qb_list_starts WHERE player_id IS NOT NULL GROUP BY ALL)
    WHERE NOT (franchise IN ('GB', 'LA') AND season >= 1999) AND season <> {cur}
    UNION ALL
    SELECT player_id, franchise, season, count(*)::DOUBLE, 'nflverse', 'games'
    FROM qb_starts WHERE game_type = 'REG' AND ((franchise IN ('GB', 'LA') AND season >= 1999) OR season = {cur})
    GROUP BY ALL
    """)

    run(con, f"""
    CREATE OR REPLACE TABLE player_team_seasons AS
    WITH rr AS (
        SELECT r.*, {_franchise_sql('r.team', 'r.season')} AS franchise FROM _roster_rows r WHERE player_id IS NOT NULL
    ),
    roster AS (
        SELECT player_id, franchise, season,
               mode(position) FILTER (WHERE week IS NULL) AS season_position,
               mode(position) AS any_position,
               mode(depth_chart_position) AS depth_chart_position,
               bool_or(week IS NOT NULL AND status IN {ACTIVE}) AS active_week,
               bool_or(week IS NOT NULL) AS has_weekly,
               bool_or(week IS NULL AND status IN {ACTIVE}) OR
                 (season < 1989 AND bool_or(week IS NULL AND status IN {ACTIVE_PRE_1989})) AS active_season_status,
               list_distinct(list(status) FILTER (WHERE week IS NULL)) AS season_statuses
        FROM rr WHERE franchise IS NOT NULL GROUP BY player_id, franchise, season
    ),
    career_pos AS (  -- fallback for mid-season signings missing from that roster, and blank old rows
        SELECT r.player_id, mode(coalesce(pg.pos_group, dg.pos_group)) AS pos_group
        FROM rr r LEFT JOIN position_groups pg ON pg.code = r.position
        LEFT JOIN position_groups dg ON dg.code = r.depth_chart_position
        GROUP BY r.player_id
    ),
    g AS (
        SELECT player_id, franchise, season, count(*) AS games
        FROM player_games WHERE game_type = 'REG' AND franchise IS NOT NULL GROUP BY ALL
    ),
    q AS (SELECT player_id, franchise, season, sum(starts) AS qb_starts, any_value(source) AS qb_source,
                 any_value(basis) AS qb_basis FROM qb_starts_final GROUP BY ALL),
    keys AS (SELECT player_id, franchise, season FROM roster UNION SELECT player_id, franchise, season FROM g
             UNION SELECT player_id, franchise, season FROM q)
    SELECT k.player_id, k.franchise, k.season,
           coalesce(roster.season_position, roster.any_position, CASE WHEN q.qb_starts > 0 THEN 'QB' END) AS position,
           CASE WHEN q.qb_starts > 0 THEN 'QB' ELSE coalesce(pg.pos_group, dg.pos_group, cp.pos_group) END AS pos_group,
           roster.depth_chart_position,
           coalesce(g.games, 0) AS games,
           coalesce(q.qb_starts, 0) AS qb_starts, q.qb_source, q.qb_basis,
           CASE WHEN q.qb_starts > 0 THEN 'qb_start' WHEN g.games > 0 THEN 'games'
                WHEN roster.active_week THEN 'active_week'
                WHEN NOT coalesce(roster.has_weekly, false) AND k.season < 2002 AND roster.active_season_status THEN 'season_status'
                ELSE 'none' END AS basis,
           coalesce(g.games > 0 OR q.qb_starts > 0 OR roster.active_week
             OR (NOT coalesce(roster.has_weekly, false) AND k.season < 2002 AND roster.active_season_status), false) AS counted,
           (k.season < 2002 AND coalesce(g.games, 0) = 0 AND NOT coalesce(roster.active_season_status, false)
             AND list_has_any(roster.season_statuses, {UNCONFIRMED.replace("(", "[").replace(")", "]")})) AS unconfirmed_status,
           al.league, al.conference, al.division
    FROM keys k
    LEFT JOIN roster USING (player_id, franchise, season)
    LEFT JOIN g USING (player_id, franchise, season)
    LEFT JOIN q USING (player_id, franchise, season)
    LEFT JOIN position_groups pg ON pg.code = coalesce(roster.season_position, roster.any_position)
    -- 'SPEC' (1981-2001 K/P/LS) and blanks: fall back to the depth-chart position
    LEFT JOIN position_groups dg ON dg.code = roster.depth_chart_position
    LEFT JOIN career_pos cp ON cp.player_id = k.player_id
    LEFT JOIN team_alignment al ON al.franchise = k.franchise AND k.season BETWEEN al.season_min AND al.season_max
    """)
    n = con.execute("SELECT count(*), count(*) FILTER (WHERE counted), count(*) FILTER (WHERE unconfirmed_status) FROM player_team_seasons").fetchall()[0]
    log(f"  {n[0]} player-team-seasons; {n[1]} counted; {n[2]} pre-2002 unconfirmed (excluded, listed in probe)")


def _production(con, log) -> None:
    """player_season_production: regular-season yards per player x franchise x season (1999+), for `peak` (§7)."""
    run(con, f"""
    CREATE OR REPLACE TABLE player_season_production AS
    SELECT player_id, season, {_franchise_sql('team', 'season')} AS franchise,
           sum(coalesce(passing_yards, 0)) AS passing_yards,
           sum(coalesce(rushing_yards, 0) + coalesce(receiving_yards, 0)) AS scrimmage_yards
    FROM raw_player_week
    WHERE season_type = 'REG' AND player_id IS NOT NULL
    GROUP BY player_id, season, team
    """)
    log(f"  player_season_production: {con.execute('SELECT count(*) FROM player_season_production').fetchall()[0][0]} rows")


def build_colleges(con, log=print) -> None:
    """player_college: one canonical final college per player (spec §3 college filter).

    Priority: draft picks (1980+, the college at the draft = final school) > nflverse players
    (college_name) > latest roster row. Multi-school strings keep the first segment (the final school);
    names go through colleges.normalize (rules + data/college_aliases.csv).
    """
    from .colleges import normalize
    log("build: player_college")
    if not table_exists(con, "raw_draft_picks"):
        log("  raw_draft_picks missing: run refresh (draft picks) first; drafted colleges skipped")
    draft = con.sql("""
        SELECT p.player_id, d.college AS raw, d.season AS draft_season, d.round AS draft_round
        FROM raw_draft_picks d JOIN players p
          ON (d.gsis_id IS NOT NULL AND d.gsis_id = p.gsis_id) OR (d.pfr_player_id IS NOT NULL AND d.pfr_player_id = p.pfr_id)
        WHERE d.college IS NOT NULL
        QUALIFY row_number() OVER (PARTITION BY p.player_id ORDER BY d.season DESC) = 1
    """).pl().with_columns(source=pl.lit("draft")) if table_exists(con, "raw_draft_picks") else None
    nflp = con.sql("""
        SELECT p.player_id, r.college_name AS raw, NULL::INT AS draft_season, NULL::INT AS draft_round, 'players' AS source
        FROM raw_players r JOIN players p ON r.gsis_id = p.gsis_id WHERE r.college_name IS NOT NULL
    """).pl()  # nflverse players: one current college per person, all eras it covers
    roster = con.sql("""
        SELECT player_id, college AS raw, NULL::INT AS draft_season, NULL::INT AS draft_round, 'roster' AS source
        FROM players WHERE college IS NOT NULL
    """).pl()  # players.college: latest roster row with a college (identity step)
    df = pl.concat([d for d in (draft, nflp, roster) if d is not None], how="vertical_relaxed")
    prio = {"draft": 0, "players": 1, "roster": 2}
    df = (df.with_columns(prio=pl.col("source").replace_strict(prio))
          .sort("prio").unique("player_id", keep="first").drop("prio")
          .with_columns(college=pl.col("raw").map_elements(normalize, return_dtype=pl.Utf8))
          .filter(pl.col("college").is_not_null()))
    write_table(con, "player_college", df.select("player_id", "college", "raw", "source", "draft_season", "draft_round"))
    log(f"  player_college: {df.height} players; by source: "
        + ", ".join(f"{k} {(df['source'] == k).sum()}" for k in prio))
