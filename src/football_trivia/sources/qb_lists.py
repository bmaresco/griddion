"""Wikipedia "List of <team> starting quarterbacks" pages (CC BY-SA), all 32 franchises.

Used for QB starts before 1999 (nflverse covers 1999+). Pages come in three layouts:

  * season rows, QB cell "Joe Montana (15) / Matt Cavanaugh (1)"   -> basis 'games'
  * season rows, QB cell "Danny White (10–4) / Gary Hogeboom (0–2)" -> basis 'record' (W+L+T)
  * one row per QB: seasons with a start + total starts (GB, LA)    -> basis 'split'
    (total spread evenly over the listed seasons; flagged as an estimate)
  * a lone QB listed with no count started every game                -> basis 'sole'

Tables under a Postseason/Playoffs heading, and postseason columns, are skipped.
Raw HTML is cached in raw_qb_list_pages so parser fixes never need a re-fetch.
"""

from __future__ import annotations

import re

import polars as pl
from bs4 import BeautifulSoup, Tag

from ..db import write_table
from ..http import get

API = "https://en.wikipedia.org/w/api.php"
_POST = re.compile(r"post-?season|playoff", re.I)
_NOT_STARTS = re.compile(r"pro bowl|selection|award|honou?r|record|leader|hall of fame|statistic|most games|retired", re.I)
_NOT_A_PLAYER = re.compile(r"suspended|operations|no team|did not play|strike", re.I)
AFL_FRANCHISES = {"BUF", "DEN", "KC", "LAC", "LV", "NE", "NYJ", "TEN", "MIA", "CIN"}


def season_games(season: int, franchise: str | None = None) -> int:
    """Regular-season games per team, 1950-1998 (used for checks and sole starters)."""
    if season <= 1960:
        return 14 if (season == 1960 and franchise in AFL_FRANCHISES) else 12
    if season <= 1977:
        return 14
    return {1982: 9, 1987: 15}.get(season, 16)
_DASH = r"[–\-−]"


# --------------------------------------------------------------------- fetch

def refresh(con, log=print) -> None:
    teams = con.execute(
        "SELECT team_abbr, team_name FROM raw_teams WHERE team_abbr NOT IN ('OAK','SD','STL','LAR') ORDER BY 1"
    ).fetchall()
    log(f"wikipedia: starting-QB lists for {len(teams)} franchises")
    rows = []
    for abbr, name in teams:
        j = get(API, params={"action": "parse", "page": f"List of {name} starting quarterbacks",
                             "prop": "text|revid", "format": "json", "formatversion": "2", "redirects": "1"}).json()
        if "error" in j:
            log(f"  {abbr}: page missing")
            continue
        rows.append({"franchise": abbr, "title": j["parse"]["title"], "revid": j["parse"]["revid"], "html": j["parse"]["text"]})
    write_table(con, "raw_qb_list_pages", pl.DataFrame(rows))


# --------------------------------------------------------------------- parse

def _grid(table: Tag) -> list[list[Tag | None]]:
    """Expand rowspan/colspan so every row has one entry per column."""
    grid: list[list[Tag | None]] = []
    pending: dict[int, tuple[Tag, int]] = {}  # col -> (cell, rows remaining)
    for tr in table.find_all("tr"):
        row: list[Tag | None] = []
        cells = tr.find_all(["td", "th"], recursive=False)
        col = 0
        it = iter(cells)
        while True:
            if col in pending:
                cell, left = pending[col]
                row.append(cell)
                pending[col] = (cell, left - 1) if left > 1 else None
                if pending[col] is None:
                    del pending[col]
                col += 1
                continue
            cell = next(it, None)
            if cell is None:
                break
            rs = int(re.sub(r"\D", "", cell.get("rowspan", "1")) or 1)
            cs = int(re.sub(r"\D", "", cell.get("colspan", "1")) or 1)
            for k in range(cs):
                row.append(cell)
                if rs > 1:
                    pending[col + k] = (cell, rs - 1)
            col += cs
        grid.append(row)
    return grid


