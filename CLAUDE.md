# Griddion — Project Spec

A daily football trivia game. Each day has a set of prompts ("Name a Bears QB"). Players type one answer per prompt against a timer. Any valid answer scores, and **the more obscure the answer is for that specific question, the more it's worth.**

> **Griddion** ([griddion.io](https://griddion.io)). Inspired by the rare-answer mechanic of Krillion, but uses none of its name, branding, or tier names.

---

## 1. Core definition: what "rarity" means

Rarity = **how deep a pull this player is for this specific question**, as an objective measure of obscurity.

- It is NOT a raw count of how many players typed the answer.
- It IS sensitive to context: Kyle Orton is a bigger pull for "any QB since 2000" than for "Bears QB," and Jerry Rice is a deep pull as a Seahawk.
- Tiers come from **objective rules**, never from anyone's hand-ranking of players. Human review only fixes broken *rules*, never an individual player's tier.
- After launch, real answer data is used to **tune** the formula's parameters, not to replace it.

---

## 2. Tiers and scoring

| Tier | Points | Meaning |
|---|---|---|
| Starter | 10 | The answer everyone thinks of first |
| Backup | 30 | Solid, but not the first name |
| Hidden Gem | 60 | You have to dig a little |
| Sleeper Pick | 85 | Truly obscure |
| YKB Kid | 100 | One hand-picked best answer per prompt |
| Botched Trick Play | 15 | Optional; the famous "obscure" pick everyone reaches for. Used sparingly |
| Invalid / no answer | 0 | |

- **YKB Kid**: one per prompt. **Default: the highest-fame (F, the prompt's own F per §7: `s_pv` on award prompts) Sleeper Pick; if the prompt has no Sleeper Pick, the highest-fame Hidden Gem.** **A player can be YKB Kid at most once in any 14-day window:** if the default pick was already YKB Kid in the previous 13 drives (or earlier in the same drive), take the next-highest-fame eligible pick, in drive order. A prompt can override it with `"ykb_kid": "<player_id>"` (publish warns if the override repeats within the window). `prompts/ykb_review.md` lists every prompt's pick and context line for a quick skim (`uv run python prompts/ykb_review.py`).
- **Botched Trick Play** is a **manual option only**: never assigned or suggested by the pipeline. It's used on a handful of prompts at most, and only when explicitly added to a prompt (`"botched_trick_play": "<player_id>"`), which overrides that one answer's tier. **No prompt uses it at launch.** (An automatic suggestion — most famous answer with F ≥ 0.58 and A ≤ 0.35 — was tried on the 14-day draft and all 32 suggestions were rejected.)

---

## 3. Validity rules

- **QBs** (team, era, or conference prompts): must have **started at least one regular-season game** in the qualifying context, for all eras. The prompt subtitle shows: *"QBs must have started a regular-season game."*
- **All other positions**: must have **played in at least one regular-season game** in the context. Preseason and playoff-only appearances don't count.
- **Trait prompts** (awards, stat thresholds, e.g. "won OROY and MVP," "1,500+ receiving yard season"): the trait alone qualifies the player.
- **College prompts** (decided 2026-11-11, e.g. "Name a WR who played college football at Ohio State"): the player's **final college** must match, **and** he must meet the usual rule above: a regular-season start for QBs, a counted season (§3 roster status) for everyone else, at the listed position. **Since 1974 only:** nflverse has a college for ~99.6% of players with a 1974+ season and 0% for careers that ended earlier, so seasons before 1974 don't count, and the subtitle says so (`Since 1974 · Must have played in an NFL regular-season game`). **Final school only:** a player who transferred out (e.g. Ohio State → Kansas) counts for the school he finished at. **School + position only:** no "any player" college prompts (Miami (FL), any position: 345 answers, too bottom-heavy: 91% Hidden Gem + Sleeper on the stat thresholds).
- **Position** is the player's listed position in the qualifying seasons (e.g. a gadget player counts as a QB only for seasons he started at QB).
- Example: Andy Dalton (0 starts for PHI in 2026) is **not** a valid "Eagles QB" answer.

**Known exception — pre-1999 non-QBs.** There is no games-played data before 1999, so we can't confirm these players appeared in a game. For non-QBs in seasons before 1999, **being on the active regular-season roster** (see *Roster status* below) in the context counts as valid. The rules for QBs and for non-QBs from 1999 on are unchanged.

**Known exception — pre-1950 QBs.** The Wikipedia starting-QB lists begin in 1950, so there are no starts before then. Pre-1950 QBs are **not excluded** (Sid Luckman must be a valid Bears QB): they use the roster rule, by listed position (QB on the active roster). `/probe` lists them separately for review.

**QB starts source.** Wikipedia's "List of [team] starting quarterbacks" is the primary source for **every season**. nflverse is the cross-check. The exception is **Green Bay and the Rams from 1999 on**, where the Wikipedia pages give only per-player totals, so nflverse is used. Reason: nflverse's schedule `qb_id` is the QB with the most passes, not the starter (e.g. it credits Garoppolo with Brady's 2014 week 17 start and shows Jayden Daniels with 12 of his 17 2024 starts). Current-season mismatches between the two are **flagged in `/probe` and the diff report, never silently resolved**.
- **Current season (decided 2026-11-08):** Wikipedia's current-season rows lag in season (e.g. Jalen Hurts 2 vs 6 starts), so **the current season's QB starts come from nflverse** (`build.QB_CURRENT_SEASON_FROM_NFLVERSE`). The mismatch flag stays on; switch the current season back to Wikipedia once its rows are complete.

**Roster status** (codes from nflverse's `dictionary_roster_status`):

| Code | nflverse meaning | Counts as active roster |
|---|---|---|
| `ACT` | On the active roster | yes |
| `TRC` `TRD` `TRT` | "Released from the practice squad" | **before 1989 only.** Practice squads didn't exist until 1989; in older data these codes mark players who left mid-season after playing (e.g. Howard Mudd, 49ers 1969). From 1989 they count as no |
| `INA` | Under contract but not on the active roster, inactive | no |
| `DEV` | Practice squad | no |
| `RES` `PUP` `RSN` | Reserve list (IR) / PUP / non-football injury | no |
| `CUT` `NWT` `RFA` `UFA` `RSR` | Released / waived | no |
| `SUS` `EXE` `E14` `RET` `TRL` | Suspended / exempt / international / retired / unknown | no |

- **A season counts** for a player and team if he appeared in ≥ 1 regular-season game where games data exists (any recorded stat 1999+, snap counts 2013+). Otherwise it counts if he had an active-roster status: any `ACT` week in the weekly rosters (2002+), or the season roster status (before 2002).
- **Seasons spent entirely on IR or the practice squad don't count**: no games and no active week.
- Known limit: before 2002 there is only one status per season (end of season). A player whose season status is `RES` or `CUT` but who played earlier that season (e.g. David Akers, Washington 1998) is excluded. `/probe` lists these as edge cases for review.

---

## 4. Data sources (all reusable, no scraping)

| Source | Used for |
|---|---|
| **nflverse** (`nflreadpy`) | Rosters, games, season stats, player IDs/cross-refs, names; QB starts for GB and LAR 1999+ and as the cross-check elsewhere |
| **Wikipedia** (CC BY-SA) | Awards (MVP, OPOY, DPOY, OROY, DROY), Pro Bowl / All-Pro, Hall of Fame |
| **Wikipedia list pages** (CC BY-SA, `raw_ap_award_pages`) | The six AP award pages; **Super Bowl Most Valuable Player Award** (game year − 1 = season; 61 rows, co-MVPs in XII); **List of Heisman Trophy winners**; **List of Pro Football Hall of Fame inductees** (inducted as a player vs coach/contributor, and the position inducted at); **"{season} All-Pro Team"** pages 1968→ (AP first team with its position slot). Pro Bowl seasons come from infobox highlights (years listed on > 99.8% of lines) |
| **nflverse draft picks** (1980+) | Draft filter: season, round, pick, position only. Its PFR-derived columns (AV, Pro Bowls, All-Pro, HOF) are **never used** (§4 PFR rule) |
| **Wikipedia "List of [team] starting quarterbacks"** (CC BY-SA, all 32 franchises) | QB starts, **primary source for every season** (see §3). Cross-checked against nflverse; mismatches flagged |
| **`data/team_alignment.csv`** (hand-maintained, reviewable) | League, conference and division per franchise-season, 1950→now, including the AFL 1960–69 |
| **nflverse colleges** (draft picks 1980+, players table, rosters) | Final college per player (`player_college`). Priority: draft picks (college at the draft) > nflverse players `college_name` > latest roster row. Multi-school strings list the final school first; only that one is kept |
| **`data/college_aliases.csv`** (hand-maintained, reviewable) | College name normalization after rules (`St.` → State, HTML entities, trailing "University"): LSU = Louisiana State, USC = Southern California, bare roster "Miami" = Miami (FL) (63 of 63 drafted players agree), … Draft vs roster agree for 99.8% of 4,828 players after normalization; the rest are real transfers, where draft wins |
| **Wikimedia Pageviews API** | Player fame (pageviews, available from mid-2015 onward) |
| **Wikidata** (CC0) | ID crosswalk only: Pro Football Reference ID → Wikipedia article |

- Do **not** scrape Pro Football Reference, StatMuse, ESPN, NFL.com, or Yahoo. They are for manual spot-checks only.
- Do **not** use Pro Football Reference data or old NFL.com scrapes from any source (e.g. `zackthoutt/nfl-player-stats`). Licensing is unclear. (Using the PFR *ID string* from Wikidata purely as a join key is fine.)
- **Aliases:** generated from nflverse name fields only (display name, legal first + last, common first name + last, last name). No hand-maintained nickname list in v1.

### Coverage (confirmed in step 1)

| Data | Available |
|---|---|
| Roster membership + listed position | 1920 → now |
| QB starts | **1950 → now** from the Wikipedia QB lists (the pages start in 1950; none before). Green Bay and the Rams list only per-player totals: nflverse for them from 1999, estimates (`basis = split`) before 1999 |
| Games played, players with a recorded stat | 1999 → now |
| Games played, all positions incl. OL | 2013 → now (snap counts) |
| Non-QB starts | not available |
| Honors, awards, HOF | all eras |

### Local cache
A `refresh` script pulls all sources into a local DuckDB (or SQLite) file. **All prompt testing and building queries this local file only.** No web calls at question time. Refresh weekly in season, since rosters change constantly.

---

## 5. Prompt format

Prompts are **structured filters**, not free text. The display text is stored alongside.

```json
{
  "id": "bears-qb-since-2000",
  "text": "Name a Bears QB since 2000",
  "subtitle": "QBs must have started a regular-season game",
  "filters": { "team": "CHI", "position": "QB", "season_min": 2000 },
  "type": "team"
}
```

Supported filter types (build as a reusable library):
- `team`, `teams_all` (played for every listed team), `position`, `conference`, `division`
- `season_min` / `season_max` (eras, decades)
- `award` (one or more; "won X and Y")
- `award_any` (two or more; "won X or Y": the union of winners, each award from its own AP start season). The prompt text must name every award and say "or" (`check_text.py`). Award prompts either way (§7 award group).
- `stat_threshold` (e.g. receiving yards ≥ 1500 in a single season)
- **Weekly stat filters** (added 2026-11-11; nflverse weekly player stats, regular season, **1999+**: `build_answers` clamps `season_min` to 1999 and `/probe` warns unless the text or subtitle says "1999", e.g. `Since 1999`):
  - `rookie_stat` `{"stat", "min"}`: total in the player's **first NFL season** = his first counted season (§3: a game, or the roster rule), not nflverse's `rookie_season`, which is earlier for 1,536 players, mostly a practice-squad / IR / cut year with no game. Only 1999+ rookies can qualify. Known limit: a pre-2013 player who played with no recorded stat (Victor Cruz 2010: 3 special-teams games, nflverse has him on IR all season) gets his next season as his rookie year.
  - `game_stat` `{"stat", "min", "games_min": 1}`: at least `games_min` regular-season games at or above `min`.
  - `window_stat` `{"stat", "min"}`: total over `season_min`–`season_max` ≥ `min`.
  - `position_not` (with these three only): exclude a group/code or list, e.g. `["RB"]` (the RB group includes FB).
  - **Position is per stat row**: `position` / `position_not` test the player's listed position for **that team-season** (`player_team_seasons`), because the weekly row's own `position` is his current one (Cordarrelle Patterson shows "RB" for his 2013–20 WR seasons). So "a non-RB with a rushing TD" counts Patterson's WR-era TDs and Taysom Hill's QB and TE seasons, never Juszczyk (FB).
  - **Coverage (checked 2026-11-11):** sacks (half sacks included) and INTs are present every season since 1999 (Strahan 2001 22.5, Allen 2011 22, Watt 2021 22.5, Reed 2004 9, Bailey 2006 10, Diggs 2021 11 all match). **Three games are missing entirely** from nflverse's weekly player stats: 1999 Wk 1 BAL@STL, 2000 Wk 3 SD@KC, 2000 Wk 6 BUF@MIA (e.g. Kevin Carter's 1999 total reads 15 vs the official 17). Rows with no player are uncredited team sacks and never answers.
  - Weekly stat prompts are trait prompts (A = 1) in the **stat** threshold group (§7).
- `college` (a school or list of schools: final college attended, §3). `build_answers` clamps `season_min` to **1974** and `/probe` warns if the text doesn't say "1974". College prompts are trait prompts (A = 1) in the **college** threshold group (§7)
- **Honors filters** (added 2026-11-11, P7). Trait prompts (A = 1) in the **award** threshold group (§7). Each reads `position` itself:
  - `hall_of_fame: true`: inducted **as a player** (the inductee list, not the HOF category, which also holds coaches who played: Bill Cowher was showing up as a HOF LB). `position` = the position(s) he was **inducted at** ("Defensive end/linebacker" counts for DL and LB), because roster data lists pre-modern two-way ends as DL (Don Hutson, Pete Pihos). `season_min`/`max`: played a counted season in the window. 335 inductees matched; Johnny Blood (1925–39) isn't (his nflverse name is "Johnny (Blood) McNally"). 11 old-timers whose article never linked in identity are matched by exact name among unlinked players.
  - `all_pro: true`: **AP first team** only, from the season All-Pro Team pages (**1968+**: `build_answers` clamps and warns unless the text says 1968). `position` = the AP slot (edge rusher and flex: his listed group that season). Special teams, returners and long snappers never count for a position. Infobox "All-Pro" lines mix PFWA/Sporting News picks and special-teams selections without saying so (infobox: 62 All-Pro WRs since 2000; AP: 32), so they are kept only as `all_pro_*_infobox` rows for comparison.
  - `pro_bowl: true`: Pro Bowl seasons from infobox years (NFL Europe, CFL, USFL, XFL, UFL, Arena and AAFC lines dropped). With `team`, the selection season's team = the team he played the most games for that season (`team` doesn't make it a team prompt).
  - `award: "sb_mvp"` / `"heisman"`: from their list pages. **Heisman answers must have played an NFL regular-season game** (§3; QB-only prompts: a start). 78 of 91 winners did; the 11 who didn't are unmatched by design (Berwanger, Kinnick, Davis, Ward, Crouch, White, …).
  - `draft: {"pick": n} | {"pick_max": n} | {"round": n}`: nflverse draft picks, **1980+** (clamp + warning unless the text says 1980). `season_min`/`max` are **draft years**, `position` is the **draft position**, and answers must have played a game (QB-only: a start).

`type` is one of: `team`, `era`, `two_team`, `trait`. It determines how association is calculated.

Filter rules:
- **Team** means franchise (`data/team_franchises.csv`), so "Colts" includes Baltimore. **AFL seasons (1960–69) count** for team prompts.
- **Conference** prompts (AFC/NFC) start in **1970**. Division prompts use the division in force that season (`data/team_alignment.csv`).
- **Stat thresholds: 1999+ only (launch).** Season stats come from nflverse, which starts in 1999. The prompt text **must state the date** ("…in a season (since 1999)") so a correct pre-1999 answer is never marked wrong. `build_answers` clamps `season_min` to 1999 and `/probe` warns if the text doesn't say "1999".
- **AAFC seasons (1946–49) are excluded** from team prompts. Players still qualify through their NFL seasons (e.g. Otto Graham, Browns 1950–55).
- **Awards: AP only.** Wikipedia variants from other bodies (PFWA, UPI, Sporting News, NEA, …) are ignored. MVP prompts start in **1957**, OROY/DROY in **1967** (the first AP seasons).

---

## 6. Pipeline

### Step 1: Valid answers (`build_answers`)
Input: one prompt. Output: every valid player, each with **evidence**:
- stable player ID, display name, aliases
- qualifying stint: starts, games, seasons in context
- career totals: starts, games, seasons
- qualifying-season production (for the peak boost)
- validity basis (QB start / game played / roster only — the §3 pre-1999 exception)

Step 2 depends on this evidence. Step 1 must never return names only.

### Step 2: Rarity (`score_answers`)
Input: Step 1 output. Output: each answer with F, A, R, R′, and tier. Formula in §7.

**Answer bank export** (the output the game ships with): every answer carries its **tier** and a **context line** built from the Step 1 evidence:

| Prompt type | Context line | Example |
|---|---|---|
| Team, QB | context starts · seasons | `102 starts · 2009–16` |
| Team, other positions | context games · seasons | `158 games · 1974–84` |
| Two-team | each team's span | `Raiders 2004–07 · Chiefs 2008` |
| Era / conference / division | teams in context · seasons | `Colts, Bills · 1990–97` |
| Stat | best qualifying season's stat · season | `1,871 yds · 2015` |
| Award | season(s) won | `Won 2011` |
| Award, either (`award_any`) | each award won · seasons | `MVP 2007, 2010 · OPOY 2007` |
| Rookie stat | rookie total · season | `91 rec · 2014 (rookie)` |
| Game stat | best game; with 2+ qualifying games, the count first | `4.5 sacks · Wk 12, 2019` / `9 games · best 7 TD · Wk 1, 2013` |
| Window stat | total · seasons that contributed | `7 TD · 2016–22` |
| College | teams in context · seasons (1974+) | `Bills · 2001` |

- Seasons render as `2009–16` (single season `2008`; full years when the century changes, `1999–2004`). Counts are singular at 1 (`1 start`).
- **Games are "complete"** for a stint when every counted season is 2013+ (snap counts), or 1999+ for QB/RB/WR/TE (stat rows track their appearances). Otherwise the line uses seasons.
- Games aren't available before 1999 (all positions) or 1999–2012 for players with no recorded stat (§4). Where a stint's games are incomplete, the line falls back to seasons: `11 seasons · 1974–84`. Pre-1950 QBs (no starts) use the same fallback.

### Published files (the contract the game UI reads)

`uv run publish build` writes `public/` (committed; deployed as static files with the site). `format` is `1` in every file; bump it on any breaking change.

**`public/schedule.json`** — which drive is when.
```json
{ "format": 1, "launch_date": "2026-11-09",
  "rollover": { "time": "00:00", "timezone": "America/New_York" },
  "drives": [ { "drive": 1, "date": "2026-11-09", "file": "days/1.json" }, … ] }
```
The UI picks today's drive from **the current date in America/New_York** (everyone gets the new drive at midnight Eastern): `drive = (today_ET − launch_date).days + 1` (§9).

**`public/days/<drive#>.json`** — one drive: 7 prompts with their full answer banks.
```json
{ "format": 1, "drive": 1, "date": "2026-11-09",
  "data_version": "2026-11-08T16:30:22", "thresholds_frozen_at": "2026-11-08",
  "prompts": [ {
      "slot": 1, "id": "d01-1",
      "text": "Name a Browns QB",
      "subtitle": "All seasons (franchise history) · QBs must have started a regular-season game",
      "type": "team", "tier_group": "other", "answer_count": 69,
      "ykb_kid": "DAW622932", "ykb_source": "default", "botched_trick_play": null,
      "answers": [ {
          "id": "00-0034855", "name": "Baker Mayfield", "tier": "Starter",
          "context": "59 starts · 2018–21",
          "names": ["Baker Mayfield"], "last_names": ["Mayfield"], "r": 0.631 }, … ] }, … ] }
```
- `answers` are sorted by `r` (R′) descending: the formula's order, most recallable first.
- `tier` is one of Starter · Backup · Hidden Gem · Sleeper Pick · YKB Kid · Botched Trick Play. Exactly one answer per prompt is `YKB Kid` (its id is `ykb_kid`; `ykb_source` is `default` or `override`). Botched Trick Play appears only where a prompt sets it.
- `names` = every full-name form to match on; `last_names` = last-name forms. The UI adds first-name variants from `matching.json`.
- `id` is the stable player id used in answer logging (§9).

**`public/game.json`** — scoring and drive rules (§2, §9).
```json
{ "format": 1,
  "tiers": { "Starter": { "points": 10, "yards": 2, "square": "⬜" }, …, "Incomplete": { "points": 0, "yards": 0, "square": "⬛" } },
  "drive": { "start_yardline": 25, "touchdown_yards": 75, "trail": [17, 21], "win": [24, 21],
             "clock_start_seconds": 175, "seconds_per_play": 25, "plays": 7 } }
```

**`public/matching.json`** — shared matcher data (§9 answer matching).
```json
{ "format": 1,
  "first_name_groups": [ ["michael", "mike", "mikey"], … ],
  "edit_budget": [ { "max_chars": 3, "edits": 0 }, { "max_chars": 6, "edits": 1 }, { "max_chars": 12, "edits": 2 }, { "max_chars": null, "edits": 3 } ],
  "all_player_names": { "Andy Dalton": ["00-0027973"], … } }
```
`all_player_names` (~2 MB raw, much smaller gzipped) lets the UI reject a real player who isn't valid for the prompt, and stop a typo from snapping to a valid answer when another real player is at least as close. Names are compared after normalization (lowercase, accents and punctuation removed, suffixes like Jr./III dropped, runs of initials joined: `Y. A.` → `ya`), exactly as `names.norm_name`.

### Slot plan (decided 2026-11-11)
The two-team slots are gone. Drives 1–2 stay frozen as published; Drives 3–14 get rebuilt on this plan once every slot is designed.

| Slot | Prompt type | Threshold group |
|---|---|---|
| P1, P2 | team / division (unchanged) | other |
| **P3** | **college**: school + position (`college`), "Since 1974" | college |
| **P4** | **new stat types**: `rookie_stat`, `game_stat`, `window_stat` (+ `position_not`), "Since 1999" | stat |
| P5 | era (unchanged) | other |
| P6 | single-season stats (`stat_threshold`), as before | stat |
| **P7** | **honors**: AP awards + `hall_of_fame`, `all_pro`, `pro_bowl`, Super Bowl MVP, Heisman, `draft` | award |

- **Drives 3–14 rebuilt on this plan (2026-11-11)**, `prompts/build_14_days.py` (`P3`, `P4`, `P7` at the end). `frozen_through` is now **2**. Drive 3's date had come but it was never deployed, so it was rebuilt once with `publish build --unfreeze 3`: `--unfreeze N` lifts only the date rule, for a drive that never went out, and can never go past `frozen_through`. Picks: P3 = 12 different schools (LSU DB, Florida WR, Penn State LB, Wisconsin OL, Oklahoma RB, Clemson DL, UCLA DB, USC WR, Georgia LB, Notre Dame OL, Auburn RB, Michigan LB; of the 12 probed on 2026-11-11, Tennessee QB had 5 answers, Iowa TE 19, and Texas WR (29) and Nebraska RB (exactly 3 Sleepers) were skipped for margin). P4 = 12 of the 21 passing (no 2+ INT game: bottom-heavy; no near-duplicates such as 3.5+ and 4+ sacks). P7 = 2 AP awards (OROY, DROY) + 10 of the 19 honors prompts, never the same type two days running. At most one 250+-answer prompt per day across all slots (the fixed slots already have one on Days 3, 5, 9, 11; P4's two go on Days 4 and 13). All 84 prompts pass ≥ 25 answers and ≥ 3 Sleepers after the 14-day YKB window; no duplicates; every daily average ≤ 142.
- **P4 pool** (`prompts/weekly_stat_probe.jsonl`, probed 2026-11-11, stat thresholds). 21 of 32 pass both publish rules: rookie WR 60+ rec, rookie RB 1,000+ and 800+ rush yds, rookie 7+ sacks, rookie 4+ INT, rookie TE 40+ rec, 3.5+ and 4+ sacks in a game, 2+ and 3+ INT game, 200+ rush yds game, 200+ and 150+ rec yds game, RB 100+ rec yds game, QB 4+ TD game, TE 3+ TD game, non-RB rushing TD (with and without QBs), non-QB TD pass, WR TD pass, DL with an INT. Failing: rookie WR 70+ rec / 900+ yds, rookie QB 20+ TD / 3,000+ yds, QB 5+ TD / 400+ yds / 100+ rush yds game, TE 150+ rec yds game, RB 150+ rec yds game, 4+ rush TD game, K 6+ FG game (famous pools with no Sleepers, or under 25).
- **P7 pool** (`prompts/honors_probe.jsonl`, award thresholds). 19 of 23 pass. Failing: All-Pro TE since 2000 (12 answers), All-Pro WR since 2000 (32, 0 Sleepers), All-Pro WR since 1990 (2 Sleepers).

### Scheduling and publish flow
- **`prompts/schedule.json`** maps each drive to its 7 prompt ids and date. `uv run publish schedule --launch YYYY-MM-DD` writes it from the prompt queue (queue Day d → Drive #d).
- **`uv run publish build`** exports every scheduled drive to `public/`. It refuses to publish a drive with any prompt under 25 answers or with fewer than 3 Sleeper Picks besides the YKB Kid (`--force` overrides) and warns when a `ykb_kid` override isn't a valid answer.
- **Frozen drives (decided 2026-11-08): a drive is frozen once it goes live (00:00 ET on its date). Never regenerate a live or past drive.** Drives up to `frozen_through` in `prompts/schedule.json` are frozen too, before their date (currently `2`: Drives 1–2 stay exactly as published). `publish build --unfreeze N` (one-off) rebuilds a drive whose date has come but that was **never deployed**; it never lifts `frozen_through`. `publish build` and `publish diff` read frozen drives back from `public/days/<n>.json` and never rewrite them, even with `--force`; their YKB Kids still count for the 14-day window. `publish schedule` refuses to change a frozen drive. So a rule or threshold change reaches only unfrozen drives: Drive 1's AP MVP (d01-7) keeps the tiers from before award `F = s_pv`.
- **AP Comeback Player of the Year is retired from the award rotation (decided 2026-11-08).** Its pool is 27 winners (1998–2025), too small to meet the ≥ 3-Sleeper rule under award `F = s_pv` (Drive 5: 1 Sleeper, Drive 10: 2). Don't schedule it; `check_text.py` flags it. Its two slots (D5.7, D10.7) went to the first two "either award" candidates that passed both publish rules, probed in this order: ROY (offense or defense) 119 answers · 4 · 22 · 40 · 52+YKB ✅ → **D5.7**; MVP or OPOY 69 · 6 · 25 · 31 · 6+YKB ✅ → **D10.7**; DPOY or DROY 93 · 3 · 19 · 29 · 41+YKB ✅ (unused); AFC / NFC DPOY winners (award-season team's conference) were not needed: the data exists, but the NFC side has only 18 winners (< 25). Comeback stays in the award calibration set: the frozen thresholds were computed with it, and changing the set would mean recalibrating.
- **Weekly in season:** `uv run refresh` → `uv run publish diff` (writes `reports/diff_<date>.md`; review it) → `uv run publish build` → deploy.

### Checks between steps
- **< 25 valid answers → hard stop.** Widen or drop the prompt.
- **< 3 Sleeper Picks besides the YKB Kid → hard stop** (decided 2026-11-08). Every shipped prompt must leave room for real deep pulls. `publish build` refuses the drive; replacements are chosen by a human, not the pipeline.
- **Per-day check: average valid answers across a day's 7 prompts > 300 → warning only.** Keeps a day reviewable and aliasable without capping any single prompt. (Replaces the earlier per-prompt 300 warning.)
- **Diff report** against the last build (new or removed answers, tier changes). It also **flags every prompt within 3 of the minimum (≤ 28 valid answers)**, since one roster or award change can push it under. Batch `/probe` marks these `tight`.
- **Tier spread warnings**: zero Starters; zero Sleepers; **very top-heavy** = Starter + Backup above 70% of answers; **very bottom-heavy** = Hidden Gem + Sleeper above 85%. (Calibration targets 45/55, so these flag clear outliers.) Warnings only. The spread is never forced.
- **Human review** of every answer bank before publishing, to catch rule bugs and edge cases.

---

## 7. Rarity formula

All components are 0–1. Every default below has a written reason. Change a number only with a reason, recorded here.

### Fame, F (per player; one formula for award prompts, one for everything else)
```
F = 0.60·s_pv + 0.25·s_honors + 0.15·s_career     stat and other prompts
F = s_pv                                          award prompts

s_pv     = clamp( (log10(pv24) − log10(30)) / (log10(300000) − log10(30)), 0, 1 )
s_honors = clamp( honors_points / HONORS_CAP, 0, 1 )
s_career = clamp( seasons / 15, 0, 1 )
```
**Decision (2026-11-08): award prompts use the pageview signal alone (`F = s_pv`).** The award already says why the player is known, so honors and career length double-count it, and they penalize recent winners who haven't had time to collect Pro Bowls or seasons yet (Tetairoa McMillan, 2025 OROY, was the OROY YKB Kid under the blended F; he's a Backup with `F = s_pv`). Stat and other prompts keep the blended F. `scoring.PV_ONLY_FAME_GROUPS`. The YKB Kid default (§2) uses the prompt's F, so on award prompts it's the most-viewed Sleeper Pick. Award thresholds were recalibrated for this (see *Frozen thresholds*). The general fix for the recent-player penalty (option b) is an open item (§11).
- `pv24` = **average monthly** enwiki pageviews (user agent) over the **most recent 24 complete months**. **Main signal** for how known a player is. No Wikipedia article → `s_pv = 0`.
- `honors_points` = weighted Pro Bowls + All-Pro + Hall of Fame (table below). Protects pre-internet stars whose pageviews undercount their fame.
- `seasons` = distinct seasons on a regular-season roster. Separates a 10-year starter from a one-season player.
- Decision: college or off-field fame in pageviews (e.g. a famous college QB) is **kept**. Fans who know the player are more likely to recall his NFL stops too.

**Decision: fixed linear scales, not percentile ranks.** A percentile ranks against ~35k players back to 1920, 27% of whom have zero pageviews, so every recognizable player was squeezed into 0.90–1.00 (Brady 1.00, Kyle Orton 0.975), and fame stopped separating answers. A fixed scale keeps the size of the gaps. Recorded values:

| Scale | Value | Reason |
|---|---|---|
| `pv24` floor | **30 / month** | ≈1 view/day, crawler-noise level: a player here is effectively unknown. ~8% of players with articles sit at or below it. |
| `pv24` ceiling | **300,000 / month** | ≈10k views/day, the current top of the distribution (Brady, Kelce, Josh Allen ≈ 320–340k). Separating the very top doesn't change recall, so anything above clamps to 1. |
| `HONORS_CAP` | **20** = the median `honors_points` of Hall of Fame players under the weights below | A typical Hall of Fame career is the natural "maximum fame from honors". Half of HOFers clamp to 1, which is intended. |
| career cap | **15 seasons** | The 99th percentile of careers in the DB (1.1% of players reach it). Longer careers don't add recall. |

**Decision: honors weights.**

| Honor | Points | Reason |
|---|---|---|
| Pro Bowl | 1 | The base unit and the most common honor (2,374 non-HOF players have at least one). |
| AFL All-Star | 1 | The AFL's Pro Bowl. AFL seasons count for team prompts (§5), so its stars shouldn't count for less. |
| 2nd-team All-Pro | 1 | About as selective as a Pro Bowl, and the two mostly go to the same players. |
| 1st-team All-Pro | 2 | Best at his position that year: a stronger recall signal than a Pro Bowl, and about half as common. |
| Hall of Fame | 6 | The median HOF player has 14 points before induction and 20 after, above the 99th-percentile non-HOF career (16), so induction reliably reads as more fame than any non-HOF honors haul ("weighted highest"). Also gives early-era HOFers with few Pro Bowls a floor of 0.3. |

**Decision: 24-month pageview window, not lifetime.** Pageview data only starts in July 2015, so lifetime totals undercounted anyone who retired before or during the window (Kyle Orton, retired 2014, had fewer lifetime views than Chase Daniel). A recent-window average puts every player on the same footing. The boost active players get is **accepted as real current recall**. The floor and ceiling above were picked for this metric (monthly average, so much smaller than lifetime totals).

### Association, A (per player, per prompt)
```
share      = context_units / career_units        (unit per the rules below)
prominence = min(1, context_units / benchmark)   benchmark: 32 starts, 32 games, or 2 seasons
peak       = min(1, best qualifying-season production / benchmark)
A          = max( sqrt(share × prominence), peak )   for team / era prompts
A          = max( A_team1, A_team2 )             for two-team prompts
A          = 1                                    for trait prompts
```
- `sqrt` softens the drop-off: half a career ≈ 0.71.
- **`prominence`** (team, era and two-team prompts; not trait): **fans tie a player to a team by how long he was the guy there, not by what fraction of a short career the stint was.** Without it, a career backup's 3 starts out of 5 scored like a long tenure (Chase Daniel, Matt Barkley and Tyson Bagent ranked above Rex Grossman on "Bears QB"). Benchmarks match the prompt's unit: **32 starts** or **32 games** (two full seasons of starting or playing) or **2 seasons** (a real tenure). With it, Grossman (31 starts) is a Starter and Daniel (3 starts) a Hidden Gem.
- Two-team prompts compute `sqrt(share × prominence)` per team and keep the better team.
- `peak` keeps a memorable short stint (one great season with a team) from being treated like a cameo.
- **`peak = min(1, best qualifying-season production ÷ benchmark)`**, for **QB, RB, WR, TE** only. A season's listed position picks the metric. All other positions use **`A = sqrt(share × prominence)`** only (no peak). Season stats start in 1999, so qualifying seasons before 1999 contribute no peak.

| Benchmark | Value | Reason |
|---|---|---|
| QB | **4,000 passing yards** | The classic "big season" mark: about 9–10 QBs reach it per season since 2009 (about 4 per season in 1999–2008), so hitting it makes a stint memorable. |
| RB, WR, TE | **1,200 scrimmage yards** | About 25–30 players per season reach it (1999–2025), roughly a Pro Bowl-calibre skill-position season. |

- Why a benchmark rather than "÷ career-best season": against a career best, any backup's best season scores 1.0, so career backups maxed out their association (Chase Daniel outranked Jay Cutler on "Bears QB"). A fixed benchmark only rewards stints that were actually big.

**Units:**
- **QBs: starts.** Wikipedia QB lists, all seasons (nflverse for GB/LAR 1999+; see §3), 1950 on. Pre-1950 QBs use seasons.
- **Everyone else: seasons on roster** (seasons with the team ÷ career seasons), counted by the §3 roster-status rule. Available for every player back to 1920.
- **Games** only where they are complete (2013+, all positions) **and** they improve the result.
- **One unit per prompt.** Never mix units within a prompt: if any valid answer lacks the chosen unit, score every player in that prompt with the fallback.
- **The one exception: pre-1950 QBs.** On QB prompts, QBs with any career season before 1950 (no starts data) use **seasons share**; every other QB in the same prompt keeps **starts share**. Reason: share is a within-career ratio, so each QB's ratio is internally consistent, and switching a whole all-history QB prompt to seasons would overrate long-time backups.
- **Games-fallback comparison test (QBs only):** before approving games as a fallback for QB prompts, score modern QB prompts both ways (starts vs games) and compare tiers. Approve only if tiers barely change.

### Base recall, R
```
R = F × A
```

### Crowding, R′
```
R′ = R × (1 + n)^(−δ)        δ = 0.15
```
- `n` = number of valid answers in this prompt with a higher R.
- Top answers are barely affected. The effect grows slowly with pool size, so a mid-fame player gets moderately deeper in big pools without collapsing.

### Tier thresholds (fixed values on R′)
Set once, objectively:
1. Run the pipeline on a batch of ~20 varied prompts (team, era, award, stat, two-team; easy and hard).
2. Pool every answer's R′ across all prompts, **weighting each answer by 1 / (its prompt's pool size)** so every prompt counts equally. Otherwise the big pools (🔥 prompts, era QBs) would set the thresholds.
3. Set thresholds at these pooled percentiles:

