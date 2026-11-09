import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { buildConfig, buildOthers, Matcher, normName, editDistance } from '../src/matching';

const pub = new URL('../../public/', import.meta.url);
const m = JSON.parse(readFileSync(new URL('matching.json', pub), 'utf8'));
const cfg = buildConfig(m.first_name_groups, m.edit_budget);
const others = buildOthers(cfg, m.all_player_names);
const cases = JSON.parse(readFileSync(new URL('cases.json', import.meta.url), 'utf8'));

describe('normName', () => {
  it('matches names.norm_name', () => {
    expect(normName('Y. A. Tittle')).toBe('ya tittle');
    expect(normName('Odell Beckham Jr.')).toBe('odell beckham');
    expect(normName('Ja\'Marr Chase')).toBe('jamarr chase');
    expect(normName('Jean-Pierre  Éclair III')).toBe('jean pierre eclair');
  });
  it('edit distance with transposition', () => {
    expect(editDistance('brady', 'bardy')).toBe(1);
    expect(editDistance('manning', 'mannign')).toBe(1);
  });
});

describe('parity with matching.py', () => {
  const matchers = new Map<string, Matcher>();
  const get = (drive: number, slot: number) => {
    const k = drive + ':' + slot;
    if (!matchers.has(k)) {
      const day = JSON.parse(readFileSync(new URL(`days/${drive}.json`, pub), 'utf8'));
      matchers.set(k, new Matcher(cfg, day.prompts[slot - 1].answers, others));
    }
    return matchers.get(k)!;
  };
  it('agrees on every case (except the documented in-bank alias improvement)', { timeout: 60000 }, () => {
    const diffs: string[] = [];
    let improved = 0;
    for (const c of cases) {
      const r = get(c.drive, c.slot).match(c.typed);
      const same = r.status === c.status && (r.playerId ?? null) === (c.id ?? null) && r.method === c.method &&
        JSON.stringify(r.candidates) === JSON.stringify([...c.candidates].sort());
      if (same) continue;
      if (c.method === 'not_valid_answer' && r.method === 'exact') { improved++; continue; }
      diffs.push(`${c.drive}/${c.slot} "${c.typed}": py=${c.status}/${c.method}/${c.id} ts=${r.status}/${r.method}/${r.playerId}`);
    }
    if (improved) console.log('in-bank alias improvements:', improved);
    expect(diffs.slice(0, 20)).toEqual([]);
  });
});
