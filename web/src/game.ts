// Drive rules (CLAUDE.md §9, UI_HANDOFF §3). Pure functions, no DOM.

export type Tier = 'Starter' | 'Botched Trick Play' | 'Backup' | 'Hidden Gem' | 'Sleeper Pick' | 'YKB Kid' | 'Incomplete';

export interface TierInfo {
  key: Tier;
  short: string; // chip / jumbotron label
  play: string; // play name
  points: number;
  yards: number;
  color: string; // tier color
  led: string; // brighter LED version for the jumbotron
  ink: string; // text color on the tier color
  square: string;
  anim: 'run' | 'short' | 'deep' | 'miss';
}

export const TIERS: Record<Tier, TierInfo> = {
  Starter: { key: 'Starter', short: 'STARTER', play: 'Run up the middle', points: 10, yards: 2, color: '#7a8191', led: '#c3c8d4', ink: '#f3ead7', square: '⬜', anim: 'run' },
  'Botched Trick Play': { key: 'Botched Trick Play', short: 'TRICK PLAY', play: 'Reverse, stuffed', points: 15, yards: 3, color: '#d4661c', led: '#ff9a52', ink: '#1d1a14', square: '🟧', anim: 'run' },
  Backup: { key: 'Backup', short: 'BACKUP', play: 'Quick slant', points: 30, yards: 6, color: '#1f6fd1', led: '#6fb4ff', ink: '#f3ead7', square: '🟦', anim: 'short' },
  'Hidden Gem': { key: 'Hidden Gem', short: 'HIDDEN GEM', play: 'Deep out', points: 60, yards: 12, color: '#198a4a', led: '#5fe08f', ink: '#f3ead7', square: '🟩', anim: 'deep' },
  'Sleeper Pick': { key: 'Sleeper Pick', short: 'SLEEPER PICK', play: 'Deep bomb', points: 85, yards: 17, color: '#7b3fc4', led: '#c89bff', ink: '#f3ead7', square: '🟪', anim: 'deep' },
  'YKB Kid': { key: 'YKB Kid', short: 'YKB KID', play: 'Hail Mary', points: 100, yards: 20, color: '#e0a800', led: '#ffd23f', ink: '#1d1a14', square: '🟨', anim: 'deep' },
  Incomplete: { key: 'Incomplete', short: 'INCOMPLETE', play: 'Incomplete', points: 0, yards: 0, color: '#4a4a55', led: '#55555f', ink: '#f3ead7', square: '⬛', anim: 'miss' },
};

export const LEGEND_ORDER: Tier[] = ['Starter', 'Backup', 'Hidden Gem', 'Sleeper Pick', 'YKB Kid', 'Botched Trick Play'];

export const RULES = {
  plays: 7,
  secondsPerPlay: 25,
  startYardline: 25,
  touchdownYards: 75,
  clockStart: 175,
  trail: [17, 21] as const,
  win: [24, 21] as const,
};

export interface PlayRecord {
  typed: string;
  playerId: string | null; // matched valid answer, or the real-but-invalid player
  name: string | null; // display name of the matched answer
  tier: Tier;
  reason: 'valid' | 'timeout' | 'empty' | 'not_valid_answer' | 'no_match';
}

export interface DriveState {
  yardline: number; // 25..100
  yards: number; // capped at 75
  points: number;
  tdPlay: number | null; // 1-based play that scored, or null
  clock: number; // seconds left
}

/** State after the given plays. */
export function driveState(plays: PlayRecord[]): DriveState {
  let yards = 0, points = 0, tdPlay: number | null = null;
  plays.forEach((p, i) => {
    const t = TIERS[p.tier];
    points += t.points;
    if (tdPlay === null) {
      yards += t.yards;
      if (yards >= RULES.touchdownYards) { yards = RULES.touchdownYards; tdPlay = i + 1; }
    }
  });
  return { yardline: RULES.startYardline + yards, yards, points, tdPlay, clock: RULES.clockStart - RULES.secondsPerPlay * plays.length };
}

/** Yards actually gained on play i (0 after the touchdown). */
export function yardsOnPlay(plays: PlayRecord[], i: number): number {
  return driveState(plays.slice(0, i + 1)).yards - driveState(plays.slice(0, i)).yards;
}

export const MAX_POINTS = RULES.plays * 100;

/** What the wristband / drive chart shows for play i: yards before the TD, "TD" on the scoring play, points after it. */
export type PlayCell = { kind: 'yds'; value: number } | { kind: 'td' } | { kind: 'pts'; value: number };
export function playCell(plays: PlayRecord[], i: number): PlayCell {
  const td = driveState(plays.slice(0, i + 1)).tdPlay;
  if (td === null) return { kind: 'yds', value: yardsOnPlay(plays, i) };
  if (td === i + 1) return { kind: 'td' };
  return { kind: 'pts', value: TIERS[plays[i].tier].points };
}

export function ballSpot(yardline: number): string {
  if (yardline >= 100) return 'END ZONE';
  if (yardline < 50) return 'OWN ' + yardline;
  if (yardline === 50) return 'MIDFIELD';
  return 'OPP ' + (100 - yardline);
}

export function clockText(sec: number): string {
  const s = Math.max(0, sec);
  return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
}

export function resultLine(plays: PlayRecord[]): string {
  const d = driveState(plays);
  if (d.tdPlay !== null) {
    const head = d.tdPlay === RULES.plays ? 'TOUCHDOWN' : 'TOUCHDOWN on P' + d.tdPlay;
    return `${head} · W ${RULES.win[0]}–${RULES.win[1]} · ${d.points}/${MAX_POINTS} pts`;
  }
  return `STALLED at ${ballSpot(d.yardline)} · L ${RULES.trail[0]}–${RULES.trail[1]} · ${d.points}/${MAX_POINTS} pts`;
}

export function shareText(drive: number, plays: PlayRecord[]): string {
  return [`Griddion Drive #${drive} 🏈`, resultLine(plays), plays.map((p) => TIERS[p.tier].square).join(''), 'griddion.io'].join('\n');
}
