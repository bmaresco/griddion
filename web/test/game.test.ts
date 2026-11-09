import { describe, it, expect } from 'vitest';
import { playCell, resultLine, MAX_POINTS, type PlayRecord, type Tier } from '../src/game';

const rec = (tier: Tier): PlayRecord => ({ typed: 'x', playerId: 'x', name: 'x', tier, reason: tier === 'Incomplete' ? 'timeout' : 'valid' });

describe('drive cells and result line', () => {
  // 20+20+20 = 60 yds, then 17 -> 77 capped: TD on P4
  const plays = (['YKB Kid', 'YKB Kid', 'YKB Kid', 'Sleeper Pick', 'Hidden Gem', 'Incomplete', 'Starter'] as Tier[]).map(rec);
  it('yards before TD, TD on the scoring play, points after', () => {
    expect(playCell(plays, 0)).toEqual({ kind: 'yds', value: 20 });
    expect(playCell(plays, 3)).toEqual({ kind: 'td' });
    expect(playCell(plays, 4)).toEqual({ kind: 'pts', value: 60 });
    expect(playCell(plays, 5)).toEqual({ kind: 'pts', value: 0 });
  });
  it('share line shows points out of 700', () => {
    expect(MAX_POINTS).toBe(700);
    expect(resultLine(plays)).toBe('TOUCHDOWN on P4 · W 24–21 · 455/700 pts');
    const stalled = (['Starter', 'Starter', 'Incomplete', 'Starter', 'Starter', 'Starter', 'Starter'] as Tier[]).map(rec);
    expect(resultLine(stalled)).toBe('STALLED at OWN 37 · L 17–21 · 60/700 pts');
  });
});
