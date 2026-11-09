# Griddion — UI Build Handoff (launch tonight)

Build the playable game UI for Griddion and deploy it to griddion.io tonight. The data side (answer banks, tiers, matching, schedule) is done in this repo. This doc is everything the UI needs. The six attached `*.dc.html` files are the approved screen designs: match their layout, colors, fonts, sprites and animations. They're design-tool files, so read them for markup, CSS, sprite maps and keyframes; don't ship them as-is.

Work on a branch named `ui`. Read CLAUDE.md first (§2 tiers, §6 answer bank export format, §9 v1 scope and drive rules).

---

## 1. Launch-tonight scope

**Must ship tonight**
1. Intro huddle → 7 plays → per-play result → recap (touchdown or stalled)
2. Answer matching (port `src/football_trivia/matching.py` to the client)
3. Scoring, tiers, yards, game clock, drive outcome (§9 rules)
4. Local storage: resume mid-game, streak, W–L record, completed-today lock
5. Share (navigator.share + clipboard fallback)
6. All Answers screen (tabs, sort, search, pinned rows, context lines). Hide pick stats if logging isn't live.
7. Deploy: Cloudflare Pages at griddion.io

**OK to defer to tomorrow:** anonymous answer logging (Worker + D1) and pick stats, extra play animations beyond the four presets below.

Stack: keep it small. Vite + TypeScript, no heavy framework (vanilla or Preact). Static build, so Cloudflare Pages serves it directly.

---

## 2. Data contract

- Read the daily answer bank export defined in CLAUDE.md §6, one file per day, produced by the step 7 publish flow.
- Each answer carries: player id, display name, aliases/name variants, tier, context line, and the prompt's YKB Kid.
- Drive # = days since launch date (ET). Day rolls over at midnight America/New_York. Launch date: **2026-11-08** (Drive #1 = today).
- If the publish flow doesn't yet emit per-day files in a static-hostable form, add that first: `public/days/<drive#>.json`.

---

## 3. Game rules (from §9, do not change)

- 7 prompts per day, one answer each, **25 seconds** per prompt.
- Tier → points → yards (yards = points ÷ 5) → play name:

| Tier | Points | Yards | Play | Color |
|---|---|---|---|---|
| Starter | 10 | 2 | Run up the middle | #7a8191 |
| Botched Trick Play | 15 | 3 | Reverse, stuffed | #d4661c |
| Backup | 30 | 6 | Quick slant | #1f6fd1 |
| Hidden Gem | 60 | 12 | Deep out | #198a4a |
| Sleeper Pick | 85 | 17 | Deep bomb | #7b3fc4 |
| YKB Kid | 100 | 20 | Hail Mary | #e0a800 |
| Invalid / timeout | 0 | 0 | Incomplete | #4a4a55 |

- Drive starts at **own 25**. TD = 75 cumulative yards (375 pts).
- Situation: player trails **17–21**, 4th quarter, **2:55**. Clock drops 0:25 per play and hits 0:00 after play 7.
- TD → final **W 24–21**. No TD → final **L 17–21**.
- TD before play 7: keep playing all 7 for points; ball stays in end zone; result reads "TOUCHDOWN on P<n>".
- Ball spot label: <50 "OWN x", 50 "MIDFIELD", >50 "OPP (100 − x)".

### Answer submission
- Match with the ported matcher: exact name (incl. first-name variants), unique last name, typo tolerance; real-but-invalid player → Incomplete.
- **Ambiguous** (two valid players share the input): keep the timer running and ask "Which Smith?" with the candidates as buttons.
- **Superseded by the playtest rules in CLAUDE.md §9 *Answer submission* (2026-11-08):** wrong guesses retry until the clock runs out, typo matches ask "Did you mean…?", and the clock submits whatever is typed at 0:00. Incomplete only if time expires without a valid answer.

---

## 4. Screens (see design files)

All screens: mobile-first 390px column, centered on desktop with the night-stadium background filling the window.

1. **Intro huddle** (`Intro.dc.html`): jumbotron scoreboard (YOU 17 · AWAY 21 · 4TH QTR · 2:55 blinking), field with offense in a huddle at own 25, defense waiting, chain crew. Wristband "Coach's Call" card with this exact copy:
   > Your team is down 4 points with 2:55 left in the game. Use your ball knowledge to get your team down the field and complete the game-winning drive!

   Then "7 PLAYS · 25 SECONDS EACH · RARER ANSWERS GO DEEPER" and a **BREAK THE HUDDLE** button.