| Tier | Share of pooled answers |
|---|---|
| Starter | top 10% |
| Backup | next 35% |
| Hidden Gem | next 35% |
| Sleeper Pick | bottom 20% |

4. **Freeze** the resulting R′ values and record them here.

**Decision: thresholds per prompt group — award, stat, college (added 2026-11-11), and other.** Steps 1–4 run separately for each group (same 10/35/35/20 split, same equal per-prompt weighting), and each prompt is scored against its group's frozen values.

| Group | Prompts | Calibration set |
|---|---|---|
| award | trait prompts with an `award` or `award_any` filter, or an honors filter (`hall_of_fame`, `all_pro`, `pro_bowl`, `draft`) | all six AP awards (MVP, OPOY, DPOY, OROY, DROY, Comeback) |
| stat | trait prompts with a `stat_threshold`, `rookie_stat`, `game_stat` or `window_stat` | 10+ sacks, RB 1,000+ rushing, TE 800+ receiving, QB 4,000+ passing, DB 5+ INT, WR 100+ receptions |
| college | trait prompts with a `college` filter | 8 school + position prompts with 40+ answers: Ohio State WR, LSU DB, Miami (FL) LB, Florida State DB, Penn State LB, Notre Dame OL, USC WR, Michigan DL |
| other | everything else | 15 prompts: 6 easy, 6 two-team (live versions), 3 era |

