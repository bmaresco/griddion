import { defineConfig, type Plugin } from 'vite';
import { readFileSync, writeFileSync, mkdirSync, copyFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));

const PUBLIC = resolve(HERE, '../public');

/** YYYY-MM-DD in America/New_York (the drive rollover zone). */
function todayET(): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
}
function addDays(d: string, n: number): string {
  const t = new Date(d + 'T12:00:00Z');
  t.setUTCDate(t.getUTCDate() + n);
  return t.toISOString().slice(0, 10);
}

/**
 * Production builds ship only the drives that are live: date <= (build date in ET + 1 day).
 * The +1 means tomorrow's drive is already deployed when midnight ET arrives. Future answer
 * banks never reach the deployed site. The first drive after the cutoff is announced as
 * schedule.next = {drive, date} (no answer bank) so a gap day can count down to it.
 * GRIDDION_BUILD_DATE=YYYY-MM-DD overrides the build date (testing).
 */
function publishLiveDrives(): Plugin {
  return {
    name: 'griddion-live-drives',
    apply: 'build',
    closeBundle() {
      const out = resolve(HERE, 'dist');
      const buildDate = process.env.GRIDDION_BUILD_DATE || todayET();
      const schedule = JSON.parse(readFileSync(resolve(PUBLIC, 'schedule.json'), 'utf8'));
      type Entry = { drive: number; date: string; file: string };
      const cutoff = addDays(buildDate, 1);
      const live = (schedule.drives as Entry[]).filter((d) => d.date <= cutoff);
      const upcoming = (schedule.drives as Entry[]).filter((d) => d.date > cutoff).sort((a, b) => a.date.localeCompare(b.date))[0];
      for (const d of live) {
        mkdirSync(dirname(resolve(out, d.file)), { recursive: true });
        copyFileSync(resolve(PUBLIC, d.file), resolve(out, d.file));
      }
      const { next: _old, ...rest } = schedule;
      writeFileSync(resolve(out, 'schedule.json'), JSON.stringify({ ...rest, drives: live, ...(upcoming ? { next: { drive: upcoming.drive, date: upcoming.date } } : {}) }, null, 1));
      for (const f of ['matching.json', 'game.json']) copyFileSync(resolve(PUBLIC, f), resolve(out, f));
      // Short cache on data so the nightly deploy is picked up promptly.
      writeFileSync(resolve(out, '_headers'), '/schedule.json\n  Cache-Control: no-cache\n/days/*\n  Cache-Control: no-cache\n/matching.json\n  Cache-Control: public, max-age=3600\n');
      console.log(`griddion: build date ${buildDate} (ET) -> shipping drives ${live.map((d) => d.drive).join(', ') || 'none'}${upcoming ? `; next = Drive ${upcoming.drive} on ${upcoming.date}` : ''}`);
    },
  };
}

// Dev serves the pipeline's public/ as-is; production copies only live drives (above).
export default defineConfig(({ command }) => ({
  publicDir: command === 'serve' ? PUBLIC : false,
  build: { outDir: 'dist', emptyOutDir: true, target: 'es2020' },
  server: { port: 5173 },
  plugins: [publishLiveDrives()],
}));
