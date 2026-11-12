import duckdb
import pytest

from football_trivia.answers import Prompt, build_answers
from football_trivia.scoring import threshold_kind
from football_trivia.sources.ap_awards import all_pro_group, hof_groups, parse_all_pro_page
from football_trivia.sources.wikipedia import honor_seasons


# ------------------------------------------------------------ parsers

def test_honor_seasons():
    got = honor_seasons("* 12× [[Pro Bowl]] (2012–2018, 2020−2023)\n* 2× [[All-Pro|First-team All-Pro]] (2006, 2008)\n"
                        "* Second-team All-Pro (2010)\n* 3× AAFC All-Pro (1947–1949)\n* Pro Bowl MVP (2009)\n"
                        "* 4× Pro Bowl (1950–53)")
    pb = sorted(s for h, s in got if h == "pro_bowl")
    assert pb == [1950, 1951, 1952, 1953, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2020, 2021, 2022, 2023]
    assert sorted(s for h, s in got if h == "all_pro_1st") == [2006, 2008]  # AAFC line skipped
    assert [s for h, s in got if h == "all_pro_2nd"] == [2010]


@pytest.mark.parametrize("label, want", [
    ("Coach", []), ("Team owner/general manager", []),
    ("Defensive tackle/end", ["DL"]),                 # bare "end" keeps "defensive"
    ("Defensive end/linebacker", ["DL", "LB"]),
    ("Offensive end Pre-Modern Era: Two-Way Performer", ["WR"]),  # Don Hutson
    ("Wide receiver/punt returner", ["WR"]),
    ("Halfback/flanker", ["RB", "WR"]),
    ("Guard Center Tackle", ["OL"]),
    ("Tight End", ["TE"]),
])
def test_hof_groups(label, want):
    assert hof_groups(label) == want


def test_all_pro_page():
    html = """<h2>Teams</h2><table class="wikitable"><tr><th>Position</th><th>First team</th><th>Second team</th></tr>
    <tr><td>Edge rusher</td><td><a title="Nick Bosa">Nick Bosa</a>, <a title="2022 San Francisco 49ers season">San Francisco</a> (AP)<br/>
    <a title="Micah Parsons">Micah Parsons</a>, <a title="2022 Dallas Cowboys season">Dallas</a> (PFWA)</td><td>x (AP-2)</td></tr></table>"""
    assert parse_all_pro_page(html) == [{"slot": "Edge rusher", "wiki_title": "Nick Bosa", "name": "Nick Bosa"}]
    assert [all_pro_group(x) for x in ("Edge rusher", "Inside linebacker", "Kick Returner", "Special teamer",
                                        "Interior lineman/Defensive tackle", "Left tackle", "Flanker/ Split End")] == \
        ["roster", "LB", None, None, "DL", "OL", "WR"]


# ------------------------------------------------------------ filters

