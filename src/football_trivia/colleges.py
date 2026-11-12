"""College filter support (spec §3, §5): one canonical final college per player.

Sources, in priority order (all nflverse):
    1. draft picks (1980+): PFR's college at the draft, i.e. the final school
    2. nflverse players (college_name)
    3. rosters / weekly rosters (latest season with a college)

Multi-school strings ("Montez Sweat: Mississippi State; Copiah-Lincoln Junior College;
Michigan State") list the final school first, so the first segment is kept.

Names are normalized by rule ("Ohio St." -> "Ohio State", HTML entities) and then by
the hand-maintained alias table `data/college_aliases.csv` (alias -> canonical).
"""

from __future__ import annotations

import csv
import html
import re
from functools import lru_cache

from .db import DATA_DIR

ALIASES_CSV = DATA_DIR / "college_aliases.csv"

_ABBREV = [  # applied in order, whole words only
    (r"\bSt\.$", "State"), (r"\bSt\.(?=\s*\()", "State"),
    (r"\bTenn\.", "Tennessee"), (r"\bMiss\.", "Mississippi"),
    (r"^NW\b", "Northwest"), (r"^SE\b", "Southeast"), (r"^SW\b", "Southwest"),
    (r"\bCol\.$", "College"), (r"\bU\.$", ""),
]


@lru_cache(maxsize=1)
def aliases() -> dict[str, str]:
    """lowercased alias -> canonical name."""
    out: dict[str, str] = {}
    with open(ALIASES_CSV, newline="") as fh:
        for row in csv.DictReader(r for r in fh if not r.startswith("#")):
            out[row["alias"].strip().lower()] = row["canonical"].strip()
    return out


def normalize(raw: str | None) -> str | None:
    """Raw nflverse college string -> canonical final college (None if empty)."""
    if raw is None:
        return None
    s = html.unescape(str(raw)).split(";")[0].strip()
    s = re.sub(r"\s+", " ", s)
    if not s:
        return None
    a = aliases()
    if s.lower() in a:
        return a[s.lower()]
    for pat, rep in _ABBREV:
        s = re.sub(pat, rep, s).strip()
    if s.lower() in a:
        return a[s.lower()]
    # "Jackson State University", "University of South Florida", "Elizabeth City State Univ":
    # drop the word unless it's part of the name ("Boston University" is in the alias table)
    s = re.sub(r"^University of (?:the )?|,?\s+(University|Univ\.?)$", "", s).strip()
    s = re.sub(r"(\bState) College$", r"\1", s)
    return a.get(s.lower(), s)


def match_key(name: str) -> str:
    """Key for comparing a prompt's college filter with the canonical names."""
    return (normalize(name) or "").lower()
