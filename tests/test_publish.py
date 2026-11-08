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


def test_frozen_drives():
    from football_trivia.publish import is_frozen
    sched = {"frozen_through": 1}
    today = dt.date(2026, 11, 8)
    d = lambda n, day: {"drive": n, "date": day}
    assert is_frozen(d(1, "2026-11-09"), sched, today)        # frozen_through, before its date
    assert not is_frozen(d(2, "2026-11-10"), sched, today)
    assert is_frozen(d(2, "2026-11-10"), sched, dt.date(2026, 11, 10))   # live at 00:00 ET on its date
    assert is_frozen(d(2, "2026-11-10"), {}, dt.date(2026, 11, 12))      # past


def test_award_prompts_use_pageview_fame_only():
    import polars as pl
    from football_trivia.answers import Prompt, Result
    from football_trivia.scoring import score_answers
    fame_df = pl.DataFrame({"player_id": ["a", "b"], "s_pv": [0.9, 0.2], "F": [0.5, 0.8]})
    answers = pl.DataFrame({"player_id": ["a", "b"], "display_name": ["A", "B"]})
    award = Prompt.from_json({"text": "x", "type": "trait", "filters": {"award": "mvp"}})
    stat = Prompt.from_json({"text": "x", "type": "trait",
                             "filters": {"stat_threshold": {"stat": "sacks", "min": 10}}})
    for p, want in ((award, {"a": 0.9, "b": 0.2}), (stat, {"a": 0.5, "b": 0.8})):
        r = Result.__new__(Result)
        r.prompt, r.answers = p, answers
        s, _ = score_answers(None, r, fame_df)
        assert dict(zip(s["player_id"], s["F"])) == want
