"""Wikimedia Pageviews API: monthly enwiki user pageviews per article (mid-2015+).

Incremental: only months after each article's latest cached month are fetched.
"""

from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import polars as pl

from ..db import table_exists, write_table
from ..http import get

API = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user"
FIRST_MONTH = dt.date(2015, 7, 1)


def _last_full_month(today: dt.date | None = None) -> dt.date:
    today = today or dt.date.today()
    first = today.replace(day=1)
    return (first - dt.timedelta(days=1)).replace(day=1)


def _fetch(title: str, start: dt.date, end: dt.date) -> list[tuple[str, dt.date, int]]:
    url = f"{API}/{quote(title.replace(' ', '_'), safe='')}/monthly/{start:%Y%m%d}00/{end:%Y%m%d}00"
    r = get(url, ok404=True)
    if r.status_code == 404:
        return []
    return [
        (title, dt.date(int(i["timestamp"][:4]), int(i["timestamp"][4:6]), 1), int(i["views"]))
        for i in r.json().get("items", [])
    ]


def refresh(con, titles: list[str], log=print, workers: int = 8) -> None:
    end = _last_full_month()
    have: dict[str, dt.date] = {}
    if table_exists(con, "raw_pageviews"):
        have = dict(con.execute("SELECT title, max(month) FROM raw_pageviews GROUP BY title").fetchall())
        fetched = {t for (t,) in con.execute("SELECT title FROM raw_pageviews_fetched").fetchall()} \
            if table_exists(con, "raw_pageviews_fetched") else set()
    else:
        fetched = set()

    jobs = []
    for t in titles:
        if t in have:
            start = (have[t].replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        elif t in fetched:  # previously fetched, had no data; only check new months
            continue
        else:
            start = FIRST_MONTH
        if start <= end:
            jobs.append((t, start))
    log(f"pageviews: {len(jobs)} articles to fetch (through {end:%Y-%m})")

    rows: list[tuple] = []
    with ThreadPoolExecutor(workers) as ex:
        futs = ex.map(lambda j: _fetch(j[0], j[1], end), jobs)
        for i, res in enumerate(futs, 1):
            rows.extend(res)
            if i % 2000 == 0:
                log(f"  {i}/{len(jobs)}")

    new = pl.DataFrame(rows, schema={"title": pl.Utf8, "month": pl.Date, "views": pl.Int64}, orient="row")
    if table_exists(con, "raw_pageviews"):
        con.register("_new", new.to_arrow())
        con.execute("INSERT INTO raw_pageviews SELECT * FROM _new")
        con.unregister("_new")
    else:
        write_table(con, "raw_pageviews", new)
    done = pl.DataFrame({"title": sorted(fetched | {t for t, _ in jobs})})
    write_table(con, "raw_pageviews_fetched", done)
    log(f"  +{new.height} monthly rows")
