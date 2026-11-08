"""`refresh`: pull every source into the local DuckDB cache, then derive tables.

    uv run refresh                 # everything
    uv run refresh --skip pageviews
    uv run refresh --only build    # re-derive from cached raw tables, no network
"""

from __future__ import annotations

import argparse
import datetime as dt
import time

from . import build
from .db import connect, run, table_exists
from .sources import ap_awards, nflverse, pageviews, qb_lists, wikidata, wikipedia

STEPS = ["nflverse", "wikidata", "wikipedia", "qb_lists", "pageviews", "build"]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="refresh", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", help="DuckDB path (default data/trivia.duckdb, or $FT_DB)")
    ap.add_argument("--only", nargs="+", choices=STEPS)
    ap.add_argument("--skip", nargs="+", choices=STEPS, default=[])
    args = ap.parse_args(argv)
    steps = [s for s in (args.only or STEPS) if s not in args.skip]

    t0 = time.time()
    log = lambda m: print(f"[{time.time() - t0:6.0f}s] {m}", flush=True)
    con = connect(args.db)

    if "nflverse" in steps:
        nflverse.refresh(con, log)
    if "wikidata" in steps:
        wikidata.refresh(con, log)
    if "qb_lists" in steps:
        qb_lists.refresh(con, log)
        qb_lists.refresh_redirects(con, log)
        ap_awards.refresh(con, log)
    if {"wikipedia", "pageviews"} & set(steps):
        build.build_identity(con, log)
        titles = [t for (t,) in con.execute("SELECT DISTINCT wiki_title FROM players WHERE wiki_title IS NOT NULL ORDER BY 1").fetchall()]
        if "wikipedia" in steps:
            wikipedia.refresh(con, titles, log)
        if "pageviews" in steps:
            pageviews.refresh(con, titles, log)
            pageviews.refresh_moves(con, titles, log)
            pageviews.refresh_moved_views(con, log)
    if "build" in steps:
        for t, step in (("raw_wiki_pages", "wikipedia"), ("raw_qb_list_pages", "qb_lists"), ("raw_ap_award_pages", "qb_lists")):
            if not table_exists(con, t):
                raise SystemExit(f"build needs {t}; run `refresh --only {step}` first")
        pageviews._ensure_tables(con)
        run(con, "CREATE TABLE IF NOT EXISTS raw_pageviews_moved (title VARCHAR, old_title VARCHAR, month DATE, views BIGINT)")
        run(con, "CREATE TABLE IF NOT EXISTS raw_title_segments (title VARCHAR, segment_title VARCHAR, arrived_at TIMESTAMP, left_at TIMESTAMP)")
        n_pv = con.execute("SELECT count(*) FROM raw_pageviews_fetched").fetchall()[0][0]
        if n_pv == 0:
            log("warning: no pageviews cached yet; fame inputs will be 0 until `refresh --only pageviews` runs")
        build.build(con, log)
        run(con, "CREATE TABLE IF NOT EXISTS refresh_log (finished_at TIMESTAMP, steps VARCHAR)")
        run(con, "INSERT INTO refresh_log VALUES (?, ?)", [dt.datetime.now(), ",".join(steps)])
        print_coverage(con)
    log("done")


def print_coverage(con) -> None:
    rows = con.execute("SELECT * FROM coverage WHERE season % 5 = 0 OR season >= 1998 ORDER BY season").fetchall()
    cols = [d[0] for d in con.description]
    print("\n" + "  ".join(f"{c:>18}" for c in cols))
    for r in rows:
        print("  ".join(f"{v!s:>18}" for v in r))


if __name__ == "__main__":
    main()