def _heading_before(table: Tag) -> str:
    h = table.find_previous(["h2", "h3", "h4"])
    return h.get_text(" ", strip=True) if h else ""


def _text(cell: Tag | None) -> str:
    if cell is None:
        return ""
    c = BeautifulSoup(str(cell), "lxml")
    for s in c.select("sup.reference, .sortkey, style"):
        s.decompose()
    return c.get_text(" ", strip=True)


def _years(s: str) -> list[int]:
    """'1985' -> [1985]; '1950–1952' -> [1950,1951,1952]; '1976–77, 79–85' -> expanded."""
    out: list[int] = []
    century = None
    for a, b in re.findall(rf"(\d{{2,4}})(?:\s*{_DASH}\s*(\d{{2,4}}))?", s):
        a_i = int(a)
        if len(a) == 4:
            century = a_i // 100 * 100
        elif century is not None:
            a_i = century + a_i if century + a_i >= (out[-1] if out else 0) else century + 100 + a_i
        else:
            continue
        if b:
            b_i = int(b)
            if len(b) == 2:
                b_i = a_i // 100 * 100 + b_i
                if b_i < a_i:
                    b_i += 100
            out.extend(range(a_i, b_i + 1))
        else:
            out.append(a_i)
        century = out[-1] // 100 * 100
    return [y for y in out if 1900 < y < 2100]


def _qb_entries(cell: Tag) -> list[tuple[str | None, str, int | None, str]]:
    """QB cell -> [(wiki_title, name, starts, basis)]."""
    c = BeautifulSoup(str(cell), "lxml")
    for s in c.select("sup.reference, style"):
        s.decompose()
    html = str(c)
    parts = re.split(r"\s/\s|<br\s*/?>|\s/(?=\s*<a)|(?<=</small>)\s*/", html)
    out = []
    for part in parts:
        p = BeautifulSoup(part, "lxml")
        link = next((a for a in p.find_all("a") if a.get("title") and "season" not in a["title"].lower()
                     and not a["title"].startswith(("File:", "Pro Football Hall", "Help:"))), None)
        text = p.get_text(" ", strip=True)
        name = link.get_text(" ", strip=True) if link else re.sub(r"\(.*?\)|[†‡*^#]", "", text).strip()
        if not name or not re.search(r"[A-Za-z]", name) or (not link and _NOT_A_PLAYER.search(name)):
            continue
        title = link["title"] if link else None
        if m := re.search(rf"\(\s*(\d+)\s*{_DASH}\s*(\d+)(?:\s*{_DASH}\s*(\d+))?\s*\)", text):
            out.append((title, name, sum(int(x) for x in m.groups() if x), "record"))
        elif m := re.search(r"\(\s*(\d+)\s*\)", text):
            out.append((title, name, int(m.group(1)), "games"))
        else:
            out.append((title, name, None, "unknown"))
    return out


def _find_col(header: list[str], *pats: str, avoid: str = r"$^") -> int | None:
    for i, h in enumerate(header):
        if any(re.search(p, h, re.I) for p in pats) and not re.search(avoid, h, re.I):
            return i
    return None


