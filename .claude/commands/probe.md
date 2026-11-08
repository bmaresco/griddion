---
description: Dry-run a draft trivia prompt against the local DB (spec §8)
argument-hint: <question text>, or --file prompts.jsonl
---

Probe this draft prompt: $ARGUMENTS

Your only job (spec §8): translate the question into the structured filter format, run `probe`, and report what it prints. **No web research, no editing data, no adjusting individual players.**

1. Translate the question into prompt JSON (spec §5):
   - `team`: franchise code, current abbreviation (CHI, GB, LV, LAC, LA (Rams), ARI, IND, TEN, NE, …). "Baltimore Colts" = `IND` + `season_max: 1983`; "Houston Oilers" = `TEN` + `season_max: 1996`; "St. Louis Rams" = `LA` + seasons 1995–2015.
   - `teams_all`: ["NYJ", "MIN"] for "played for both"; `type: "two_team"`.
   - `position`: QB RB WR TE OL DL LB DB K P LS, or a specific code (CB, FS, …).
   - `conference` (AFC/NFC, 1970+), `division` ("NFC North", "AFC Central", "Coastal", "AFL Eastern"), `league` (NFL/AFL).
   - `season_min` / `season_max`: "90s" = 1990–1999, "since 2000" = `season_min: 2000`.
   - `award`: mvp, opoy, dpoy, oroy, droy, comeback (AP only); a list means "won all of these". `type: "trait"`.
   - `stat_threshold`: {"stat": "receiving_yards", "min": 1500}; stats: passing_yards, passing_tds, rushing_yards, rushing_tds, receiving_yards, receiving_tds, receptions, scrimmage_yards, sacks, interceptions. Seasons 1999+ only.
   - `type`: team | era | two_team | trait.
2. Run it from the project root:
   `uv run probe '<prompt JSON>'` (add `--all` to list every answer). For a file of prompts: `uv run probe --file <path>` (one prompt JSON per line).
3. Report the probe output as printed. Then add one line for anything that needs a human: hard stop (< 25), > 300, pre-1950 QBs listed for review, excluded edge cases, QB source mismatches, or warnings. If the question can't be expressed with these filters, say which part and stop.
