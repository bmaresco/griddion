# Football Rare-Answer Trivia — data pipeline

Build order step 1: **`refresh`**, the local data cache. Everything downstream
(`build_answers`, `/probe`, scoring) queries `data/trivia.duckdb` only.

## Run

```sh
# Wikimedia throttles anonymous User-Agents; the repo URL is the default contact (override with FT_CONTACT)
uv run refresh                         # full pull + derive (~first run: 20-40 min, mostly pageviews)
uv run refresh --skip pageviews        # weekly in-season roster refresh
uv run refresh --only build            # re-derive from cached raw tables, no network
uv run pytest
```

Pageviews are incremental: after the first run only new months are fetched.

## Sources

| Step | Source | Raw table |
|---|---|---|
| nflverse | `nflreadpy`: players, rosters (season + weekly), schedules, weekly player stats, snap counts, teams | `raw_*` |
| wikidata | SPARQL: Pro Football Reference ID (P3561) → enwiki title, DOB. Used only as an ID crosswalk | `raw_wikidata` |
| wikipedia | Infobox `highlights` wikitext + "Pro Football Hall of Fame inductees" category | `raw_wiki_pages` |
| pageviews | Wikimedia Pageviews API, monthly, user agent, 2015-07 → last full month | `raw_pageviews` |

## Derived tables

| Table | Grain | Notes |
|---|---|---|
| `players` | person | `player_id` = gsis id; else `pfr:<id>` (matched via Wikidata on name+DOB); else `nm:<name>\|<dob>` |
| `player_seasons` | player × season × team | roster membership + listed position. **Not** proof of playing |
| `player_games` | player × game | games actually played. `sources` ⊂ {stats, snaps, qb_start} |
| `qb_starts` | team × game | starting QB, from schedules |
| `player_awards` | player × award × season | mvp, opoy, dpoy, oroy, droy, roy, afl_mvp, comeback, sb_mvp, sb_champ |
| `player_honors` | player | pro bowls, all-pro 1st/2nd, AFL all-star, HOF, lifetime pageviews |
| `aliases` | player × alias | display, first_last, common_first_last, last_only, + `data/aliases.csv` |
| `team_franchises` | code × season range | from `data/team_franchises.csv` — see below |
| `coverage` | season | data-availability report (printed at the end of every refresh) |

### Team codes → franchise

nflverse reuses codes across eras (e.g. rosters' `STL` is the Cardinals ≤1987
and the Rams 1995–2001; `HOU` is the Oilers ≤1996 and the Texans 2002+; rosters
use `ARZ/BLT/CLV/HST/SL` only for 2002–2015). `data/team_franchises.csv` maps
`(code, season)` to the current franchise code. Defunct teams (AAFC, 1940s
mergers) map to null. Prompts filter on `franchise`.

## Coverage findings (answers spec §4 TODO)

From the `coverage` table (regenerate with `uv run refresh --only build`):

| Data | Available | Notes |
|---|---|---|
| Roster membership + listed position | 1920 → now | Season rosters; weekly rosters (mid-season moves) only 2002+ |
| Stable player identity | ~1975 → now (≈100%) | Pre-1975: 25–90% matched via Wikidata name+DOB; rest get `nm:` ids |
| QB starts | **1999 → now** | From schedules (`home_qb_id`/`away_qb_id`) |
| Games played, players with a stat | **1999 → now** | Misses OL and anyone with zero recorded stats |
| Games played, everyone (incl. OL) | **2013 → now** | Snap counts (nflverse has none for 2012) |
| Non-QB starts | **not available** | nflverse has no starts for non-QBs |
| Wikipedia article | ~95% of players since 1970 | |
| Honors (Pro Bowl, All-Pro, awards, HOF) | all eras | Parsed from infobox highlights; AP MVP found for every season 1957–2025 except 1963 |

**Decisions** based on these findings (pre-1999 QB starts from Wikipedia lists,
seasons-on-roster as the non-QB unit, the pre-1999 roster validity exception)
are recorded in the spec: [`CLAUDE.md`](CLAUDE.md) §3, §4, §7.
