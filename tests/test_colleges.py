import duckdb
import pytest

from football_trivia.answers import COLLEGE_FIRST_SEASON, Prompt, build_answers
from football_trivia.colleges import normalize
from football_trivia.scoring import threshold_kind


# ------------------------------------------------------------ normalization

@pytest.mark.parametrize("raw, want", [
    ("Ohio St.", "Ohio State"),
    ("Ohio State", "Ohio State"),
    ("Penn St.", "Penn State"),
    ("Middle Tenn. St.", "Middle Tennessee"),
    ("Miss. Valley St.", "Mississippi Valley State"),
    ("Louisiana State", "LSU"),
    ("Southern California", "USC"),
    ("Brigham Young", "BYU"),
    ("Texas A&amp;M", "Texas A&M"),               # HTML entity
    ("Jackson State University", "Jackson State"),
    ("Fort Valley State College", "Fort Valley State"),
    ("Boston College", "Boston College"),         # "College" is part of the name
    ("Boston University", "Boston University"),
    # Miami: bare roster "Miami" is Miami (FL) (63/63 drafted players agree); Ohio is always marked
    ("Miami", "Miami (FL)"),
    ("Miami (Fla.)", "Miami (FL)"),
    ("Miami (FL)", "Miami (FL)"),
    ("Miami (Ohio)", "Miami (OH)"),
    ("Miami, O.", "Miami (OH)"),
])
def test_normalize(raw, want):
    assert normalize(raw) == want


def test_final_school_is_first_segment():
    # nflverse lists the final school first ("Montez Sweat: Mississippi State; Copiah-Lincoln JC; Michigan State")
    assert normalize("Mississippi State; Copiah-Lincoln Junior College; Michigan State") == "Mississippi State"
    assert normalize("California; Butte College") == "California"


def test_normalize_empty():
    assert normalize(None) is None
    assert normalize("  ") is None


# ------------------------------------------------------------ the filter

@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute("""CREATE TABLE players (player_id VARCHAR, display_name VARCHAR, wiki_title VARCHAR)""")
    c.execute("""CREATE TABLE player_honors (player_id VARCHAR, pv24 DOUBLE, pro_bowls INT, all_pro_1st INT, hof BOOLEAN)""")
    c.execute("""CREATE TABLE player_college (player_id VARCHAR, college VARCHAR, raw VARCHAR, source VARCHAR,
                                              draft_season INT, draft_round INT)""")
    c.execute("""CREATE TABLE qb_list_crosscheck (franchise VARCHAR, season INT, wiki_name VARCHAR, player_id VARCHAR,
                                                  wiki_starts INT, nflverse_starts INT, status VARCHAR)""")
    c.execute("""CREATE TABLE player_team_seasons (
        player_id VARCHAR, franchise VARCHAR, league VARCHAR, season INT, conference VARCHAR, division VARCHAR,
        counted BOOLEAN, pos_group VARCHAR, position VARCHAR, depth_chart_position VARCHAR,
        qb_starts DOUBLE, games INT, basis VARCHAR, unconfirmed_status BOOLEAN)""")
    people = [  # id, name, college, [(season, pos_group, counted, qb_starts)]
        ("wr1", "Buckeye Receiver", "Ohio State", [(2010, "WR", True, 0)]),
        ("wr2", "Buckeye Old Timer", "Ohio State", [(1972, "WR", True, 0), (1975, "WR", True, 0)]),
        ("wr3", "Buckeye Too Early", "Ohio State", [(1970, "WR", True, 0)]),      # career ended before 1974
        ("wr4", "Buckeye Practice Squad", "Ohio State", [(2015, "WR", False, 0)]),  # never counted
        ("wr5", "Wolverine Receiver", "Michigan", [(2012, "WR", True, 0)]),
        ("rb1", "Buckeye Back", "Ohio State", [(2005, "RB", True, 0)]),
        ("qb1", "Buckeye Starter", "Ohio State", [(2001, "QB", True, 12)]),
        ("qb2", "Buckeye Clipboard", "Ohio State", [(2003, "QB", True, 0)]),       # QB with no start
        ("x1", "Unknown School", None, [(2010, "WR", True, 0)]),
    ]
    for pid, name, college, seasons in people:
        c.execute("INSERT INTO players VALUES (?, ?, NULL)", [pid, name])
        c.execute("INSERT INTO player_honors VALUES (?, 100, 0, 0, false)", [pid])
        if college:
            c.execute("INSERT INTO player_college VALUES (?, ?, ?, 'draft', NULL, NULL)", [pid, college, college])
        for season, grp, counted, starts in seasons:
            c.execute("INSERT INTO player_team_seasons VALUES (?, 'CLE', 'NFL', ?, 'AFC', 'AFC North', ?, ?, ?, ?, ?, 1, 'games', false)",
                      [pid, season, counted, grp, grp, grp, starts])
    yield c
    c.close()


def ids(con, filters, text="Since 1974"):
    r = build_answers(con, Prompt(filters=filters, text=text, type="trait"))
    return set(r.answers["player_id"].to_list()), r


def test_college_position(con):
    got, _ = ids(con, {"college": "Ohio State", "position": "WR"})
    # wr2: a 1975 season clears the 1974 cutoff; wr3 (1970 only) and wr4 (never counted) don't
    assert got == {"wr1", "wr2"}


def test_college_name_is_normalized(con):
    got, _ = ids(con, {"college": "Ohio St.", "position": "WR"})
    assert got == {"wr1", "wr2"}


def test_college_qb_needs_a_start(con):
    got, _ = ids(con, {"college": "Ohio State", "position": "QB"})
    assert got == {"qb1"}


def test_college_list_is_union(con):
    got, _ = ids(con, {"college": ["Ohio State", "Michigan"], "position": "WR"})
    assert got == {"wr1", "wr2", "wr5"}


def test_college_cutoff_and_text_warning(con):
    _, r = ids(con, {"college": "Ohio State", "position": "WR"}, text="Name an Ohio State WR")
    assert any(str(COLLEGE_FIRST_SEASON) in w and "state the date" in w for w in r.warnings)
    _, r = ids(con, {"college": "Ohio State", "position": "WR", "season_min": 1974})
    assert not any("state the date" in w for w in r.warnings)


def test_unknown_college_warns(con):
    got, r = ids(con, {"college": "Hogwarts", "position": "WR"})
    assert got == set()
    assert any("Hogwarts" in w for w in r.warnings)


def test_college_routing():
    p = Prompt(filters={"college": "Ohio State", "position": "WR"}, type="trait")
    assert p.is_trait
    assert threshold_kind(p) == "college"
    assert threshold_kind(Prompt(filters={"award": "mvp"}, type="trait")) == "award"
    assert threshold_kind(Prompt(filters={"stat_threshold": {"stat": "sacks", "min": 10}}, type="trait")) == "stat"
