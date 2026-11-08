"""Name normalization used for identity matching and aliases."""

from __future__ import annotations

import re
import unicodedata

SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def norm_name(name: str | None) -> str:
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9 ]", "", s.lower().replace("-", " "))
    parts = [p for p in s.split() if p not in SUFFIXES]
    # join runs of initials so "Y. A. Tittle", "Y.A. Tittle" and "YA Tittle" all match
    out: list[str] = []
    prev_initial = False
    for p in parts:
        initial = len(p) == 1
        if initial and prev_initial:
            out[-1] += p
        else:
            out.append(p)
        prev_initial = initial
    return " ".join(out)
