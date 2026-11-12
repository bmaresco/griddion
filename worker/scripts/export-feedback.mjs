#!/usr/bin/env node
// Export the D1 feedback table to CSV (spec §9).
//
//   node scripts/export-feedback.mjs                      -> feedback-YYYY-MM-DD.csv from the live (remote) D1
//   node scripts/export-feedback.mjs --local              -> from the local dev D1 (.wrangler/)
//   node scripts/export-feedback.mjs --since 2026-11-10 --out f.csv
//
// Needs `npx wrangler login` once (remote). Read-only: runs a single SELECT.
import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";

const args = process.argv.slice(2);
const opt = (name) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : undefined; };
const local = args.includes("--local");
const since = opt("--since");
if (since && !/^\d{4}-\d{2}-\d{2}$/.test(since)) { console.error("--since must be YYYY-MM-DD"); process.exit(2); }
const out = opt("--out") ?? `feedback-${new Date().toISOString().slice(0, 10)}.csv`;

const cols = ["id", "created_at", "drive", "rating", "device", "message"];
// coalesce: wrangler's JSON output shows SQL NULL as the string "null"; an empty cell is unambiguous
const sql = `SELECT id, created_at, drive, rating, device, coalesce(message, '') AS message FROM feedback`
  + (since ? ` WHERE created_at >= '${since}'` : "") + " ORDER BY id";

const raw = execFileSync("npx", ["wrangler", "d1", "execute", "griddion", local ? "--local" : "--remote", "--json", "--command", sql],
  { encoding: "utf8", stdio: ["ignore", "pipe", "inherit"], env: { ...process.env, WRANGLER_SEND_METRICS: "false" } });
const rows = JSON.parse(raw)[0]?.results ?? [];

const cell = (v) => {
  const s = String(v ?? "");
  // quote when needed; neutralize spreadsheet formulas in free text (=, +, -, @ at the start)
  const safe = /^[=+\-@]/.test(s) ? "'" + s : s;
  return /[",\n\r]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
};
const csv = [cols.join(","), ...rows.map((r) => cols.map((c) => cell(r[c])).join(","))].join("\r\n") + "\r\n";
writeFileSync(out, "﻿" + csv);   // BOM so Excel reads UTF-8
console.log(`${rows.length} rows -> ${out}`);