def parse_page(html: str, franchise: str | None = None) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict] = []
    for t_idx, table in enumerate(soup.select("table.wikitable")):
        heading = _heading_before(table)
        if _POST.search(heading) or _NOT_STARTS.search(heading):
            continue
        grid = _grid(table)
        if not grid:
            continue
        header = [_text(c) for c in grid[0]]
        season_col = _find_col(header, r"^season", r"^year", avoid=r"with|at least|selected")
        qb_col = _find_col(header, r"regular", r"quarterback")
        per_qb = _find_col(header, r"at least one") is not None and _find_col(header, r"games started|^starts|^gs$") is not None
        if per_qb:
            name_col = _find_col(header, r"quarterback")
            seasons_col = _find_col(header, r"at least one")
            gs_col = _find_col(header, r"games started|^starts|^gs$")
            for r in grid[1:]:
                if len(r) <= max(name_col, seasons_col, gs_col):
                    continue
                ents = _qb_entries(r[name_col])
                yrs = _years(_text(r[seasons_col]))
                total = re.match(r"\d+", _text(r[gs_col]))
                if not ents or not yrs or not total:
                    continue
                title, name, _, _ = ents[0]
                for y in yrs:
                    rows.append({"season": y, "wiki_title": title, "name": name,
                                 "starts": int(total.group()) / len(yrs), "basis": "split", "table": t_idx})
            continue
        if all(c is grid[0][0] for c in grid[0]):
            # one title cell spanning every column (NO): season | regular season | postseason | refs
            season_col, qb_col = 0, 1
            qb_cols = [1]
        elif season_col is None or qb_col is None or _POST.search(header[qb_col]):
            continue
        else:
            qb_cols = [i for i, c in enumerate(grid[0]) if c is grid[0][qb_col]]
        for r in grid[1:]:
            if len(r) <= max(season_col, qb_col) or r[season_col] is r[qb_col]:
                continue  # era sub-header spanning the row
            yrs = _years(_text(r[season_col]))
            if not yrs:
                continue
            ents, seen = [], set()
            for i in qb_cols:
                if i < len(r) and r[i] is not None and id(r[i]) not in seen:
                    seen.add(id(r[i]))
                    ents.extend(_qb_entries(r[i]))
            if len(ents) == 1 and ents[0][2] is None:
                # a lone starter listed without a count started every game that season
                title, name, _, _ = ents[0]
                for y in yrs:
                    rows.append({"season": y, "wiki_title": title, "name": name,
                                 "starts": float(season_games(y, franchise)), "basis": "sole", "table": t_idx})
                continue
            for title, name, starts, basis in ents:
                for y in yrs:
                    # a count on a multi-season row is a total; spread it like 'split'
                    s, b = (starts / len(yrs), "split") if (starts is not None and len(yrs) > 1) else (starts, basis)
                    rows.append({"season": y, "wiki_title": title, "name": name, "starts": s, "basis": b, "table": t_idx})
    return rows


def parse_all(con) -> pl.DataFrame:
    out = []
    for franchise, title, revid, html in con.execute("SELECT franchise, title, revid, html FROM raw_qb_list_pages").fetchall():
        for r in parse_page(html, franchise):
            out.append({"franchise": franchise, "page": title, "revid": revid, **r})
    return pl.DataFrame(out, schema={"franchise": pl.Utf8, "page": pl.Utf8, "revid": pl.Int64, "season": pl.Int32,
                                     "wiki_title": pl.Utf8, "name": pl.Utf8, "starts": pl.Float64,
                                     "basis": pl.Utf8, "table": pl.Int32})


# ------------------------------------------------------------ link redirects

def refresh_redirects(con, log=print) -> None:
    """Canonical titles for every QB link (pages often link via redirects)."""
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
    write_table(con, "raw_qb_list_redirects", pl.DataFrame(out))
    log(f"  {len(out)} QB link titles resolved")


# --------------------------------------------------------------------- build

# Cross-check runs through the current season: in-season page lag is exactly what
# §3 wants flagged (in /probe and the diff report), never silently resolved.


