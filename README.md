# Football Rare-Answer Trivia — data pipeline

Build order step 1: **`refresh`**, the local data cache. Everything downstream
(`build_answers`, `/probe`, scoring) queries `data/trivia.duckdb` only.

## Run

```sh
export FT_CONTACT="you@example.com"   # Wikimedia wants contact info in the User-Agent
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

## Coverage (answers spec §4 TODO)

See the "Coverage findings" section of the build notes below; regenerate with
`uv run refresh --only build`.