2. **Play** (`Main.dc.html`): jumbotron shows PLAY n OF 7, the prompt (uppercase), subtitle, 25-segment LED timer + countdown; footer BALL spot + PTS. Field with 11v11 pre-snap formation at the current spot, chains at spot and spot+10. Wristband: 7-cell drive log (current cell highlighted), CALL IT input, SNAP button, tier/play key.
3. **Result** (`Result.dc.html`): jumbotron flashes tier name, player name, "PLAY · +YDS · +PTS"; field runs the play animation; wristband shows the context line and NEXT PLAY.
4. **Recap: touchdown** (`Recap.dc.html`): TOUCHDOWN!, YOU 24 – 21 AWAY, totals, 7 LED squares, footer "DRIVE #n COMPLETE · PTS"; field celebration; wristband drive chart (7 rows: play, tier chip, yards), SHARE and ALL ANSWERS.
5. **Recap: stalled** (`Stalled.dc.html`): DRIVE STALLED, YOU 17 – 21 AWAY, "<n> YDS SHORT · RECORD", defense celebrating, offense slumped.
6. **All Answers** (`Answers.dc.html`): tabs P1–P7 (bar = your tier), TIER / A–Z sort, alias-aware search, pinned YOUR PICK + YKB KID rows, sticky tier headers, each row = name + context line + pick stats. Unlocks only after play 7.

Header bar everywhere: GRIDDION + "STREAK n · xW yL".

---

## 5. Visual system

- **Colors:** night bg #160f33 / #0f0b26, stands #211a45, jumbotron frame #2b2b33, LED amber #ffb43a / dim #c98a2e, header red #c8352f, paper #efe6cf, ink #1d1a14, muted ink #6b6253, highlighter #ffe27a. Teams: home #2f5bd3, away #c8352f. Tier colors in table above.
- **Fonts:** DotGothic16 (jumbotron), Silkscreen (logo, buttons, section titles), Courier Prime (everything else).
- **Pixel font rule:** DotGothic16 only at 16/32/48px; Silkscreen only at 8/16/24px. Courier Prime for any small or in-between label. Set `-webkit-font-smoothing: none` on pixel-font text.
- **Sprites:** reuse the box-shadow pixel sprite approach from the design files (player facing L/R, coach, ref, ref-TD, chain crew, cheering player, slumped player, ball). 2px pixels, field 360×200, 3px per yard. Sideline players stand in loose staggered clusters, not rows.
- **Field:** alternating 10-yard stripes, white yard lines, 5-yard lines, hash marks, end zones home-blue/away-red, line of scrimmage blue, first-down line yellow.

---

## 6. Animations (CSS keyframes, all in the design files)

- **Pre-snap:** idle bob for everyone (steps), slot receiver in motion, crowd camera flashes.
- **Plays after an answer** (tonight, 4 presets):
  - Run (Starter, Reverse): line pushes, RB gains a short distance.
  - Short pass (Backup): quick throw to a receiver a few yards out.
  - Deep pass (Hidden Gem, Sleeper Pick, YKB Kid): QB drops back, ball arcs to the receiver, defenders chase (see `bomb`/`route`/`chase` keyframes). Scale distance to the yards gained.
  - Incomplete: ball falls short, no gain.
- **Touchdown:** players jump, ref signals TD, confetti falls.
- **Stalled:** defense and visiting sideline jump; offense slumps.
- Respect `prefers-reduced-motion` (turn all animation off).

---

## 7. Local storage

- Today's in-progress game (drive #, answers, timer state) so a refresh resumes it.
- `streak` = consecutive days played (missing a day resets it; a loss does not).
- `wins`, `losses` (separate from streak).
- Completed-today lock: after play 7, reopening goes to the recap.
- Wrap all storage access in try/catch; the game must still work without it.

---

## 8. Share

- `navigator.share()` on mobile; fallback copies to clipboard with a "Copied!" toast.
- No answers in the text. Format:

```
Griddion Drive #<n> 🏈
TOUCHDOWN · W 24–21 · 375 pts
⬜🟩🟪🟦🟦🟩🟨
griddion.io
```

- Variants: "TOUCHDOWN on P5 · W 24–21 · 410 pts"; "STALLED at OPP 24 · L 17–21 · 255 pts".
- Squares: ⬜ Starter, 🟦 Backup, 🟩 Hidden Gem, 🟪 Sleeper Pick, 🟨 YKB Kid, 🟧 Botched Trick Play, ⬛ Incomplete.

---

## 9. Pick stats (only if logging is live)

Per prompt: under 100 logged answers show share ("14% of players", "Under 1% of players"); at 100+ show counts ("291 players"). If logging isn't live tonight, hide the stats column.

---

## 10. Accessibility & quality bar

Real `<button>`, `<label>`, `<input>`; icon-only buttons get `aria-label`; field is `role="img"` with a short description; text contrast ≥ 4.5:1; touch targets ≥ 44px; works at 360px wide; no horizontal scroll.

---

## 11. Before going live tonight

1. Play Drive #1 start to finish on a phone-size viewport: touchdown path and stalled path.
2. Verify Drive #1's 7 answer banks render in All Answers with context lines.
3. Test resume after refresh, and the next-day rollover (mock the date).
4. Deploy to Cloudflare Pages, connect griddion.io, confirm HTTPS.
