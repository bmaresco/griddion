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

    log("nflverse: teams")
    write_table(con, "raw_teams", nfl.load_teams())
