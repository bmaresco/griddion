# Football Rare-Answer Trivia — Project Spec

A daily football trivia game. Each day has a set of prompts ("Name a Bears QB"). Players type one answer per prompt against a timer. Any valid answer scores, and **the more obscure the answer is for that specific question, the more it's worth.**

> Working title TBD. Inspired by the rare-answer mechanic of Krillion, but uses none of its name, branding, or tier names.

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

**Known exception — pre-1999 non-QBs.** There is no games-played data before 1999, so we can't confirm these players appeared in a game. For non-QBs in seasons before 1999, **being on a regular-season roster** in the context counts as valid. The rules for QBs (all eras) and for non-QBs from 1999 on are unchanged.

---

## 4. Data sources (all reusable, no scraping)

| Source | Used for |
|---|---|
| **nflverse** (`nflreadpy`) | Rosters, games, QB starts (1999+), season stats, player IDs/cross-refs, names |
| **Wikipedia** (CC BY-SA) | Awards (MVP, OPOY, DPOY, OROY, DROY), Pro Bowl / All-Pro, Hall of Fame |
| **Wikipedia "List of [team] starting quarterbacks"** (CC BY-SA, all 32 franchises) | QB starts **before 1999**. Seasons from 1999 on use nflverse. Overlap years are cross-checked and mismatches flagged |
| **Wikimedia Pageviews API** | Player fame (pageviews, available from mid-2015 onward) |
| **Wikidata** (CC0) | ID crosswalk only: Pro Football Reference ID → Wikipedia article |

- Do **not** scrape Pro Football Reference, StatMuse, ESPN, NFL.com, or Yahoo. They are for manual spot-checks only.
- Do **not** use Pro Football Reference data or old NFL.com scrapes from any source (e.g. `zackthoutt/nfl-player-stats`). Licensing is unclear. (Using the PFR *ID string* from Wikidata purely as a join key is fine.)
- **Aliases:** generated from nflverse name fields (full name, first/last, common short forms), plus a hand-maintained `data/aliases.csv` for nicknames and misspellings.

### Coverage (confirmed in step 1)

| Data | Available |
|---|---|
| Roster membership + listed position | 1920 → now |
| QB starts | 1999 → now (nflverse); pre-1999 from the Wikipedia QB lists |
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
- **> 300 valid answers → warning.** Too many to review and alias well.
- **Diff report** against the last build (new or removed answers, tier changes).
- **Tier spread warnings** (zero Starters, very top-heavy or bottom-heavy). These are warnings only. The spread is never forced.
- **Human review** of every answer bank before publishing, to catch rule bugs and edge cases.

---

## 7. Rarity formula

All components are 0–1. Every default below has a written reason. Change a number only with a reason, recorded here.

### Fame, F (per player, same for every prompt)
```
F = 0.60·pct(pageviews) + 0.25·pct(honors) + 0.15·pct(career_length)
```
- `pageviews` = lifetime Wikipedia pageviews (log-scaled before ranking). **Main signal** for how known a player is.
- `honors` = Pro Bowls + All-Pro (weighted higher) + Hall of Fame (weighted highest). Protects pre-internet stars whose pageviews undercount their fame. **TODO:** set exact weights with a written reason.
- `career_length` = seasons played or starts. Separates a 10-year starter from a one-season player.
- `pct()` = percentile across all players in the database.
- Decision: college or off-field fame in pageviews (e.g. a famous college QB) is **kept**. Fans who know the player are more likely to recall his NFL stops too.

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
- **TODO:** define the per-position production metric for `peak`.

**Units:**
- **QBs: starts.** Wikipedia QB lists before 1999, nflverse from 1999 on, so full history.
- **Everyone else: seasons on roster** (seasons with the team ÷ career seasons). Available for every player back to 1920.
- **Games** only where they are complete (2013+, all positions) **and** they improve the result.
- **One unit per prompt.** Never mix units within a prompt: if any valid answer lacks the chosen unit, score every player in that prompt with the fallback.
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
Valid answers: 214   ✅ in range (25–300)
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

- Honors weights within F
- Per-position production metric for `peak`
- Wikipedia QB-list ingestion + cross-check with nflverse
- Games-fallback approval for QBs (pending comparison test)
- Game title
