"""Build step 5: answer matching (spec §9 "fuzzy matching with alias support").

Matches what a player typed to one valid answer of the prompt, or says why not.
This is the reference implementation; the game UI ports the same rules.

Order (first rule that decides wins):
  1. exact full name in the answer bank (any alias: display, legal, common first name,
     first-name variants such as Mike/Michael, manual aliases)  -> valid
  2. exact last name, unique in the bank ("Mahomes")            -> valid
  3. exact full name of a real player who is NOT in the bank    -> invalid (not_valid_answer)
  4. typo tolerance against bank names (Damerau-Levenshtein,
     allowed edits grow with length), unique best match         -> valid (fuzzy)
  5. same, but a non-bank player is at least as close           -> invalid
  6. several bank players tie at any step                       -> ambiguous (ask for more)
  otherwise                                                      -> invalid (no_match)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .names import norm_name

# first-name variant groups (bidirectional). Kept small and common; nicknames that aren't
# first-name forms ("Megatron", "T.O.") go in data/aliases.csv.
NAME_GROUPS = [
    {"michael", "mike", "mikey"}, {"christopher", "chris"}, {"joshua", "josh"}, {"matthew", "matt"},
    {"joseph", "joe", "joey"}, {"nicholas", "nick"}, {"benjamin", "ben"}, {"samuel", "sam", "sammy"},
    {"william", "will", "bill", "billy", "willie", "willy"}, {"jeffrey", "jeff", "geoffrey"},
    {"gregory", "greg"}, {"jacob", "jake"}, {"zachary", "zach", "zack", "zak"},
    {"nathaniel", "nathan", "nate"}, {"daniel", "dan", "danny"}, {"robert", "rob", "bob", "bobby", "robbie"},
    {"james", "jim", "jimmy", "jamie"}, {"thomas", "tom", "tommy"}, {"anthony", "tony"},
    {"david", "dave", "davey"}, {"steven", "stephen", "steve", "stevie"},
    {"richard", "rich", "rick", "ricky", "dick", "richie"}, {"edward", "ed", "eddie"},
    {"kenneth", "ken", "kenny"}, {"ronald", "ron", "ronnie"}, {"donald", "don", "donnie"},
    {"jonathan", "jon", "johnny"}, {"john", "johnny", "jack"}, {"alexander", "alex"},
    {"andrew", "andy", "drew"}, {"patrick", "pat"}, {"timothy", "tim", "timmy"},
    {"lawrence", "larry"}, {"gerald", "jerry"}, {"jerome", "jerry"}, {"charles", "charlie", "chuck", "chas"},
    {"frederick", "fred", "freddie"}, {"raymond", "ray"}, {"terrence", "terry"}, {"eugene", "gene"},
    {"henry", "hank"}, {"douglas", "doug"}, {"phillip", "philip", "phil"}, {"vincent", "vince"},
    {"albert", "al"}, {"alan", "al"}, {"allen", "al"}, {"theodore", "ted", "teddy"},
    {"francis", "frank", "frankie"}, {"franklin", "frank"}, {"leonard", "leon", "lenny", "len"},
    {"gary", "garry"}, {"cameron", "cam"}, {"maurice", "mo"}, {"demetrius", "meech"},
    {"jeremiah", "jeremy"}, {"kristopher", "kris"}, {"kenneth", "kenny"}, {"walter", "walt"},
    {"harold", "harry"}, {"randall", "randy"}, {"gerard", "gerry"}, {"bradley", "brad"},
    {"benjamin", "benny"}, {"frederick", "freddy"}, {"augustus", "gus"}, {"ezekiel", "zeke"},
]
_VARIANTS: dict[str, set[str]] = {}
for g in NAME_GROUPS:
    for n in g:
        _VARIANTS.setdefault(n, set()).update(g)


def first_name_variants(full_norm: str) -> set[str]:
    """'mike vick' -> {'mike vick', 'michael vick', 'mikey vick'}."""
    parts = full_norm.split()
    if len(parts) < 2:
        return {full_norm}
    return {" ".join([v] + parts[1:]) for v in _VARIANTS.get(parts[0], {parts[0]}) | {parts[0]}}


def edit_distance(a: str, b: str, cap: int = 4) -> int:
    """Damerau-Levenshtein (optimal string alignment), stopping early past `cap`."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev2, prev = None, list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        row_min = cur[0]
        for j in range(1, len(b) + 1):
            cost = a[i - 1] != b[j - 1]
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if prev2 is not None and i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
            row_min = min(row_min, cur[j])
        if row_min > cap:
            return cap + 1
        prev2, prev = prev, cur
    return prev[-1]


