"""Award winners from Wikipedia's dedicated award list pages (CC BY-SA).

Spec §5: awards are AP only. Player infoboxes often list other bodies' versions
without saying so (e.g. Unitas's 1964 MVP was UPI's; AP's went to Lenny Moore),
so the six AP awards come from these season-by-season tables instead. Super Bowl
MVP and the Heisman Trophy (added 2026-11-11, §5 honors) have one list page each,
which is the whole record.
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
    "sb_mvp": ("Super Bowl Most Valuable Player Award", r"^Winners"),
    "heisman": ("List of Heisman Trophy winners", r"^List"),
}
HOF_PAGE = "List of Pro Football Hall of Fame inductees"
# AP first-team All-Pro by season, with the position slot ("{season} All-Pro Team" pages). The pages
# parse from 1968 (AP's AFL and NFL teams in 1968-69, one team from 1970); 1960-67 use another layout.
ALL_PRO_FIRST_SEASON = 1968


def all_pro_pages(last: int) -> list[str]:
    return [f"{y} All-Pro Team" for y in range(ALL_PRO_FIRST_SEASON, last + 1)]  # players vs coaches/contributors, inducted position
# award -> (season column, player column, offset to the NFL/college season). Default: season, player, 0.
# Super Bowl MVP lists the game's calendar year (Super Bowl I: 1967 = the 1966 season).
COLUMNS = {"sb_mvp": ("year", "winner", -1), "heisman": ("year", "name", 0)}


def refresh(con, log=print, last_season: int | None = None) -> None:
    import datetime as dt
    log("wikipedia: award list pages, HOF inductees, All-Pro teams")
    last = last_season or (dt.date.today().year - (1 if dt.date.today().month >= 2 else 2))
    rows, pages = [], {}
    for page in [p for p, _ in PAGES.values()] + [HOF_PAGE] + all_pro_pages(last):
        if page not in pages:
            j = get(API, params={"action": "parse", "page": page, "prop": "text|revid",
                                 "format": "json", "formatversion": "2", "redirects": "1"}, ok404=True).json()
            if "parse" not in j:
                log(f"  missing page: {page}")
                continue
            pages[page] = (j["parse"]["revid"], j["parse"]["text"])
    for page, (revid, html) in pages.items():
        rows.append({"page": page, "revid": revid, "html": html})
    write_table(con, "raw_ap_award_pages", pl.DataFrame(rows))

    titles = sorted({r["wiki_title"] for r in parse_all(con).iter_rows(named=True) if r["wiki_title"]}
                    | {r["wiki_title"] for r in parse_hof(con).iter_rows(named=True)}
                    | {r["wiki_title"] for r in parse_all_pro(con).iter_rows(named=True)})
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


def parse_page(html: str, heading_re: str, season_col: str = "season", player_col: str = "player",
               offset: int = 0) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for table in soup.select("table.wikitable"):
        if not re.search(heading_re, _heading_before(table)):
            continue
        grid = _grid(table)
        header = [_text(c).lower() for c in grid[0]]
        if season_col not in header or player_col not in header:
            continue
        sc, pc = header.index(season_col), header.index(player_col)
        for r in grid[1:]:
            if len(r) <= max(sc, pc):
                continue
            m = re.match(r"(\d{4})", _text(r[sc]))
            if not m:
                continue
            for a in r[pc].find_all("a"):
                t = a.get("title")
                if t and not t.startswith(("File:", "Help:")) and "Hall of Fame" not in t:
                    out.append({"season": int(m.group(1)) + offset, "wiki_title": t, "name": a.get_text(" ", strip=True)})
        break  # first matching table only
    return out


def parse_all(con) -> pl.DataFrame:
    pages = {p: html for p, html in con.execute("SELECT page, html FROM raw_ap_award_pages").fetchall()}
    rows = [{"award": award, **r} for award, (page, hre) in PAGES.items() if page in pages
            for r in parse_page(pages[page], hre, *COLUMNS.get(award, ("season", "player", 0)))]
    return pl.DataFrame(rows, schema={"award": pl.Utf8, "season": pl.Int32, "wiki_title": pl.Utf8, "name": pl.Utf8})


# --------------------------------------------------------------- Hall of Fame
# inducted-position phrases -> position group, longest first so "defensive end" beats "end".
# Anything else (coach, owner, general manager, commissioner, founder, contributor, ...) is not a
# playing position; an inductee with no playing position was inducted as a non-player.
HOF_POSITIONS = [
    ("defensive middle guard", "DL"), ("defensive lineman", "DL"), ("defensive end", "DL"),
    ("defensive tackle", "DL"), ("nose tackle", "DL"), ("defensive back", "DB"),
    ("outside linebacker", "LB"), ("middle linebacker", "LB"), ("linebacker", "LB"),
    ("offensive tackle", "OL"), ("offensive end", "WR"), ("wide receiver", "WR"), ("tight end", "TE"),
    ("running back", "RB"), ("quarterback", "QB"), ("placekicker", "K"), ("free safety", "DB"),
    ("cornerback", "DB"), ("halfback", "RB"), ("fullback", "RB"), ("flanker", "WR"), ("safety", "DB"),
    ("tackle", "OL"), ("guard", "OL"), ("center", "OL"), ("kicker", "K"), ("punter", "P"), ("end", "WR"),
]
_HOF_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k, _ in HOF_POSITIONS) + r")\b")


def hof_groups(position: str) -> list[str]:
    """'Defensive end/linebacker' -> ['DL', 'LB']; 'Coach' -> []. Return roles are skipped."""
    pos = re.sub(r"(kick|punt|kickoff)\s*(/\s*punt\s*)?returner|return specialist", "", position.lower())
    # "Defensive tackle/end": a bare end/tackle/guard after a "defensive"/"offensive" segment keeps it
    segs, side = [], ""
    for seg in pos.split("/"):
        seg = seg.strip()
        if m := re.match(r"(defensive|offensive)\b", seg):
            side = m.group(1)
        elif side and re.match(r"(end|tackle|guard)\b", seg):
            seg = f"{side} {seg}"
        segs.append(seg)
    g = dict(HOF_POSITIONS)
    return list(dict.fromkeys(g[m] for m in _HOF_RE.findall(" / ".join(segs))))


def parse_hof(con) -> pl.DataFrame:
    """One row per inductee x listed position: wiki_title, name, class, position (as inducted)."""
    rows = con.execute("SELECT html FROM raw_ap_award_pages WHERE page = ?", [HOF_PAGE]).fetchall()
    row = rows[0] if rows else None
    out = []
    if row:
        soup = BeautifulSoup(row[0], "lxml")
        for table in soup.select("table.wikitable"):
            grid = _grid(table)
            header = [_text(c).lower() for c in grid[0]]
            if not {"inductee", "class", "position"} <= set(header):
                continue
            ic, cc, pc = header.index("inductee"), header.index("class"), header.index("position")
            for r in grid[1:]:
                if len(r) <= max(ic, cc, pc):
                    continue
                a = next((a for a in r[ic].find_all("a") if a.get("title") and not a["title"].startswith(("File:", "Help:"))), None)
                m = re.match(r"(\d{4})", _text(r[cc]))
                if a and m:
                    out.append({"wiki_title": a["title"], "name": a.get_text(" ", strip=True),
                                "class": int(m.group(1)), "position": _text(r[pc])})
            break  # the NFL inductees table; the non-NFL-teams table repeats the same people
    return pl.DataFrame(out, schema={"wiki_title": pl.Utf8, "name": pl.Utf8, "class": pl.Int32, "position": pl.Utf8}).unique()


# ------------------------------------------------------------ AP All-Pro teams
# position slot -> group; None = special teams / returner / long snapper (no positional group);
# "roster" = the player's listed group that season (edge rusher: DE or OLB; flex)
ALL_PRO_SLOTS = [
    ("edge rusher", "roster"), ("flex", "roster"), ("all-purpose", None),
    ("returner", None), ("special team", None), ("long snapper", None),
    ("interior lineman", "DL"), ("defensive end", "DL"), ("defensive tackle", "DL"), ("nose tackle", "DL"),
    ("linebacker", "LB"), ("cornerback", "DB"), ("safety", "DB"), ("defensive back", "DB"),
    ("quarterback", "QB"), ("running back", "RB"), ("halfback", "RB"), ("fullback", "RB"),
    ("wide receiver", "WR"), ("flanker", "WR"), ("split end", "WR"), ("tight end", "TE"),
    ("tackle", "OL"), ("guard", "OL"), ("center", "OL"), ("kicker", "K"), ("punter", "P"),
]


def all_pro_group(label: str) -> str | None:
    lab = label.lower()
    return next((g for k, g in ALL_PRO_SLOTS if k in lab), None)


def parse_all_pro_page(html: str) -> list[dict]:
    """AP first-team selections: [{slot, wiki_title, name}]. A "First team" cell lists one player
    per <br> chunk as "Name, Team (AP, PFWA, ...)"; AP second team is "AP-2"."""
    soup = BeautifulSoup(html, "lxml")
    out = []
    for table in soup.select("table.wikitable"):
        grid = _grid(table)
        hdr = None
        for i, r in enumerate(grid[:3]):
            h = [_text(c).lower() for c in r]
            if "position" in h and any("first" in x for x in h):
                hdr = (i, h.index("position"), next(k for k, x in enumerate(h) if "first" in x))
                break
        if not hdr:
            continue
        i0, pc, fc = hdr
        for r in grid[i0 + 1:]:
            if len(r) <= max(pc, fc):
                continue
            slot = re.sub(r"\s*\[\w\]", "", _text(r[pc])).strip()
            for chunk in re.split(r"<br\s*/?>", str(r[fc])):
                cs = BeautifulSoup(chunk, "lxml")
                m = re.search(r"\(([^)]*)\)", cs.get_text(" ", strip=True))
                if not m or "AP" not in [x.strip() for x in m.group(1).split(",")]:
                    continue
                a = next((a for a in cs.find_all("a") if a.get("title") and not re.match(r"\d{4} ", a["title"])
                          and not a["title"].startswith(("File:", "Help:"))), None)
                if a:
                    out.append({"slot": slot, "wiki_title": a["title"], "name": a.get_text(" ", strip=True)})
    return out


def parse_all_pro(con) -> pl.DataFrame:
    rows = con.execute("SELECT page, html FROM raw_ap_award_pages WHERE page LIKE '% All-Pro Team'").fetchall()
    out = [{"season": int(page[:4]), **r} for page, html in rows for r in parse_all_pro_page(html)]
    return pl.DataFrame(out, schema={"season": pl.Int32, "slot": pl.Utf8, "wiki_title": pl.Utf8, "name": pl.Utf8}).unique()
