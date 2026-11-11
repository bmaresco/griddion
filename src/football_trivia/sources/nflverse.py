"""Raw nflverse pulls -> raw_* tables. No transformation beyond type cleanup."""

from __future__ import annotations

import nflreadpy as nfl
import polars as pl

from ..db import write_table

SNAP_COUNTS_FIRST_SEASON = 2012


def refresh(con, log=print) -> None:
    log("nflverse: players")
    write_table(con, "raw_players", nfl.load_players())

    log("nflverse: rosters (1920-present)")
    write_table(con, "raw_rosters", nfl.load_rosters(seasons=True))

    log("nflverse: weekly rosters (2002-present; catches mid-season moves)")
    write_table(con, "raw_rosters_weekly", nfl.load_rosters_weekly(seasons=True))

    log("nflverse: schedules")
    write_table(con, "raw_schedules", nfl.load_schedules())

    log("nflverse: weekly player stats (1999-present)")
    stats = nfl.load_player_stats(seasons=True, summary_level="week")
    # list-typed kicking columns don't round-trip usefully; keep everything else
    stats = stats.drop([c for c, t in stats.schema.items() if isinstance(t, pl.List)])
    write_table(con, "raw_player_week", stats)

    log(f"nflverse: snap counts ({SNAP_COUNTS_FIRST_SEASON}-present)")
    write_table(con, "raw_snap_counts", nfl.load_snap_counts(seasons=True))

    refresh_draft_picks(con, log)

    log("nflverse: teams")
    write_table(con, "raw_teams", nfl.load_teams())


def refresh_draft_picks(con, log=print) -> None:
    """Draft picks 1980-present: the final college (PFR's college at the draft), spec §3 college."""
    log("nflverse: draft picks (1980-present)")
    write_table(con, "raw_draft_picks", nfl.load_draft_picks())
