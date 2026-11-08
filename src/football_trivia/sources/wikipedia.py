"""Wikipedia (CC BY-SA): honors from each player's infobox `highlights` field,
and Hall of Fame status from article categories.

Raw wikitext highlights are cached in raw_wiki_pages; parsing happens in
parse_highlights() so parser fixes never need a re-fetch.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

import polars as pl

from ..db import write_table
from ..http import get

API = "https://en.wikipedia.org/w/api.php"
HOF_CATEGORY = "Category:Pro Football Hall of Fame inductees"
BATCH = 50  # API max for prop=revisions content on multiple titles

_HIGHLIGHTS_RE = re.compile(r"\|\s*highlights\s*=(.*?)(?=\n\s*\|\s*[a-z_]+\s*=|\n\}\})", re.S | re.I)


# --------------------------------------------------------------------- fetch

def _fetch_batch(titles: list[str]) -> list[dict]:
    r = get(
        API,
        params={
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "prop": "revisions|categories",
            "rvprop": "content|ids",
            "rvslots": "main",
            "clcategories": HOF_CATEGORY,
            "cllimit": "max",
            "redirects": "1",
            "titles": "|".join(titles),
        },
    )
    q = r.json().get("query", {})
    # map normalized/redirected titles back to the title we asked for
    back = {}
    for k in ("normalized", "redirects"):
        for m in q.get(k, []):
            back[m["to"]] = back.get(m["from"], m["from"])
    out = []
    for p in q.get("pages", []):
        if p.get("missing") or "revisions" not in p:
            continue
        content = p["revisions"][0]["slots"]["main"]["content"]
        m = _HIGHLIGHTS_RE.search(content)
        out.append(
            {
                "title": back.get(p["title"], p["title"]),
                "resolved_title": p["title"],
                "revid": p["revisions"][0]["revid"],
                "highlights": m.group(1).strip() if m else None,
                "is_hof": bool(p.get("categories")),
            }
        )
    return out


def refresh(con, titles: list[str], log=print, workers: int = 4) -> None:
    log(f"wikipedia: fetching infoboxes for {len(titles)} articles")
    batches = [titles[i : i + BATCH] for i in range(0, len(titles), BATCH)]
    rows: list[dict] = []
    with ThreadPoolExecutor(workers) as ex:
        for i, res in enumerate(ex.map(_fetch_batch, batches), 1):
            rows.extend(res)
            if i % 100 == 0:
                log(f"  {i}/{len(batches)} batches")
    df = pl.DataFrame(
        rows,
        schema={"title": pl.Utf8, "resolved_title": pl.Utf8, "revid": pl.Int64, "highlights": pl.Utf8, "is_hof": pl.Boolean},
    ).unique("title")
    write_table(con, "raw_wiki_pages", df)
    log(f"  {df.height} pages, {df['highlights'].is_not_null().sum()} with highlights, {df['is_hof'].sum()} HOF")


# --------------------------------------------------------------------- parse

def clean_wikitext(s: str) -> str:
    s = re.sub(r"<ref[^>]*/>", "", s)
    s = re.sub(r"<ref.*?</ref>", "", s, flags=re.S)
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = re.sub(r"<br\s*/?>", "\n", s)
    for _ in range(3):  # nested templates
        s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"\[\[([^\]]*)\]\]", r"\1", s)
    s = s.replace("&ndash;", "–").replace("&nbsp;", " ")
    return s


def _count(line: str) -> int | None:
    m = re.match(r"\s*(\d+)\s*[×x]\s", line)
    return int(m.group(1)) if m else None


def _years(line: str) -> list[int]:
    """Seasons listed in a highlights line; expands ranges like 2015–2021."""
    years: list[int] = []
    for a, b in re.findall(r"\b((?:19|20)\d\d)\b(?:\s*[–-]\s*\b((?:19|20)\d\d)\b)?", line):
        a = int(a)
        if b and int(b) > a:
            years.extend(range(a, int(b) + 1))
        else:
            years.append(a)
    return years


# (award key, required regex, forbidden regex). Lines are cleaned display text.
AWARD_RULES = [
    # AP MVP only: drop NFL Europe/World League, side-of-ball "MVPs", and other voting bodies
    ("mvp", r"\b(NFL|AP)\b.*\b(Most Valuable Player|MVP)\b",
     r"Bowl|AFL|playoff|Championship Game|Europ|World League|Offensive|Defensive|PFWA|UPI|Sporting News|Bert Bell|Newspaper"),
    ("afl_mvp", r"\bAFL\b.*\b(Most Valuable Player|MVP)\b", r"Bowl|All-Star"),
    ("opoy", r"\bNFL Offensive Player of the Year\b", r"Rookie"),
    ("dpoy", r"\bNFL Defensive Player of the Year\b", r"Rookie"),
    ("oroy", r"\bNFL Offensive Rookie of the Year\b", r"$^"),
    ("droy", r"\bNFL Defensive Rookie of the Year\b", r"$^"),
    ("roy", r"\bNFL Rookie of the Year\b", r"$^"),
    ("comeback", r"\bNFL Comeback Player of the Year\b", r"$^"),
    ("sb_mvp", r"\bSuper Bowl (Most Valuable Player|MVP)\b", r"$^"),
    ("sb_champ", r"\bSuper Bowl champion\b", r"$^"),
]


def parse_highlights(text: str | None) -> dict:
    """-> {'pro_bowls', 'all_pro_1st', 'all_pro_2nd', 'afl_all_star', 'awards': [(key, season|None)]}"""
    res = {"pro_bowls": 0, "all_pro_1st": 0, "all_pro_2nd": 0, "afl_all_star": 0, "awards": []}
    if not text:
        return res
    for raw in clean_wikitext(text).splitlines():
        line = raw.lstrip("*;: ").strip()
        if not line:
            continue
        # NFL records / college sections often follow a ";" header; college lines never say NFL/Pro Bowl/All-Pro
        n = _count(line)
        yrs = _years(line)
        k = n if n is not None else max(1, len(yrs))
        if re.search(r"\bPro Bowl\b", line) and not re.search(r"\bPro Bowl (MVP|Most Valuable)", line):
            res["pro_bowls"] += k
        elif re.search(r"\bAFL All-Star\b", line):
            res["afl_all_star"] += k
        elif re.search(r"\bAll-Pro\b", line) and not re.search(r"Rookie", line):
            if re.search(r"Second[- ]team", line, re.I):
                res["all_pro_2nd"] += k
            else:  # "First-team All-Pro" or unqualified "All-Pro"
                res["all_pro_1st"] += k
        else:
            for key, req, forbid in AWARD_RULES:
                if re.search(req, line) and not re.search(forbid, line):
                    seasons = yrs or [None]
                    if n is not None and len(seasons) != n:
                        seasons = [None] * n  # count is authoritative; years unparseable
                    res["awards"].extend((key, s) for s in seasons)
                    break
    return res
