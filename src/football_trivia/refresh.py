"""`refresh`: pull every source into the local DuckDB cache, then derive tables.

    uv run refresh                 # everything
    uv run refresh --skip pageviews
    uv run refresh --only build    # re-derive from cached raw tables, no network
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import time

from . import build
from .db import connect, table_exists
from .sources import nflverse, pageviews, wikidata, wikipedia

STEPS = ["nflverse", "wikidata", "wikipedia", "pageviews", "build"]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="refresh", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", help="DuckDB path (default data/trivia.duckdb, or $FT_DB)")
    ap.add_argument("--only", nargs="+", choices=STEPS)
    ap.add_argument("--skip", nargs="+", choices=STEPS, default=[])
    args = ap.parse_args(argv)
    steps = [s for s in (args.only or STEPS) if s not in args.skip]

    if {"wikidata", "wikipedia", "pageviews"} & set(steps) and "FT_CONTACT" not in os.environ:
        print("warning: FT_CONTACT not set; Wikimedia asks for contact info in the User-Agent")

    t0 = time.time()
    log = lambda m: print(f"[{time.time() - t0:6.0f}s] {m}", flush=True)
    con = connect(args.db)

    if "nflverse" in steps:
        nflverse.refresh(con, log)
    if "wikidata" in steps:
        wikidata.refresh(con, log)
    if {"wikipedia", "pageviews"} & set(steps):
        build.build_identity(con, log)
        titles = [t for (t,) in con.execute("SELECT DISTINCT wiki_title FROM players WHERE wiki_title IS NOT NULL ORDER BY 1").fetchall()]
        if "wikipedia" in steps:
            wikipedia.refresh(con, titles, log)
        if "pageviews" in steps:
            pageviews.refresh(con, titles, log)
    if "build" in steps:
        missing = [t for t in ("raw_wiki_pages", "raw_pageviews") if not table_exists(con, t)]
        if missing:
            raise SystemExit(f"build needs {missing}; run without --only first")
        build.build(con, log)
        con.execute("CREATE TABLE IF NOT EXISTS refresh_log (finished_at TIMESTAMP, steps VARCHAR)")
        con.execute("INSERT INTO refresh_log VALUES (?, ?)", [dt.datetime.now(), ",".join(steps)])
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
