# Griddion API Worker

Cloudflare Worker + D1 on the same origin as the game (spec §9). **Not deployed.** Nothing here
runs on griddion.io until the database is created, the `routes` line in `wrangler.toml` is
uncommented, and `npx wrangler deploy` is run.

## Endpoint

`POST /feedback`, `Content-Type: application/json`

```json
{ "drive": 3, "rating": 4, "message": "optional, up to 500 characters", "device": "mobile" }
```

| Field | Rule |
|---|---|
| `drive` | integer, 1 to (days since the original launch + 1) + 1. An upper bound: real drive numbers come from `schedule.json` and only lag that count after a relaunch shift; +1 covers a page left open past midnight ET |
| `rating` | integer 1–5 |
| `message` | optional string, ≤ 500 characters after trimming; blank → stored as NULL |
| `device` | `"mobile"` or `"desktop"` |

Responses: `201 {"ok":true}` · `400 {"error": "..."}` (bad JSON, unknown field, wrong type or range) ·
`403` (Origin other than griddion.io) · `405` (not POST) · `413` (body > 2 KB) · `415` (not JSON) ·
`429` + `Retry-After: 60` (more than 5 requests a minute from one client).

**Stored:** `id`, `created_at` (server time, UTC), `drive`, `rating`, `message`, `device`. No IP,
user agent, cookie or other identifier. The rate limiter counts per client at the edge on a hash
of the IP; that key is never written to D1 or logged.

## One-time setup (when it's time to go live)

```sh
cd worker && npm install
npx wrangler login
npx wrangler d1 create griddion             # paste the database_id into wrangler.toml
npx wrangler d1 migrations apply griddion --remote
# uncomment `routes` in wrangler.toml, then:
npx wrangler deploy
```

## Reading feedback in the Cloudflare dashboard

1. dash.cloudflare.com → your account → **Storage & Databases → D1 SQL Database** → **griddion**.
2. Open the **Console** tab, type a query, press **Execute**. (The **Tables** tab browses rows.)

Useful queries:

```sql
-- newest first
SELECT created_at, drive, rating, device, message FROM feedback ORDER BY id DESC LIMIT 100;

-- average rating and count per drive
SELECT drive, count(*) AS n, round(avg(rating), 2) AS avg_rating
FROM feedback GROUP BY drive ORDER BY drive DESC;

-- rating split by device
SELECT device, rating, count(*) AS n FROM feedback GROUP BY device, rating ORDER BY device, rating;

-- only comments, last 7 days
SELECT created_at, drive, rating, message FROM feedback
WHERE message IS NOT NULL AND created_at >= datetime('now', '-7 days') ORDER BY id DESC;
```

The same queries work from a terminal:
`npx wrangler d1 execute griddion --remote --command "SELECT ..."`.

## Export to CSV

```sh
npm run export:feedback                                   # feedback-YYYY-MM-DD.csv, all rows
node scripts/export-feedback.mjs --since 2026-11-10 --out week.csv
node scripts/export-feedback.mjs --local                  # local dev database
```

UTF-8 with a BOM (opens cleanly in Excel / Sheets). Messages that start with `=`, `+`, `-` or `@`
get a leading `'` so a spreadsheet never runs them as formulas. The script runs one `SELECT`
and changes nothing.

## Development

```sh
npm test                        # unit tests (fake D1 + limiter)
npm run db:migrate:local        # create the local D1 (.wrangler/)
npm run dev                     # wrangler dev on http://localhost:8787
npm run check                   # typecheck + tests + `wrangler deploy --dry-run` (uploads nothing)
```
