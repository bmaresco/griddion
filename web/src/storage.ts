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

/** Streak shown today: it's broken if the last completed drive is older than yesterday. */
export function displayStreak(today: number): number {
  return mem.stats.lastPlayed >= today - 1 ? mem.stats.streak : 0;
}

export function recordFinish(drive: number, won: boolean): void {
  const g = mem.game;
  if (!g || g.counted) return;
  const st = mem.stats;
  if (st.lastPlayed !== drive) {
    st.streak = st.lastPlayed === drive - 1 ? st.streak + 1 : 1;
    st.lastPlayed = drive;
  }
  if (won) st.wins++; else st.losses++;
  g.counted = true;
  save();
}
