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

from ..db import run
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
    url = f"{API}/{quote(title.replace(' ', '_'), safe='')}/monthly/{start:%Y%m%d}00/{end:%Y%m%d}00"
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
