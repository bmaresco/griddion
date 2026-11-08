# Gridion — Project Spec

A daily football trivia game. Each day has a set of prompts ("Name a Bears QB"). Players type one answer per prompt against a timer. Any valid answer scores, and **the more obscure the answer is for that specific question, the more it's worth.**

> **Gridion** ([gridion.io](https://gridion.io)). Inspired by the rare-answer mechanic of Krillion, but uses none of its name, branding, or tier names.

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

- **YKB Kid** is chosen manually from the Sleeper Pick / Hidden Gem answers. It's the most satisfying deep pull, not necessarily the rarest.
- **Botched Trick Play** is never assigned automatically. The pipeline may *suggest* at most one candidate per prompt (a high-fame player with low association to the prompt). The human decides, and most prompts have none.

---

## 3. Validity rules

- **QBs** (team, era, or conference prompts): must have **started at least one regular-season game** in the qualifying context, for all eras. The prompt subtitle shows: *"QBs must have started a regular-season game."*
- **All other positions**: must have **played in at least one regular-season game** in the context. Preseason and playoff-only appearances don't count.
- **Trait prompts** (awards, stat thresholds, e.g. "won OROY and MVP," "1,500+ receiving yard season"): the trait alone qualifies the player.
- **Position** is the player's listed position in the qualifying seasons (e.g. a gadget player counts as a QB only for seasons he started at QB).
- Example: Andy Dalton (0 starts for PHI in 2026) is **not** a valid "Eagles QB" answer.

**Known exception — pre-1999 non-QBs.** There is no games-played data before 1999, so we can't confirm these players appeared in a game. For non-QBs in seasons before 1999, **being on the active regular-season roster** (see *Roster status* below) in the context counts as valid. The rules for QBs and for non-QBs from 1999 on are unchanged.

**Known exception — pre-1950 QBs.** The Wikipedia starting-QB lists begin in 1950, so there are no starts before then. Pre-1950 QBs are **not excluded** (Sid Luckman must be a valid Bears QB): they use the roster rule, by listed position (QB on the active roster). `/probe` lists them separately for review.

**QB starts source.** Wikipedia's "List of [team] starting quarterbacks" is the primary source for **every season**. nflverse is the cross-check. The exception is **Green Bay and the Rams from 1999 on**, where the Wikipedia pages give only per-player totals, so nflverse is used. Reason: nflverse's schedule `qb_id` is the QB with the most passes, not the starter (e.g. it credits Garoppolo with Brady's 2014 week 17 start and shows Jayden Daniels with 12 of his 17 2024 starts). Current-season mismatches between the two are **flagged in `/probe` and the diff report, never silently resolved**.

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
| **Wikipedia "List of [team] starting quarterbacks"** (CC BY-SA, all 32 franchises) | QB starts, **primary source for every season** (see §3). Cross-checked against nflverse; mismatches flagged |
| **`data/team_alignment.csv`** (hand-maintained, reviewable) | League, conference and division per franchise-season, 1950→now, including the AFL 1960–69 |
| **Wikimedia Pageviews API** | Player fame (pageviews, available from mid-2015 onward) |
| **Wikidata** (CC0) | ID crosswalk only: Pro Football Reference ID → Wikipedia article |

- Do **not** scrape Pro Football Reference, StatMuse, ESPN, NFL.com, or Yahoo. They are for manual spot-checks only.
- Do **not** use Pro Football Reference data or old NFL.com scrapes from any source (e.g. `zackthoutt/nfl-player-stats`). Licensing is unclear. (Using the PFR *ID string* from Wikidata purely as a join key is fine.)
- **Aliases:** generated from nflverse name fields (full name, first/last, common short forms), plus a hand-maintained `data/aliases.csv` for nicknames and misspellings.

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
- `stat_threshold` (e.g. receiving yards ≥ 1500 in a single season)

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

### Checks between steps
- **< 25 valid answers → hard stop.** Widen or drop the prompt.
- **Per-day check: average valid answers across a day's 7 prompts > 300 → warning only.** Keeps a day reviewable and aliasable without capping any single prompt. (Replaces the earlier per-prompt 300 warning.)
- **Diff report** against the last build (new or removed answers, tier changes).
- **Tier spread warnings** (zero Starters, very top-heavy or bottom-heavy). These are warnings only. The spread is never forced.
- **Human review** of every answer bank before publishing, to catch rule bugs and edge cases.

---

## 7. Rarity formula

All components are 0–1. Every default below has a written reason. Change a number only with a reason, recorded here.

### Fame, F (per player, same for every prompt)
```
F = 0.60·s_pv + 0.25·s_honors + 0.15·s_career

s_pv     = clamp( (log10(pv24) − log10(30)) / (log10(300000) − log10(30)), 0, 1 )
s_honors = clamp( honors_points / HONORS_CAP, 0, 1 )
s_career = clamp( seasons / 15, 0, 1 )
```
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
share   = context_units / career_units        (unit per the rules below)
peak    = best qualifying-season production / career-best season production
A       = max( sqrt(share), peak )               for team / era prompts
A       = max( A_team1, A_team2 )                for two-team prompts
A       = 1                                       for trait prompts
```
- `sqrt` softens the drop-off: half a career ≈ 0.71.
- `peak` keeps a memorable short stint (one great season with a team) from being treated like a cameo.
- **`peak = min(1, best qualifying-season production ÷ benchmark)`**, for **QB, RB, WR, TE** only. A season's listed position picks the metric. All other positions use **`A = sqrt(share)`** only. Season stats start in 1999, so qualifying seasons before 1999 contribute no peak.

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
2. Pool every answer's R′ across all prompts.
3. Set thresholds at these pooled percentiles:

| Tier | Share of pooled answers |
|---|---|
| Starter | top 10% |
| Backup | next 35% |
| Hidden Gem | next 35% |
| Sleeper Pick | bottom 20% |

4. **Freeze** the resulting R′ values and record them here.

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

**In:** daily set of prompts, same for everyone; timer per prompt; fuzzy matching with alias support; scoring and tiers; post-game reveal; streaks in local storage; share card; ~14 days of prompts queued at launch.

**Out (later):** accounts, unlimited mode, archive, leaderboards, themed packs.

---

## 10. Build order

1. `refresh`: local data cache (nflverse + Wikipedia awards + Wikipedia QB lists + pageviews)
2. Step 1 `build_answers` + `/probe`
3. Step 2 `score_answers` + games-fallback comparison test (QBs)
4. Threshold calibration on ~20 prompts; freeze values
5. Answer matching (aliases, fuzzy)
6. Game UI
7. Prompt scheduling + publish flow

---

## 11. Open items

- Backlog: Wikipedia milestone lists for marquee stat thresholds (2,000-yd rushing season, 5,000-yd passing season, …) where a clean list exists, so those prompts can cover all eras
- Games-fallback approval for QBs (pending comparison test)
- ~~Game title~~ — **resolved:** Gridion (gridion.io)
