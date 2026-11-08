"""Wikimedia Pageviews API: monthly enwiki user pageviews per article (mid-2015+).

Resumable and incremental:
  * results are flushed to the DB every FLUSH articles, so a crash loses little
  * an article that fails after retries is skipped and retried next run
  * on later runs only months after each article's latest cached month are fetched
"""

from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import polars as pl

from ..db import run, write_table
from ..http import get

API = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user"
FIRST_MONTH = dt.date(2015, 7, 1)
FLUSH = 500


def _last_full_month(today: dt.date | None = None) -> dt.date:
    first = (today or dt.date.today()).replace(day=1)
    return (first - dt.timedelta(days=1)).replace(day=1)


def _next_month(d: dt.date) -> dt.date:
    return (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)


def _fetch(title: str, start: dt.date, end: dt.date) -> list[tuple[str, dt.date, int]] | None:
    """Rows for one article; [] if it has no data; None if the request failed."""
    end_day = _next_month(end) - dt.timedelta(days=1)  # last day: a 1-month range needs a full month
    url = f"{API}/{quote(title.replace(' ', '_'), safe='')}/monthly/{start:%Y%m%d}00/{end_day:%Y%m%d}00"
    try:
        r = get(url, ok404=True)
    except Exception:
        return None
    if r.status_code == 404:
        return []
    return [
        (title, dt.date(int(i["timestamp"][:4]), int(i["timestamp"][4:6]), 1), int(i["views"]))
        for i in r.json().get("items", [])
    ]


def _ensure_tables(con) -> None:
    run(con, "CREATE TABLE IF NOT EXISTS raw_pageviews (title VARCHAR, month DATE, views BIGINT)")
    # every article we've queried, and the last month the query covered (even if it had no views)
    run(con, "CREATE TABLE IF NOT EXISTS raw_pageviews_fetched (title VARCHAR PRIMARY KEY, through DATE)")


def refresh(con, titles: list[str], log=print, workers: int = 4) -> None:
    _ensure_tables(con)
    end = _last_full_month()
    through = dict(con.execute("SELECT title, through FROM raw_pageviews_fetched").fetchall())
    jobs = []
    for t in titles:
        start = _next_month(through[t]) if t in through else FIRST_MONTH
        if start <= end:
            jobs.append((t, start))
    log(f"pageviews: {len(jobs)} articles to fetch (through {end:%Y-%m})")

    failed = 0
    for i in range(0, len(jobs), FLUSH):
        chunk = jobs[i : i + FLUSH]
        with ThreadPoolExecutor(workers) as ex:
            results = list(ex.map(lambda j: _fetch(j[0], j[1], end), chunk))
        rows = [row for res in results if res for row in res]
        done = [(t, end) for (t, _), res in zip(chunk, results) if res is not None]
        failed += sum(res is None for res in results)
        if rows:
            df = pl.DataFrame(rows, schema={"title": pl.Utf8, "month": pl.Date, "views": pl.Int64}, orient="row")
            con.register("_pv", df.to_arrow())
            run(con, "INSERT INTO raw_pageviews SELECT * FROM _pv")
            con.unregister("_pv")
        if done:
            con.executemany(
                "INSERT INTO raw_pageviews_fetched VALUES (?, ?) "
                "ON CONFLICT (title) DO UPDATE SET through = excluded.through",
                done,
            )
        log(f"  {min(i + FLUSH, len(jobs))}/{len(jobs)} ({failed} failed, will retry next run)")


# ------------------------------------------------------------------ page moves
# The API counts views by exact title, so a rename splits an article's history.
# Only the pv24 window matters for fame (spec §7), so we only look at moves in it.

WIKI_API = "https://en.wikipedia.org/w/api.php"
WINDOW_MONTHS = 24


def window_start(end: dt.date | None = None) -> dt.date:
    end = end or _last_full_month()
    y, m = divmod(end.year * 12 + end.month - 1 - (WINDOW_MONTHS - 1), 12)
    return dt.date(y, m + 1, 1)


def refresh_moves(con, titles: list[str], log=print) -> None:
    """Article moves (namespace 0) since the window start that end at one of `titles`."""
    start = window_start()
    log(f"pageviews: reading the Wikipedia move log back to {start:%Y-%m}")
    moves: list[tuple[str, str, dt.datetime]] = []
    params = {"action": "query", "list": "logevents", "letype": "move", "lenamespace": "0", "lelimit": "500",
              "leprop": "title|details|timestamp", "leend": f"{start:%Y-%m-%d}T00:00:00Z",
              "format": "json", "formatversion": "2"}
    pages = 0
    while True:
        j = get(WIKI_API, params=params).json()
        for e in j.get("query", {}).get("logevents", []):
            tgt = e.get("params", {})
            if tgt.get("target_ns") == 0:
                # naive UTC: avoids DuckDB needing pytz for tz-aware values
                moves.append((e["title"], tgt["target_title"], dt.datetime.fromisoformat(e["timestamp"].rstrip("Z"))))
        pages += 1
        if pages % 200 == 0:
            log(f"  {pages} pages, {len(moves)} moves")
        if "continue" not in j:
            break
        params.update(j["continue"])

    # walk each article's history backwards; every title it held is valid from the
    # move that created it ("arrived") until the move that left it ("left")
    by_target: dict[str, list[tuple[str, dt.datetime]]] = {}
    for old, new, ts in moves:
        by_target.setdefault(new, []).append((old, ts))
    rows = []
    for t in titles:
        frontier = [(t, None)]  # (title, left_at); None = still current
        seen = {t}
        while frontier:
            cur, left = frontier.pop()
            into = [(old, ts) for old, ts in by_target.get(cur, []) if left is None or ts < left]
            arrived = max((ts for _, ts in into), default=None)
            if left is not None or arrived is not None:
                rows.append({"title": t, "segment_title": cur, "arrived_at": arrived, "left_at": left})
            for old, ts in into:
                if old not in seen:
                    seen.add(old)
                    frontier.append((old, ts))
    df = pl.DataFrame(rows, schema={"title": pl.Utf8, "segment_title": pl.Utf8,
                                    "arrived_at": pl.Datetime, "left_at": pl.Datetime})
    write_table(con, "raw_title_segments", df)
    log(f"  {len(moves)} moves in window; {df.filter(pl.col('left_at').is_not_null()).height} former titles "
        f"across {df['title'].n_unique()} player articles")


def refresh_moved_views(con, log=print, workers: int = 4) -> None:
    """Pageviews for each former title, for the window months while the article held it."""
    end = _last_full_month()
    start = window_start(end)
    jobs = []
    for title, seg, arrived, left in con.execute(
            "SELECT title, segment_title, arrived_at, left_at FROM raw_title_segments WHERE left_at IS NOT NULL").fetchall():
        first = max(start, arrived.date().replace(day=1)) if arrived else start
        last = min(end, left.date().replace(day=1))  # move month: views split between titles
        if first <= last:
            jobs.append((title, seg, first, last))
    log(f"pageviews: {len(jobs)} former titles to fetch")
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(lambda j: _fetch(j[1], j[2], j[3]), jobs))
    rows = [(t, seg, month, views) for (t, seg, _, _), r in zip(jobs, res) if r for (_, month, views) in r]
    df = pl.DataFrame(rows, schema={"title": pl.Utf8, "old_title": pl.Utf8, "month": pl.Date, "views": pl.Int64}, orient="row")
    write_table(con, "raw_pageviews_moved", df)
    log(f"  +{df.height} monthly rows from former titles ({sum(r is None for r in res)} failed; rerun to retry)")