def build(con, log=print) -> None:
    """qb_list_starts (parsed + matched), qb_season_starts (merged), qb_list_crosscheck, qb_list_checks."""
    from ..names import norm_name

    df = parse_all(con)
    redirects = dict(con.execute("SELECT link_title, canonical_title FROM raw_qb_list_redirects").fetchall())
    by_title = {t: pid for pid, t in con.execute(
        "SELECT player_id, wiki_title FROM players WHERE wiki_title IS NOT NULL").fetchall()}
    # fallback: same normalized name on that franchise's roster that season (QB preferred)
    roster = {}
    for pid, name, fr, season, pos in con.execute("""
            SELECT s.player_id, p.display_name, s.franchise, s.season, s.position
            FROM player_seasons s JOIN players p USING (player_id) WHERE s.franchise IS NOT NULL""").fetchall():
        roster.setdefault((norm_name(name), fr, season), []).append((pos == "QB", pid))

    def match(title, name, franchise, season):
        if title:
            pid = by_title.get(redirects.get(title, title)) or by_title.get(title)
            if pid:
                return pid, "wiki_title"
        cands = sorted(set(roster.get((norm_name(name), franchise, season), [])), reverse=True)
        if cands and (len(cands) == 1 or cands[0][0] != cands[1][0]):
            return cands[0][1], "roster_name"
        return None, "unmatched"

    m = [match(*r) for r in df.select("wiki_title", "name", "franchise", "season").iter_rows()]
    df = df.with_columns(player_id=pl.Series([x[0] for x in m], dtype=pl.Utf8),
                         match=pl.Series([x[1] for x in m], dtype=pl.Utf8))
    write_table(con, "qb_list_starts", df)

    con.execute("""
    CREATE OR REPLACE TABLE qb_season_starts AS
    SELECT player_id, franchise, season, sum(starts) AS starts, 'wikipedia' AS source,
           string_agg(DISTINCT basis, ',') AS basis
    FROM qb_list_starts WHERE season < 1999 AND player_id IS NOT NULL
    GROUP BY ALL
    UNION ALL
    SELECT player_id, franchise, season, count(*)::DOUBLE, 'nflverse', 'games'
    FROM qb_starts WHERE game_type = 'REG' AND franchise IS NOT NULL
    GROUP BY ALL
    """).fetchall()

    con.execute(f"""
    CREATE OR REPLACE TABLE qb_list_crosscheck AS
    WITH w AS (SELECT player_id, franchise, season, sum(starts) starts, any_value(name) name,
                      bool_or(basis = 'split') estimated
               FROM qb_list_starts WHERE season >= 1999
               GROUP BY ALL),
         n AS (SELECT player_id, franchise, season, count(*)::DOUBLE starts
               FROM qb_starts WHERE game_type = 'REG' AND season >= 1999 GROUP BY ALL)
    SELECT coalesce(w.franchise, n.franchise) franchise, coalesce(w.season, n.season) season,
           coalesce(w.player_id, n.player_id) player_id, w.name wiki_name,
           w.starts wiki_starts, n.starts nflverse_starts,
           CASE WHEN w.player_id IS NULL THEN 'missing_in_wikipedia'
                WHEN n.player_id IS NULL THEN 'missing_in_nflverse'
                WHEN w.estimated THEN 'match_estimated'
                WHEN round(w.starts) = n.starts THEN 'match'
                ELSE 'count_differs' END AS status
    FROM w FULL JOIN n ON w.player_id = n.player_id AND w.franchise = n.franchise AND w.season = n.season
    """).fetchall()

    # pre-1999 self-check: starts per team-season should equal games played
    sums = df.filter((pl.col("season") < 1999) & (pl.col("basis") != "split")).group_by("franchise", "season").agg(
        pl.col("starts").sum().alias("starts"), pl.col("starts").is_null().any().alias("has_unknown"))
    sums = sums.with_columns(expected=pl.struct("season", "franchise").map_elements(
        lambda r: season_games(r["season"], r["franchise"]), return_dtype=pl.Int64))
    checks = sums.filter(pl.col("has_unknown") | (pl.col("starts").round(0) != pl.col("expected"))).sort("franchise", "season")
    write_table(con, "qb_list_checks", checks)

    unmatched = df.filter(pl.col("player_id").is_null())
    cc = dict(con.execute("SELECT status, count(*) FROM qb_list_crosscheck GROUP BY 1").fetchall())
    pre = con.execute("SELECT count(*), count(DISTINCT player_id), min(season) FROM qb_season_starts WHERE source='wikipedia'").fetchall()[0]
    log(f"  qb lists: {df.height} rows parsed, {unmatched.height} unmatched to a player")
    log(f"  pre-1999 QB seasons: {pre[0]} rows, {pre[1]} QBs, from {pre[2]}; {checks.height} team-seasons fail the games check")
    log(f"  1999-now cross-check vs nflverse: {cc}")
