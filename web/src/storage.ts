// Local storage: in-progress game, streak, W–L. Every access is wrapped; the game works without it.
import type { PlayRecord } from './game';

const KEY = 'griddion:v1';

export interface SavedGame {
  drive: number;
  plays: PlayRecord[];
  phase: 'intro' | 'play' | 'result' | 'done';
  deadline: number | null; // epoch ms when the current play's timer expires
  counted: boolean; // W/L + streak already recorded
}

export interface Stats {
  streak: number;
  lastPlayed: number; // drive # of the last completed game
  wins: number;
  losses: number;
}

interface Store { stats: Stats; game: SavedGame | null }

let mem: Store = { stats: { streak: 0, lastPlayed: 0, wins: 0, losses: 0 }, game: null };

export function load(): Store {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const s = JSON.parse(raw) as Partial<Store>;
      mem = { stats: { ...mem.stats, ...(s.stats ?? {}) }, game: s.game ?? null };
    }
  } catch { /* storage blocked or corrupt: keep in-memory state */ }
  return mem;
}

export function save(): void {
  try { localStorage.setItem(KEY, JSON.stringify(mem)); } catch { /* ignore */ }
}

export function store(): Store { return mem; }

// Streaks count consecutive *published* drives played, not calendar days: a day with no drive in
// schedule.json never breaks a streak. `published` = drive numbers dated on or before today, in date order.

/** Streak after finishing `drive`; `prev` is the published drive just before it (null if it's the first). */
export function streakAfter(st: Stats, drive: number, prev: number | null): number {
  if (st.lastPlayed === drive) return st.streak;
  return prev !== null && st.lastPlayed === prev ? st.streak + 1 : 1;
}

/** Streak to show now. Alive if the last drive played is today's drive, or the latest published drive
 *  before today's (today's not played yet), or — on a day with no drive — the latest published drive. */
export function streakShown(st: Stats, published: number[], todayDrive: number | null): number {
  const i = st.lastPlayed ? published.indexOf(st.lastPlayed) : -1;
  if (i < 0) return 0;
  const behind = published.length - 1 - i; // published drives since the last one played
  return behind <= (todayDrive !== null ? 1 : 0) ? st.streak : 0;
}

export function displayStreak(published: number[], todayDrive: number | null): number {
  return streakShown(mem.stats, published, todayDrive);
}

export function recordFinish(drive: number, won: boolean, prev: number | null): void {
  const g = mem.game;
  if (!g || g.counted) return;
  const st = mem.stats;
  st.streak = streakAfter(st, drive, prev);
  st.lastPlayed = drive;
  if (won) st.wins++; else st.losses++;
  g.counted = true;
  save();
}
