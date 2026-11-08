// Eastern-time day math (rollover at 00:00 America/New_York).

const TZ = 'America/New_York';

let offsetMs = 0;
/** Dev only: pretend "now" is a different instant (?now=2026-11-09T08:00 in ET-agnostic ISO, or ?today=YYYY-MM-DD). */
export function setMockNow(target: Date): void {
  offsetMs = target.getTime() - Date.now();
}
export const now = (): number => Date.now() + offsetMs;

function parts(t: number): Record<string, number> {
  const f = new Intl.DateTimeFormat('en-US', {
    timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  });
  const out: Record<string, number> = {};
  for (const p of f.formatToParts(new Date(t))) if (p.type !== 'literal') out[p.type] = Number(p.value);
  return out;
}

/** YYYY-MM-DD in Eastern time. */
export function todayET(t = now()): string {
  const p = parts(t);
  return `${p.year}-${String(p.month).padStart(2, '0')}-${String(p.day).padStart(2, '0')}`;
}

/** Whole days from a to b (both YYYY-MM-DD). */
export function daysBetween(a: string, b: string): number {
  return Math.round((Date.UTC(+b.slice(0, 4), +b.slice(5, 7) - 1, +b.slice(8, 10)) - Date.UTC(+a.slice(0, 4), +a.slice(5, 7) - 1, +a.slice(8, 10))) / 86400000);
}

export function driveNumber(launch: string, t = now()): number {
  return daysBetween(launch, todayET(t)) + 1;
}

/** Milliseconds until the next Eastern midnight. Steps forward to find the exact instant, so DST days work. */
export function msUntilMidnightET(t = now()): number {
  const p = parts(t);
  const approx = ((23 - p.hour) * 3600 + (59 - p.minute) * 60 + (60 - p.second)) * 1000 - (t % 1000);
  // correct for a DST shift tonight: check the date actually changes at t + approx
  const today = todayET(t);
  let ms = approx;
  if (todayET(t + ms) === today) ms += 3600000;
  else if (todayET(t + ms - 3600000) !== today) ms -= 3600000;
  return Math.max(0, ms);
}
