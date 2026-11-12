import { describe, it, expect } from 'vitest';
import { streakAfter, streakShown, type Stats } from '../src/storage';

const st = (streak: number, lastPlayed: number): Stats => ({ streak, lastPlayed, wins: 0, losses: 0 });

describe('streaks count published drives, not calendar days', () => {
  it('extends when the previous published drive was played, even across days with no drive', () => {
    // Drive 2 on Nov 10, outage Nov 11–14, Drive 3 on the relaunch day: prev of 3 is 2.
    expect(streakAfter(st(2, 2), 3, 2)).toBe(3);
  });
  it('resets after a missed published drive', () => {
    expect(streakAfter(st(2, 1), 3, 2)).toBe(1);
  });
  it('first drive ever starts at 1; replaying the same drive does not double count', () => {
    expect(streakAfter(st(0, 0), 1, null)).toBe(1);
    expect(streakAfter(st(4, 3), 3, 2)).toBe(4);
  });
  it('shown streak survives a day with no drive', () => {
    // Published so far: 1, 2. Today has no drive. Last played 2.
    expect(streakShown(st(2, 2), [1, 2], null)).toBe(2);
  });
  it('shown streak survives until today is played, then breaks after a missed drive', () => {
    expect(streakShown(st(2, 2), [1, 2, 3], 3)).toBe(2); // today = 3, not yet played
    expect(streakShown(st(3, 3), [1, 2, 3], 3)).toBe(3); // played today
    expect(streakShown(st(2, 2), [1, 2, 3, 4], 4)).toBe(0); // missed 3
    expect(streakShown(st(2, 2), [1, 2, 3], null)).toBe(0); // no drive today, but missed 3
  });
  it('unknown last drive shows 0', () => {
    expect(streakShown(st(5, 0), [1, 2], 2)).toBe(0);
  });
});
