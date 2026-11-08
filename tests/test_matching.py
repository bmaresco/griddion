import os

import pytest

from football_trivia.matching import Matcher, edit_distance, first_name_variants

BANK = {
    "mahomes": ["Patrick Mahomes", "Mahomes"],
    "a_smith": ["Alex Smith", "Smith"],
    "o_smith": ["Onterrio Smith", "Smith"],   # two Smiths in the bank
    "vick": ["Mike Vick", "Michael Vick", "Vick"],
    "obj": ["Odell Beckham Jr.", "Odell Beckham", "Beckham"],
    "stbrown": ["Amon-Ra St. Brown", ("St. Brown", "last_only")],
    "tittle": ["Y.A. Tittle", "Tittle"],
}
OTHERS = {"andy dalton": {"dalton"}, "patrick mahomes": {"mahomes"}}


@pytest.fixture
def m():
    return Matcher(BANK, OTHERS)


@pytest.mark.parametrize("typed,pid,method", [
    ("Patrick Mahomes", "mahomes", "exact"),
    ("patrick  MAHOMES ", "mahomes", "exact"),
    ("Pat Mahomes", "mahomes", "exact"),          # first-name variant
    ("Mahomes", "mahomes", "last_name"),          # unique last name
    ("Mahomse", "mahomes", "fuzzy"),              # transposition
    ("Patrik Mahomes", "mahomes", "fuzzy"),
    ("Michael Vick", "vick", "exact"),
    ("Odell Beckham", "obj", "exact"),            # suffix dropped
    ("odell beckham jr", "obj", "exact"),
    ("Amon Ra St Brown", "stbrown", "exact"),     # hyphen/period-free
    ("St. Brown", "stbrown", "last_name"),
    ("YA Tittle", "tittle", "exact"),             # initials
    ("Y. A. Tittle", "tittle", "exact"),
])
def test_valid(m, typed, pid, method):
    r = m.match(typed)
    assert (r.status, r.player_id, r.method) == ("valid", pid, method)


def test_last_name_aliases_not_split(m):
    assert m.match("Brown").status == "invalid"        # "St. Brown" is the last name, not "Brown"


def test_ambiguous_last_name(m):
    r = m.match("Smith")
    assert r.status == "ambiguous" and set(r.candidates) == {"a_smith", "o_smith"}


def test_real_player_not_in_bank(m):
    r = m.match("Andy Dalton")
    assert (r.status, r.method) == ("invalid", "not_valid_answer")


def test_short_inputs_need_exact(m):
    assert m.match("Vic").status == "invalid"      # 3 chars: no typo budget
    assert m.match("").method == "empty"


def test_nonsense(m):
    assert m.match("Zzzzzz Qqqqq").method == "no_match"


def test_edit_distance():
    assert edit_distance("mahomes", "mahomse") == 1      # transposition counts once
    assert edit_distance("kitten", "sitting") == 3
    assert first_name_variants("mike vick") >= {"mike vick", "michael vick"}


# --------------------------------------------------------- against the real DB

DB = os.path.join(os.path.dirname(__file__), "..", "data", "trivia.duckdb")


@pytest.mark.skipif(not os.path.exists(DB), reason="needs data/trivia.duckdb (run refresh)")
def test_real_prompts():
    from football_trivia.answers import Prompt, build_answers
    from football_trivia.db import connect
    from football_trivia.matching import bank_aliases, load_others

    con = connect(DB, read_only=True)
    others = load_others(con)

    def matcher(filters):
        r = build_answers(con, Prompt(filters=filters))
        return Matcher(bank_aliases(con, r.answers["player_id"].to_list()), others), r

    kc, r = matcher({"team": "KC", "position": "QB"})
    name = lambda pid: r.answers.filter(r.answers["player_id"] == pid)["display_name"][0]
    assert name(kc.match("Mahomes").player_id) == "Patrick Mahomes"
    assert name(kc.match("Pat Mahomes").player_id) == "Patrick Mahomes"
    assert name(kc.match("len dawsen").player_id) == "Len Dawson"
    assert kc.match("Josh Allen").status == "invalid"          # real QB, never a Chief

    phi, _ = matcher({"team": "PHI", "position": "QB", "season_min": 2026})
    assert phi.match("Andy Dalton").status == "invalid"        # spec §3 example

    jets, rj = matcher({"team": "NYJ", "position": "QB"})
    assert rj.answers.filter(rj.answers["player_id"] == jets.match("Michael Vick").player_id)["display_name"][0] in ("Mike Vick", "Michael Vick")
