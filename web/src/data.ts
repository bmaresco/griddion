// Published files (CLAUDE.md §6): schedule.json, days/<drive#>.json, matching.json.
import { buildConfig, buildOthers, Matcher, type MatchConfig, type Others } from './matching';
import type { Tier } from './game';

export interface Answer {
  id: string; name: string; tier: Exclude<Tier, 'Incomplete'>; context: string;
  names: string[]; last_names: string[]; r: number;
}
export interface Prompt {
  slot: number; id: string; text: string; subtitle: string; type: string;
  answer_count: number; ykb_kid: string; answers: Answer[];
}
export interface Day { format: number; drive: number; date: string; prompts: Prompt[] }
export interface Schedule { format: number; launch_date: string; drives: { drive: number; date: string; file: string }[] }

async function getJSON<T>(path: string): Promise<T> {
  const r = await fetch(path, { cache: 'no-cache' });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json() as Promise<T>;
}

export const loadSchedule = () => getJSON<Schedule>('/schedule.json');
export const loadDay = (file: string) => getJSON<Day>('/' + file.replace(/^\//, ''));

export interface MatchData { cfg: MatchConfig; others: Others | null; nameById: Map<string, string> }

let matchData: Promise<MatchData> | null = null;
/** matching.json is ~650 KB gzipped: start loading early, and fall back to a bank-only matcher if it fails. */
export function loadMatchData(): Promise<MatchData> {
  matchData ??= getJSON<{ first_name_groups: string[][]; edit_budget: { max_chars: number | null; edits: number }[]; all_player_names: Record<string, string[]> }>('/matching.json')
    .then((m) => {
      const cfg = buildConfig(m.first_name_groups, m.edit_budget);
      const nameById = new Map<string, string>();
      for (const [name, ids] of Object.entries(m.all_player_names)) for (const id of ids) if (!nameById.has(id)) nameById.set(id, name);
      return { cfg, others: buildOthers(cfg, m.all_player_names), nameById };
    })
    .catch((e) => {
      console.warn('matching.json unavailable; matching against answer banks only', e);
      matchData = null;
      return {
        cfg: buildConfig([], [{ max_chars: 3, edits: 0 }, { max_chars: 6, edits: 1 }, { max_chars: 12, edits: 2 }, { max_chars: null, edits: 3 }]),
        others: null, nameById: new Map(),
      };
    });
  return matchData;
}

const matchers = new WeakMap<Prompt, Matcher>();
export async function matcherFor(p: Prompt): Promise<Matcher> {
  let m = matchers.get(p);
  if (!m) {
    const d = await loadMatchData();
    m = new Matcher(d.cfg, p.answers, d.others);
    if (d.others) matchers.set(p, m);
  }
  return m;
}