Reasons:
- **Trait vs other:** `A = 1` for trait prompts puts them on a different scale. With one shared set, award and stat prompts filled most of the pooled top 10% and couldn't produce Hidden Gems or Sleepers (AP MVP came out 30 Starters · 21 Backups · 0 · 0), while team prompts got only 1–8 Starters each.
- **Award vs stat:** award winners are a much more famous pool than stat qualifiers. With one trait set, stat prompts spread across all four tiers but award prompts produced almost no Sleepers (AP MVP 9 · 32 · 10 · 0, Comeback 4 · 16 · 6 · 1).

`data/tier_thresholds.json` holds the frozen values per group; prompts are routed by `threshold_kind()`.

**Frozen thresholds** (2026-11-08, `prompts/calibration.jsonl`: other 15 prompts / 1,638 answers, award 6 / 284, stat 6 / 743; 24-month pageview signal; prominence in association). Lower bounds on R′:

| Group | Starter | Backup | Hidden Gem | Sleeper Pick |
|---|---|---|---|---|
| other | 0.2754 | 0.0892 | 0.0324 | below 0.0324 |
| award | 0.7155 | 0.4705 | 0.3270 | below 0.3270 |
| stat | 0.5542 | 0.3114 | 0.1945 | below 0.1945 |
| college | 0.3696 | 0.1587 | 0.0676 | below 0.0676 |

