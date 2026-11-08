import datetime as dt

from football_trivia.publish import TIER_INFO, _span, drive_number


def test_span():
    assert _span(2009, 2016) == "2009–16"
    assert _span(2008, 2008) == "2008"
    assert _span(1999, 2004) == "1999–2004"


def test_drive_number():
    launch = dt.date(2027, 1, 5)
    assert drive_number(launch, launch) == 1
    assert drive_number(dt.date(2027, 1, 18), launch) == 14


def test_yards_are_points_over_five():
    assert {k: v["yards"] for k, v in TIER_INFO.items()} == {
        "Starter": 2, "Botched Trick Play": 3, "Backup": 6, "Hidden Gem": 12,
        "Sleeper Pick": 17, "YKB Kid": 20, "Incomplete": 0}