def allowed_edits(n_chars: int) -> int:
    """Typo budget by length (spaces excluded): short names must be exact-ish."""
    if n_chars <= 3:
        return 0
    if n_chars <= 6:
        return 1
    if n_chars <= 12:
        return 2
    return 3


@dataclass
class Match:
    status: str                      # valid | invalid | ambiguous
    player_id: str | None = None
    method: str = ""                 # exact | last_name | fuzzy | not_valid_answer | no_match | empty
    candidates: list[str] = field(default_factory=list)  # player_ids when ambiguous


class Matcher:
    """One matcher per prompt. `bank` = {player_id: [(alias, kind)]} for the valid answers,
    kind as in the aliases table ('last_only' goes to the last-name index; everything else is
    a full name, and a one-word manual alias like "Megatron" matches exactly). A bare string
    is treated as a last name if it's one word, else a full name.
    `others` = {alias_norm: {player_ids}} for full names of every player (to spot real
    players who aren't valid for this prompt)."""

    def __init__(self, bank: dict[str, list], others: dict[str, set[str]] | None = None):
        self.full: dict[str, set[str]] = {}   # norm full alias -> bank player_ids
        self.last: dict[str, set[str]] = {}   # norm last name -> bank player_ids
        for pid, aliases in bank.items():
            for a in aliases:
                alias, kind = a if isinstance(a, tuple) else (a, None)
                n = norm_name(alias)
                if not n:
                    continue
                is_last = kind == "last_only" or (kind is None and " " not in n)
                if is_last:
                    self.last.setdefault(n, set()).add(pid)
                else:
                    for v in first_name_variants(n):
                        self.full.setdefault(v, set()).add(pid)
        self.others = others or {}
        # index non-bank full names by last token so the "someone else is closer" check
        # only scans ~25k last names instead of every full name
        self._others_by_last: dict[str, dict[str, set[str]]] = {}
        for name, ids in self.others.items():
            self._others_by_last.setdefault(name.rsplit(" ", 1)[-1], {})[name] = ids

    def _resolve(self, ids: set[str], method: str) -> Match:
        if len(ids) == 1:
            return Match("valid", next(iter(ids)), method)
        return Match("ambiguous", None, method, sorted(ids))

    def match(self, typed: str) -> Match:
        q = norm_name(typed)
        if not q:
            return Match("invalid", method="empty")
        if q in self.full:                                    # 1
            return self._resolve(self.full[q], "exact")
        if q in self.last:                                    # 2
            return self._resolve(self.last[q], "last_name")
        outside = {pid for v in first_name_variants(q) for pid in self.others.get(v, set())}
        if outside:                                           # 3
            return Match("invalid", next(iter(sorted(outside))), "not_valid_answer")
        budget = allowed_edits(len(q.replace(" ", "")))       # 4-5
        if budget == 0:
            return Match("invalid", method="no_match")
        pool = self.full if " " in q else {**self.last, **self.full}
        best, best_ids = budget + 1, set()
        for name, ids in pool.items():
            d = edit_distance(q, name, budget)
            if d < best:
                best, best_ids = d, set(ids)
            elif d == best:
                best_ids |= ids
        if best > budget:
            return Match("invalid", method="no_match")
        if self._others_by_last and " " in q:
            # a real non-bank player at least as close means the typo probably wasn't for a bank answer
            q_last = q.rsplit(" ", 1)[-1]
            for last, names in self._others_by_last.items():
                if abs(len(last) - len(q_last)) > best or edit_distance(q_last, last, best) > best:
                    continue
                for name, ids in names.items():
                    if edit_distance(q, name, best) <= best and not ids & best_ids:
                        return Match("invalid", next(iter(sorted(ids))), "not_valid_answer")
        return self._resolve(best_ids, "fuzzy")


# ------------------------------------------------------------------- loaders

def load_others(con) -> dict[str, set[str]]:
    """Full-name aliases (not last names) for every player, with first-name variants."""
    out: dict[str, set[str]] = {}
    for pid, n in con.execute("SELECT player_id, alias_norm FROM aliases WHERE kind <> 'last_only'").fetchall():
        if n and " " in n:
            for v in first_name_variants(n):
                out.setdefault(v, set()).add(pid)
    return out


def bank_aliases(con, player_ids: list[str]) -> dict[str, list]:
    con.register("_ids", __import__("polars").DataFrame({"player_id": player_ids}).to_arrow())
    rows = con.execute("SELECT player_id, alias, kind FROM aliases WHERE player_id IN (SELECT player_id FROM _ids)").fetchall()
    con.unregister("_ids")
    out: dict[str, list] = {pid: [] for pid in player_ids}
    for pid, a, kind in rows:
        out[pid].append((a, kind))
    return out
