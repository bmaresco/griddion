"""AP award winners from Wikipedia's dedicated AP award pages (CC BY-SA).

Spec §5: awards are AP only. Player infoboxes often list other bodies' versions
without saying so (e.g. Unitas's 1964 MVP was UPI's; AP's went to Lenny Moore),
so the six AP awards come from these season-by-season tables instead.
"""

from __future__ import annotations

import re

import polars as pl
from bs4 import BeautifulSoup

from ..db import write_table
from ..http import get
from .qb_lists import _grid, _heading_before, _text

API = "https://en.wikipedia.org/w/api.php"
# award -> (page, regex the table's section heading must match)
PAGES = {
    "mvp": ("AP NFL Most Valuable Player", r"^Winners"),
    "opoy": ("AP NFL Offensive Player of the Year", r"^Winners"),
    "dpoy": ("AP NFL Defensive Player of the Year", r"^Winners"),
    "oroy": ("AP NFL Rookie of the Year", r"^Offensive"),
    "droy": ("AP NFL Rookie of the Year", r"^Defensive"),
    "comeback": ("AP NFL Comeback Player of the Year", r"^1998"),
}


def refresh(con, log=print) -> None:
    log("wikipedia: AP award pages")
    rows, pages = [], {}
    for award, (page, _) in PAGES.items():
        if page not in pages:
            j = get(API, params={"action": "parse", "page": page, "prop": "text|revid",
                                 "format": "json", "formatversion": "2", "redirects": "1"}).json()
            pages[page] = (j["parse"]["revid"], j["parse"]["text"])
    for page, (revid, html) in pages.items():
        rows.append({"page": page, "revid": revid, "html": html})
    write_table(con, "raw_ap_award_pages", pl.DataFrame(rows))

    titles = sorted({r["wiki_title"] for r in parse_all(con).iter_rows(named=True) if r["wiki_title"]})
    out = []
    for i in range(0, len(titles), 50):
        q = get(API, params={"action": "query", "format": "json", "formatversion": "2", "redirects": "1",
                             "titles": "|".join(titles[i:i + 50])}).json().get("query", {})
        hop = {m["from"]: m["to"] for k in ("normalized", "redirects") for m in q.get(k, [])}
        for t in titles[i:i + 50]:
            c = t
            for _ in range(3):
                c = hop.get(c, c)
            out.append({"link_title": t, "canonical_title": c})
    write_table(con, "raw_ap_award_redirects", pl.DataFrame(out))
    log(f"  {len(titles)} winner links resolved")


def parse_page(html: str, heading_re: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for table in soup.select("table.wikitable"):
        if not re.search(heading_re, _heading_before(table)):
            continue
        grid = _grid(table)
        header = [_text(c).lower() for c in grid[0]]
        if "season" not in header or "player" not in header:
            continue
        sc, pc = header.index("season"), header.index("player")
        for r in grid[1:]:
            if len(r) <= max(sc, pc):
                continue
            m = re.match(r"(\d{4})", _text(r[sc]))
            if not m:
                continue
            for a in r[pc].find_all("a"):
                t = a.get("title")
                if t and not t.startswith(("File:", "Help:")) and "Hall of Fame" not in t:
                    out.append({"season": int(m.group(1)), "wiki_title": t, "name": a.get_text(" ", strip=True)})
        break  # first matching table only
    return out


def parse_all(con) -> pl.DataFrame:
    pages = {p: html for p, html in con.execute("SELECT page, html FROM raw_ap_award_pages").fetchall()}
    rows = [{"award": award, **r} for award, (page, hre) in PAGES.items() for r in parse_page(pages[page], hre)]
    return pl.DataFrame(rows, schema={"award": pl.Utf8, "season": pl.Int32, "wiki_title": pl.Utf8, "name": pl.Utf8})
