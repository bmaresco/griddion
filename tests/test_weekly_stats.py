import duckdb
import pytest

from football_trivia.answers import Prompt, build_answers, weekly_stat_qualifiers
from football_trivia.scoring import threshold_kind


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute("CREATE TABLE players (player_id VARCHAR, display_name VARCHAR, wiki_title VARCHAR)")
    c.execute("CREATE TABLE player_honors (player_id VARCHAR, pv24 DOUBLE, pro_bowls INT, all_pro_1st INT, hof BOOLEAN)")
    c.execute("CREATE TABLE team_franchises (code VARCHAR, franchise VARCHAR, season_min INT, season_max INT)")
    c.execute("INSERT INTO team_franchises VALUES ('NYG', 'NYG', 1925, 2100), ('ATL', 'ATL', 1966, 2100)")
    c.execute("CREATE TABLE position_groups (code VARCHAR, pos_group VARCHAR)")
    c.execute("INSERT INTO position_groups VALUES ('WR','WR'), ('RB','RB'), ('FB','RB'), ('QB','QB'), ('DE','DL'), ('TE','TE')")
    c.execute("""CREATE TABLE player_team_seasons (
        player_id VARCHAR, franchise VARCHAR, season INT, position VARCHAR, pos_group VARCHAR,
        depth_chart_position VARCHAR, counted BOOLEAN, qb_starts DOUBLE, games INT)""")
    c.execute("""CREATE TABLE raw_player_week (
        player_id VARCHAR, season INT, week INT, season_type VARCHAR, team VARCHAR, position VARCHAR,
        receptions DOUBLE, rushing_tds DOUBLE, def_sacks DOUBLE, def_interceptions DOUBLE)""")
    pts = [  # player, franchise, season, position, counted
        ("hybrid", "ATL", 2015, "WR", True), ("hybrid", "ATL", 2021, "RB", True),  # WR, then RB
        ("fb", "NYG", 2010, "FB", True),
        ("qb", "NYG", 2012, "QB", True),
        ("rookie", "NYG", 2014, "WR", True), ("rookie", "NYG", 2015, "WR", True),
        ("late", "NYG", 2009, "WR", False), ("late", "NYG", 2010, "WR", True),     # practice squad year, then plays
        ("rusher", "NYG", 2005, "DE", True),
    ]
    for pid, fr, season, pos, counted in pts:
        grp = {"FB": "RB", "DE": "DL"}.get(pos, pos)
        c.execute("INSERT INTO player_team_seasons VALUES (?, ?, ?, ?, ?, ?, ?, 0, 16)", [pid, fr, season, pos, grp, pos, counted])
    weeks = [  # player, season, week, team, current position, rec, rush_td, sacks, int
        ("hybrid", 2015, 1, "ATL", "RB", 3, 1, 0, 0),   # weekly position is his *current* one (RB)
        ("hybrid", 2021, 1, "ATL", "RB", 2, 2, 0, 0),
        ("fb", 2010, 3, "NYG", "FB", 1, 1, 0, 0),
        ("qb", 2012, 4, "NYG", "QB", 0, 1, 0, 0),
        ("rookie", 2014, 1, "NYG", "WR", 40, 0, 0, 0), ("rookie", 2014, 2, "NYG", "WR", 35, 0, 0, 0),
        ("rookie", 2015, 1, "NYG", "WR", 90, 0, 0, 0),
        ("late", 2010, 1, "NYG", "WR", 80, 0, 0, 0),
        ("rusher", 2005, 1, "NYG", "DE", 0, 0, 3.5, 0), ("rusher", 2005, 2, "NYG", "DE", 0, 0, 2.0, 0),
        ("rusher", 2005, 3, "NYG", "DE", 0, 0, 4.0, 2),
        ("rusher", 2005, 4, "NYG", "DE", 0, 0, 1.0, 0),
        ("rusher", 1998, 1, "NYG", "DE", 0, 0, 5.0, 0),  # before weekly stats count (1999)
    ]
    for w in weeks:
        c.execute("INSERT INTO raw_player_week VALUES (?, ?, ?, 'REG', ?, ?, ?, ?, ?, ?)", list(w))
    for pid in {p[0] for p in pts}:
        c.execute("INSERT INTO players VALUES (?, ?, NULL)", [pid, pid])
        c.execute("INSERT INTO player_honors VALUES (?, 100, 0, 0, false)", [pid])
    yield c
    c.close()


def ids(con, filters, text="Since 1999"):
    r = build_answers(con, Prompt(filters=filters, text=text, type="trait"))
    return set(r.answers["player_id"].to_list()), r


def test_window_stat_uses_listed_position_that_season(con):
    # hybrid's 2015 TD came as a WR (weekly row says RB, his current position): it counts as non-RB
    got, _ = ids(con, {"window_stat": {"stat": "rushing_tds", "min": 1}, "position_not": ["RB"]})
    assert got == {"hybrid", "qb"}  # fb excluded: FB is in the RB group
    got, _ = ids(con, {"window_stat": {"stat": "rushing_tds", "min": 1}, "position_not": ["RB", "QB"]})
    assert got == {"hybrid"}


def test_window_stat_range_and_total(con):
    got, _ = ids(con, {"window_stat": {"stat": "rushing_tds", "min": 1}, "season_min": 2011, "position": "WR"})
    assert got == {"hybrid"}  # his 2015 TD, as a WR
    got, _ = ids(con, {"window_stat": {"stat": "rushing_tds", "min": 1}, "season_min": 2016, "position": "WR"})
    assert got == set()  # from 2016 his only TDs came as an RB (2021)
    got, _ = ids(con, {"window_stat": {"stat": "rushing_tds", "min": 3}, "season_min": 2011})
    assert got == {"hybrid"}  # 1 (2015) + 2 (2021)


def test_game_stat_threshold_and_games_min(con):
    got, _ = ids(con, {"game_stat": {"stat": "sacks", "min": 3.5}})
    assert got == {"rusher"}  # 3.5 and 4.0 games; the 1998 game doesn't count
    q = weekly_stat_qualifiers(con, {"game_stat": {"stat": "sacks", "min": 3.5}, "season_min": 1999}, "game_stat")
    assert q.row(0, named=True) | {} == {"player_id": "rusher", "games": 2, "best": 4.0, "best_season": 2005, "best_week": 3}
    got, _ = ids(con, {"game_stat": {"stat": "sacks", "min": 3.5, "games_min": 3}})
    assert got == set()


def test_rookie_stat_is_first_season_played(con):
    got, _ = ids(con, {"rookie_stat": {"stat": "receptions", "min": 70}, "position": "WR"})
    # rookie: 75 in 2014 (not his 90 in 2015); late: practice-squad 2009 doesn't count, 80 in 2010
    assert got == {"rookie", "late"}
    got, _ = ids(con, {"rookie_stat": {"stat": "receptions", "min": 80}, "position": "WR"})
    assert got == {"late"}


def test_weekly_stat_rules(con):
    _, r = ids(con, {"game_stat": {"stat": "sacks", "min": 3.5}}, text="Name a player with 3.5+ sacks in a game")
    assert any("1999" in w for w in r.warnings)
    with pytest.raises(ValueError):
        ids(con, {"stat_threshold": {"stat": "sacks", "min": 10}, "position_not": "RB"})
    p = Prompt(filters={"game_stat": {"stat": "sacks", "min": 3.5}}, type="trait")
    assert p.is_trait and threshold_kind(p) == "stat"