@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute("CREATE TABLE players (player_id VARCHAR, display_name VARCHAR, wiki_title VARCHAR, gsis_id VARCHAR, pfr_id VARCHAR)")
    c.execute("CREATE TABLE player_honors (player_id VARCHAR, pv24 DOUBLE, pro_bowls INT, all_pro_1st INT, hof BOOLEAN)")
    c.execute("CREATE TABLE position_groups (code VARCHAR, pos_group VARCHAR)")
    c.execute("INSERT INTO position_groups VALUES ('QB','QB'), ('WR','WR'), ('LB','LB'), ('DE','DL'), ('T','OL')")
    c.execute("""CREATE TABLE player_team_seasons (player_id VARCHAR, franchise VARCHAR, league VARCHAR, season INT,
        pos_group VARCHAR, position VARCHAR, depth_chart_position VARCHAR, counted BOOLEAN, qb_starts DOUBLE, games INT)""")
    c.execute("CREATE TABLE player_hof (player_id VARCHAR, class INT, position VARCHAR[], groups VARCHAR[])")
    c.execute("CREATE TABLE player_honor_seasons (player_id VARCHAR, honor VARCHAR, season INT, slot VARCHAR, slot_group VARCHAR)")
    c.execute("CREATE TABLE player_awards (player_id VARCHAR, award VARCHAR, season INT, source VARCHAR)")
    c.execute("""CREATE TABLE raw_draft_picks (season INT, round INT, pick INT, team VARCHAR, gsis_id VARCHAR,
        pfr_player_id VARCHAR, position VARCHAR)""")
    seasons = [  # player, franchise, season, group, counted, qb_starts, games
        ("hutson", "GB", 1940, "DL", True, 0, 11),            # roster says DL; inducted as an offensive end
        ("coach", "PIT", 1980, "LB", True, 0, 16),            # inducted as a coach
        ("lb", "NYG", 1985, "LB", True, 0, 16),
        ("traded", "PIT", 2005, "WR", True, 0, 4), ("traded", "DAL", 2005, "WR", True, 0, 12),
        ("steeler", "PIT", 2010, "WR", True, 0, 16), ("steeler", "PIT", 1998, "WR", True, 0, 16),
        ("qb1", "IND", 2001, "QB", True, 10, 12),
        ("qb2", "CLE", 2003, "QB", True, 0, 2),               # first-rounder who never started
        ("heis", "DET", 1990, "WR", True, 0, 10),
    ]
    for pid, fr, s, g, cnt, qs, gm in seasons:
        c.execute("INSERT INTO player_team_seasons VALUES (?, ?, 'NFL', ?, ?, ?, ?, ?, ?, ?)", [pid, fr, s, g, g, g, cnt, qs, gm])
    c.execute("INSERT INTO player_hof VALUES ('hutson', 1963, ['Offensive end'], ['WR']), ('lb', 2000, ['Linebacker'], ['LB'])")
    c.execute("""INSERT INTO player_honor_seasons VALUES ('traded','pro_bowl',2005,NULL,NULL), ('steeler','pro_bowl',2010,NULL,NULL),
                 ('steeler','pro_bowl',1998,NULL,NULL), ('steeler','all_pro_1st',2010,'Wide receiver','WR'),
                 ('lb','all_pro_1st',1985,'Outside linebacker','LB'),
                 ('heis','all_pro_1st',1990,'Kick returner',NULL),        -- special-teams pick: no positional credit
                 ('heis','all_pro_1st_infobox',1991,NULL,NULL)""")
    c.execute("INSERT INTO player_awards VALUES ('heis','heisman',1988,'list'), ('nfl_never','heisman',2001,'list')")
    c.execute("""INSERT INTO raw_draft_picks VALUES (2001, 1, 1, 'IND', 'g-qb1', NULL, 'QB'), (2003, 1, 20, 'CLE', 'g-qb2', NULL, 'QB'),
                 (1999, 1, 3, 'PIT', NULL, 'StStee00', 'WR'), (1984, 1, 1, 'NYG', 'g-lb', NULL, 'LB')""")
    ids = {r[0] for r in seasons} | {"nfl_never"}
    for pid in ids:
        c.execute("INSERT INTO players VALUES (?, ?, NULL, ?, ?)", [pid, pid, f"g-{pid}", "StStee00" if pid == "steeler" else None])
        c.execute("INSERT INTO player_honors VALUES (?, 100, 0, 0, false)", [pid])
    yield c
    c.close()


def ids(con, filters, text="Since 1980"):
    r = build_answers(con, Prompt(filters=filters, text=text, type="trait"))
    return set(r.answers["player_id"].to_list()), r


def test_hall_of_fame_uses_inducted_position(con):
    assert ids(con, {"hall_of_fame": True})[0] == {"hutson", "lb"}       # the coach is out
    assert ids(con, {"hall_of_fame": True, "position": "WR"})[0] == {"hutson"}
    assert ids(con, {"hall_of_fame": True, "position": "DL"})[0] == set()
    assert ids(con, {"hall_of_fame": True, "season_min": 1960})[0] == {"lb"}  # played in the window


def test_pro_bowl_team_is_main_team_that_season(con):
    got, _ = ids(con, {"pro_bowl": True, "team": "DAL"})
    assert got == {"traded"}                       # 12 of his 16 games in 2005 were for Dallas
    got, _ = ids(con, {"pro_bowl": True, "team": "PIT", "season_min": 2000})
    assert got == {"steeler"}
    p = Prompt(filters={"pro_bowl": True, "team": "PIT"}, type="")
    assert p.is_trait and threshold_kind(p) == "award"   # team doesn't make it a team prompt


def test_all_pro_position_and_window(con):
    assert ids(con, {"all_pro": True, "position": "WR", "season_min": 2000})[0] == {"steeler"}
    assert ids(con, {"all_pro": True, "season_max": 1999})[0] == {"lb", "heis"}   # 1968+ (AP pages)
    assert ids(con, {"all_pro": True, "position": "WR"})[0] == {"steeler"}        # returner slot isn't WR
    _, r = ids(con, {"all_pro": True}, text="Name a first-team All-Pro")
    assert any("1968" in w for w in r.warnings)


def test_heisman_needs_an_nfl_game(con):
    got, _ = ids(con, {"award": "heisman"})
    assert got == {"heis"}


def test_draft(con):
    got, r = ids(con, {"draft": {"pick": 1}})
    assert got == {"qb1", "lb"}
    got, _ = ids(con, {"draft": {"round": 1}, "position": "QB", "season_min": 2000})
    assert got == {"qb1"}                          # QB rule: qb2 never started
    got, _ = ids(con, {"draft": {"pick_max": 5}, "season_min": 1990})
    assert got == {"qb1", "steeler"}               # matched on the PFR id
    _, r = ids(con, {"draft": {"pick": 1}}, text="Name a #1 overall pick")
    assert any("1980" in w for w in r.warnings)


def test_routing():
    for f in ({"hall_of_fame": True}, {"all_pro": True}, {"draft": {"pick": 1}}, {"award": "sb_mvp"}):
        assert threshold_kind(Prompt(filters=f, type="trait")) == "award"
