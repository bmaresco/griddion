from football_trivia.sources.wikipedia import parse_highlights

STABLER = """
* [[List of Super Bowl champions|Super Bowl champion]] ([[Super Bowl XI|XI]])
* [[NFL Most Valuable Player]] (1974)
* [[NFL Offensive Player of the Year Award|NFL Offensive Player of the Year]] (1974)
* First-team [[All-Pro]] ([[1974 All-Pro Team|1974]])
* Second-team All-Pro ([[1976 All-Pro Team|1976]])
* 4× [[Pro Bowl]] ([[1974 Pro Bowl|1973]], [[1975 Pro Bowl|1974]], [[1977 Pro Bowl|1976]], [[1978 Pro Bowl|1977]])
* [[Hickok Belt]] (1976)
* First-team [[College Football All-America Team|All-American]] ([[1967 College Football All-America Team|1967]])
"""

DONALD = """
* 3× [[AP NFL Defensive Player of the Year|NFL Defensive Player of the Year]] (2017, 2018, 2020)
* [[National Football League Rookie of the Year Award|NFL Defensive Rookie of the Year]] (2014)
* 8× First-team [[All-Pro]] ([[2015 All-Pro Team|2015]]–[[2021 All-Pro Team|2021]], [[2023 All-Pro Team|2023]])
* 10× [[Pro Bowl]] ([[2015 Pro Bowl|2014]]–[[2024 Pro Bowl Games|2023]])
* [[Pro Football Writers of America NFL Defensive Player of the Year Award|PFWA All-Rookie Team]] (2014)
* [[ACC Defensive Player of the Year]] (2013)
"""

ORTON = """
* [[PFWA All-Rookie Team]] ([[PFWA All-Rookie Team#2005|2005]])
* [[Senior Bowl]] (2005)
* [[Sun Bowl#C.M. Hendricks Most Valuable Player Trophy|Hendricks Trophy]] (Sun Bowl MVP) (2002)
"""


def test_stabler():
    r = parse_highlights(STABLER)
    assert r["pro_bowls"] == 4
    assert r["all_pro_1st"] == 1 and r["all_pro_2nd"] == 1
    assert ("mvp", 1974) in r["awards"] and ("opoy", 1974) in r["awards"]
    assert ("sb_champ", None) in r["awards"]


def test_donald():
    r = parse_highlights(DONALD)
    assert r["pro_bowls"] == 10 and r["all_pro_1st"] == 8
    assert sorted(s for k, s in r["awards"] if k == "dpoy") == [2017, 2018, 2020]
    assert ("droy", 2014) in r["awards"]
    assert not any(k == "mvp" for k, _ in r["awards"])


def test_no_false_positives():
    r = parse_highlights(ORTON)
    assert r == {"pro_bowls": 0, "all_pro_1st": 0, "all_pro_2nd": 0, "afl_all_star": 0, "awards": []}


def test_mvp_excludes_non_ap_variants():
    for line in [
        "* NFL Europe Offensive MVP (2000)",
        "* NFL Europe co-defensive MVP (2000)",
        "* PFWA NFL Most Valuable Player (2003)",
        "* [[Super Bowl Most Valuable Player Award|Super Bowl MVP]] (XXXIV)",
        "* [[Pro Bowl]] MVP (2004)",
    ]:
        assert not any(k == "mvp" for k, _ in parse_highlights(line)["awards"]), line
    assert ("mvp", 2003) in parse_highlights("* [[NFL Most Valuable Player|NFL co-MVP]] (2003)")["awards"]