- **Honors filters use the award group (decided 2026-11-11).** `hall_of_fame`, `all_pro`, `pro_bowl` and `draft` route to award (F = s_pv) like Super Bowl MVP and Heisman (which are `award` values). On 23 probes: award thresholds pass 19 (failures are pool size: All-Pro TE/WR); stat thresholds pass 5 (honors pools are famous, like award winners: Super Bowl MVP 13 · 27 · 9 · 0, #1 pick 6 · 26 · 14 · 0); calibrating the honors probes as their own group (0.6454 / 0.4246 / 0.2910) passes 18 and drops Super Bowl MVP and first-round QB below 3 Sleepers. So no new group; award's frozen values are unchanged.
- **Weekly stat filters use the stat group (decided 2026-11-11).** On the 9 probe prompts with 25+ answers (`prompts/weekly_stat_probe.jsonl`), the stat thresholds give a pooled 10 / 30 / 34 / 26% (target 10 / 35 / 35 / 20), and calibrating those prompts alone would give 0.5487 / 0.2950 / 0.1741, within ~0.02 of the stat values. Failures come from the pool (famous QBs: QB 5+ TD game 9 · 38 · 9 · 0), not the scale, so no new group.
- **College group added 2026-11-11** (`--groups college`; the other groups keep their values). College pools are every player from a school at a position, with no production bar, so they run deeper than stat pools (stat qualifiers all had a big season): on the stat thresholds Miami (FL) any position came out 7 · 22 · 42 · 273 and LSU DB 2 · 5 · 13 · 48; on "other" (A = 1 inflates R) Ohio State WR got 0 Sleepers. Calibration set: 8 prompts / 463 answers, same 10/35/35/20 split, equal per-prompt weighting; Alabama RB and Georgia RB (39 each) missed the 40-answer bar. Spread (Starter · Backup · Hidden Gem · Sleeper + YKB Kid): Ohio State WR 7 · 22 · 17 · 3 + Reggie Germany, LSU DB 6 · 19 · 22 · 21 + Anthony Marshall, Miami (FL) LB 5 · 19 · 20 · 9 + Spencer Adkins, Florida State DB 5 · 21 · 17 · 11 + Walt Sumner, Penn State LB 7 · 22 · 30 · 17 + Glenn Carson, Notre Dame OL 5 · 22 · 22 · 17 + Mike Brennan, USC WR 6 · 17 · 15 · 11 + Will Buchanon, Michigan DL 4 · 16 · 18 · 2 + Kerwin Waldroup (fails the ≥ 3 Sleeper rule; don't ship as is).

- **Award recalibrated 2026-11-08** for award `F = s_pv` (above): same 6 prompts / 284 answers, same 10/35/35/20 split, equal per-prompt weighting. Was 0.6832 / 0.4495 / 0.2993. With the old F, today's data reproduces the old award values exactly, so the whole shift comes from the F change. Only the award group was refrozen (`--groups award`): rerunning other on today's data gives slightly different values (1,621 answers; Backup 0.0900), from data refreshes since the freeze rather than any rule change, so other and stat keep their recorded values.
- Award calibration spread after the change (Starter · Backup · Hidden Gem · Sleeper): MVP 6 · 18 · 23 · 4, DPOY 3 · 16 · 15 · 9, OROY 4 · 17 · 19 · 19, OPOY 5 · 18 · 19 · 2, DROY 2 · 14 · 15 · 29, Comeback 5 · 12 · 8 · 2.

Change these only by rerunning the calibration (`probe --calibrate prompts/calibration.jsonl --freeze`, or `--groups award` etc. to refreeze only some groups) with a recorded reason.

Each prompt is then scored against the same frozen values, so hard prompts naturally get few Starters and easy prompts get many. There are no per-prompt quotas.

**After launch:** rerun the pooled calibration with real answer data, and use real data to tune weights, δ, and thresholds.

---

## 8. Probe tool (test a question before committing)

A cheap, local dry run of Step 1 (plus an optional tier preview from cached scores). Exposed as a Claude Code slash command in `.claude/commands/probe.md`:

```
/probe Name a 90s AFC QB
```

Claude's only job: translate the question into the filter format (§5), run `probe`, report results. No web research.

Output:
```
"Name a 90s AFC QB"  →  conference=AFC, position=QB, seasons 1990–1999
Valid answers: 214   ✅ (≥ 25)
Sample (top):    Elway, Marino, Kelly …
Sample (bottom): …
Edge cases: N players with 0 starts excluded
Tier preview: Starter 12 · Backup 70 · Hidden Gem 85 · Sleeper Pick 47
```

Also supports **batch mode** (a file of draft questions → one summary table).

---

## 9. Version 1 scope

**In:** daily set of prompts, same for everyone; timer per prompt; answer matching (below); scoring and tiers; All Answers screen; pick stats; share; streaks and W–L record in local storage; anonymous answer logging; ~14 days of prompts queued at launch.

**Answer matching** (reference implementation: `src/football_trivia/matching.py`; the UI ports it)
- Matches on **full names** (display, legal first + last, common first name + last), **first-name variants** (Mike/Michael, Pat/Patrick, Bill/William, …), **unique last names** ("Mahomes" → Patrick Mahomes), and **typo tolerance** (Damerau-Levenshtein; allowed edits by length: ≤ 3 chars 0, ≤ 6 chars 1, ≤ 12 chars 2, longer 3).
- **No nickname list in v1** ("Megatron", "T.O." don't match).
- A real player who isn't valid for the prompt is rejected, including when a typo is at least as close to him as to any valid answer.
- **Ambiguous last name within a prompt:** the UI asks for a first name ("Which Smith?") instead of guessing. The same applies when a typo ties between two valid answers.
- **Identical full names within a prompt** (e.g. two Steve Smiths on "WR 1,200+ receiving yards": Panthers 1,563 yds · 2005 and Giants 1,220 yds · 2009): asking for a first name can't separate them, so the UI lists the tied answers with their **context lines** and the player taps one.
- Measured on the 14-day draft (one random typo per answer, 9,291 answers): 98.6% matched the right player, 0 the wrong one, 0.2% ambiguous, 1.3% rejected.

**Answer submission** (playtest rules, decided 2026-11-08)
- **Retries:** a guess that isn't a valid answer (an unknown name, or a real player who doesn't fit the prompt) does **not** end the play. The input shakes, "Not on the board" shows briefly, the box clears, and the clock keeps running. Players keep guessing until they hit a valid answer or the clock runs out. Repeating the same wrong guess just shakes again. An empty submit does nothing.
- **Autocorrect confirmation:** when a match needed typo correction (a fuzzy match, not an exact name, first-name variant or exact unique last name), the UI asks "Did you mean <Name>?" with the context line and Yes / No while the clock keeps running. Yes locks it in; No (or Escape) clears the box to guess again.
- **Clock hits 0:00:** whatever is typed is submitted once through the matcher. A valid match counts, including a fuzzy one (accepted without asking). An open "Did you mean" is accepted. Otherwise the play is **Incomplete** (0 yards).
- A play is Incomplete only when time expires without a valid answer. If the clock runs out while a "Which Smith?" picker is open, or the timeout submit is ambiguous, no answer was chosen, so the play is Incomplete.

**All Answers screen**
- Unlocks after the 7th play. Tabs **P1–P7**, one per prompt.
- Scrollable list per prompt, sortable by **tier** or **A–Z**, with **search** (same matcher as answer entry: names, first-name variants, last names, typos).
- **Your pick** and the **YKB Kid** are pinned at the top.
- Each row shows the player's name, the **context line** (§6 answer bank export), and **pick stats**.

**Pick stats** (from anonymous answer logging)
- Fewer than 100 logged answers for the prompt: show share of players (`14% of players`, `Under 1% of players`).
- 100 or more: show raw counts (`291 players`).

**Share**
- `navigator.share()` on mobile; elsewhere copy to clipboard and show "Copied!".
- Text format:
  ```
  Griddion Drive #<n> 🏈
  <result line>
  <7 tier squares>
  griddion.io
  ```
- Result line (see *Drive outcome* below):
  - TD on play 7: `TOUCHDOWN · W 24–21 · 375 pts`
  - TD before play 7: `TOUCHDOWN on P5 · W 24–21 · 410 pts`
  - No TD: `STALLED at <ball spot> · L 17–21 · <pts> pts`, e.g. `STALLED at OPP 24 · L 17–21 · 255 pts`
- Tier squares, one per prompt in order: ⬜ Starter · 🟦 Backup · 🟩 Hidden Gem · 🟪 Sleeper Pick · 🟨 YKB Kid · 🟧 Botched Trick Play · ⬛ Incomplete.

**Drive outcome** (how a game becomes the drive in the share line)
- **Yards per answer = tier points ÷ 5:** Starter 2 · Botched Trick Play 3 · Backup 6 · Hidden Gem 12 · Sleeper Pick 17 · YKB Kid 20 · invalid / no answer 0.
- **Game state:** the player trails **17–21**, 4th quarter, **2:55** left, ball on their **own 25**.
- **Touchdown** = 75 cumulative yards (= 375 points) → final **W 24–21**. No TD after 7 plays → final **L 17–21** (down 4, so a field goal never wins).
- **Clock:** 2:55 minus 0:25 per play, reaching 0:00 after play 7.
- **Ball spot** (yardline = 25 + cumulative yards): below 50 → `OWN x`; 50 → `MIDFIELD`; above 50 → `OPP (100 − x)`.
- **TD before play 7:** all 7 plays are still played and scored. The ball stays in the end zone, the remaining plays show as running out the clock, and the result reads `TOUCHDOWN on P<n>`.

**Drive, streak, record**
- **Drive #** = days since launch, the same for everyone. **Launch: 2026-11-09 = Drive #1**; the drive rolls over at **00:00 America/New_York** (`(today_ET − launch_date).days + 1`).
- **Streak** = consecutive days played. A separate **W–L record**. Both in local storage.

**Anonymous answer logging**
- For every submitted answer, record **prompt id**, **matched player id** (or `invalid`), and **tier**. Nothing else: no accounts, no personal data, no device or user identifiers.
- Used for pick stats and for tuning the formula after launch (§1, §7).
- **Hosting (decided):** the static game on **Cloudflare Pages** at griddion.io; logging on a **Cloudflare Worker + D1** (managed SQLite) on the same domain. One table `answers(prompt_id, player_id, tier, day)`; `POST /log` writes a row, `GET /stats/<prompt_id>` returns per-player counts for pick stats (cacheable briefly). Per-IP rate limiting at the Worker; IPs are not stored. Why: no server to run, free tier covers launch traffic, same origin as the game (no CORS or third-party scripts), and SQL makes post-launch tuning queries easy.

**Player feedback** (added 2026-11-11; built in `worker/`, **not deployed**)
- `POST /feedback` on the same Worker + D1: `{ "drive": int, "rating": 1–5, "message": optional string ≤ 500 chars, "device": "mobile" | "desktop" }` → `201 {"ok":true}`.
- Stored in `feedback(id, created_at, drive, rating, message, device)`: `created_at` is server time (UTC). **No IPs, user agents or other personal data.**
- Abuse limits: strict validation (unknown fields, wrong types, out-of-range values → 400; `drive` must be between 1 and today's Drive # + 1), JSON only (415), body ≤ 2 KB (413), Origin must be griddion.io when present (403), **5 requests / minute per client** (429, `Retry-After: 60`) via the Workers Rate Limiting API, keyed on a hash of the IP that is counted at the edge and never stored.
- Reading it: `worker/README.md` (D1 console in the Cloudflare dashboard, example queries) and `worker/scripts/export-feedback.mjs` (CSV export, `npm run export:feedback`).
- Go-live steps (create D1, apply `worker/migrations`, uncomment `routes`, `wrangler deploy`) are in the README. Answer logging (`POST /log`, `GET /stats/<prompt_id>`) goes in the same Worker.

**Out (later):** accounts, unlimited mode, archive, leaderboards, themed packs.

---

## 10. Build order

1. `refresh`: local data cache (nflverse + Wikipedia awards + Wikipedia QB lists + pageviews)
2. Step 1 `build_answers` + `/probe`
3. Step 2 `score_answers` + games-fallback comparison test (QBs)
4. Threshold calibration on ~20 prompts; freeze values
5. Answer matching (full names, first-name variants, unique last names, typo tolerance)
6. Game UI
7. Prompt scheduling + publish flow

---

## 11. Open items

- Backlog: Wikipedia milestone lists for marquee stat thresholds (2,000-yd rushing season, 5,000-yd passing season, …) where a clean list exists, so those prompts can cover all eras
- Games-fallback approval for QBs (pending comparison test)
- **Known limit: no `peak` before 1999.** Season stats start in 1999, so pre-1999 era prompts can't rescue a short, famous tenure with `peak`, and those players read as low association (e.g. Joe Montana's 1990 season on "NFC QB from the 1990s" is a 1-of-many-seasons stint: A ≈ 0.21). Revisit with real answer data after launch.
- **Known issue: honors and career length penalize recent players (all prompt types).** `s_honors` and `s_career` grow with time in the league, so a recent player reads as less famous than his real recall (a rookie has at most 1 season and few honors). Award prompts sidestep it with `F = s_pv` (§7, 2026-11-08). **Option (b), to revisit with real answer data:** scale career length by *possible* seasons (seasons since debut, capped at 15) instead of absolute seasons, and don't apply an honors penalty in a player's early years. This would apply to all prompt types and could let award prompts go back to the blended F.
- ~~Game title~~ — **resolved:** Griddion (griddion.io)
