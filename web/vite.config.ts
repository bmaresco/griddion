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
 * The +1 covers the gap between midnight ET and the nightly 00:05 ET rebuild. Future answer
 * banks never reach the deployed site. Before launch the build date counts as the launch date. GRIDDION_BUILD_DATE=YYYY-MM-DD overrides the date (testing).
 */
function publishLiveDrives(): Plugin {
  return {
    name: 'griddion-live-drives',
    apply: 'build',
    closeBundle() {
      const out = resolve(HERE, 'dist');
      const buildDate = process.env.GRIDDION_BUILD_DATE || todayET();
      const schedule = JSON.parse(readFileSync(resolve(PUBLIC, 'schedule.json'), 'utf8'));
      // Before launch, count from the launch date, so a pre-launch build ships Drives 1-2.
      const cutoff = addDays(buildDate < schedule.launch_date ? schedule.launch_date : buildDate, 1);
      const live = schedule.drives.filter((d: { date: string }) => d.date <= cutoff);
      for (const d of live) {
        mkdirSync(dirname(resolve(out, d.file)), { recursive: true });
        copyFileSync(resolve(PUBLIC, d.file), resolve(out, d.file));
      }
      writeFileSync(resolve(out, 'schedule.json'), JSON.stringify({ ...schedule, drives: live }, null, 1));
      for (const f of ['matching.json', 'game.json']) copyFileSync(resolve(PUBLIC, f), resolve(out, f));
      // Short cache on data so the nightly deploy is picked up promptly.
      writeFileSync(resolve(out, '_headers'), '/schedule.json\n  Cache-Control: no-cache\n/days/*\n  Cache-Control: no-cache\n/matching.json\n  Cache-Control: public, max-age=3600\n');
      console.log(`griddion: build date ${buildDate} (ET) -> shipping drives ${live.map((d: { drive: number }) => d.drive).join(', ') || 'none'}`);
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
