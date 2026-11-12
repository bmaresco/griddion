import datetime as dt

from football_trivia.publish import TIER_INFO, _span, drive_on


def test_span():
    assert _span(2009, 2016) == "2009–16"
    assert _span(2008, 2008) == "2008"
    assert _span(1999, 2004) == "1999–2004"


def test_drive_on_uses_schedule_dates():
    sched = {"drives": [{"drive": 1, "date": "2026-11-09"}, {"drive": 2, "date": "2026-11-10"},
                        {"drive": 3, "date": "2026-12-01"}]}
    assert drive_on(dt.date(2026, 11, 10), sched)["drive"] == 2
    assert drive_on(dt.date(2026, 11, 20), sched) is None           # gap before the relaunch
    assert drive_on(dt.date(2026, 12, 1), sched)["drive"] == 3


def _sched_file(tmp_path, monkeypatch, drives, frozen_through=2):
    import json
    from football_trivia import publish
    path = tmp_path / "schedule.json"
    path.write_text(json.dumps({"launch_date": "2026-11-09", "frozen_through": frozen_through,
                                "drives": [{"drive": n, "date": d, "prompt_ids": [f"d{n:02d}-1"]} for n, d in drives]}))
    monkeypatch.setattr(publish, "SCHEDULE", path)
    return path


def test_shift(tmp_path, monkeypatch):
    import json
    import pytest
    from football_trivia.publish import shift_schedule
    path = _sched_file(tmp_path, monkeypatch, [(1, "2026-11-09"), (2, "2026-11-10"), (3, "2026-11-11"), (4, "2026-11-12")])
    today = dt.date(2026, 11, 11)
    with pytest.raises(SystemExit):     # drive 3's date has come: needs --never-deployed
        shift_schedule(dt.date(2026, 12, 1), today=today)
    with pytest.raises(SystemExit):     # never into the past / today
        shift_schedule(dt.date(2026, 11, 11), today=today, never_deployed=True)
    with pytest.raises(SystemExit):     # frozen drives never move
        shift_schedule(dt.date(2026, 12, 1), first=2, today=today, never_deployed=True)
    _, changes = shift_schedule(dt.date(2026, 12, 1), today=today, never_deployed=True)
    assert changes == [(3, "2026-11-11", "2026-12-01"), (4, "2026-11-12", "2026-12-02")]
    dates = {d["drive"]: d["date"] for d in json.loads(path.read_text())["drives"]}
    assert dates == {1: "2026-11-09", 2: "2026-11-10", 3: "2026-12-01", 4: "2026-12-02"}


def test_frozen_check_uses_shifted_dates():
    from football_trivia.publish import is_frozen
    sched = {"frozen_through": 2}
    today = dt.date(2026, 11, 20)
    assert not is_frozen({"drive": 3, "date": "2026-12-01"}, sched, today)   # moved to the future
    assert is_frozen({"drive": 3, "date": "2026-12-01"}, sched, dt.date(2026, 12, 1))
    assert is_frozen({"drive": 2, "date": "2026-11-10"}, sched, today)


def test_write_schedule_keeps_shifted_dates(tmp_path, monkeypatch):
    import json
    from football_trivia import publish
    _sched_file(tmp_path, monkeypatch, [(1, "2026-11-09"), (2, "2026-11-10"), (3, "2026-12-01")])
    q = tmp_path / "queue.jsonl"
    q.write_text("\n".join(json.dumps({"day": d, "id": f"d{d:02d}-1"}) for d in (1, 2, 3, 4)))
    monkeypatch.setattr(publish, "ROOT", tmp_path)
    monkeypatch.setattr(publish, "today_et", lambda: dt.date(2026, 11, 20))
    s = publish.write_schedule(None, q)
    assert [d["date"] for d in s["drives"]] == ["2026-11-09", "2026-11-10", "2026-12-01", "2026-12-02"]


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
