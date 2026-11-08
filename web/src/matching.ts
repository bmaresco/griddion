// Port of src/football_trivia/matching.py + names.norm_name (CLAUDE.md §9 answer matching).
// Keep the rule order identical to the Python reference.

const SUFFIXES = new Set(['jr', 'sr', 'ii', 'iii', 'iv', 'v']);

export function normName(name: string | null | undefined): string {
  if (!name) return '';
  // NFKD + drop non-ASCII (accents), like unicodedata.normalize(...).encode('ascii','ignore')
  let s = name.normalize('NFKD').replace(/[^\x00-\x7f]/g, '');
  s = s.toLowerCase().replace(/-/g, ' ').replace(/[^a-z0-9 ]/g, '');
  const parts = s.split(/\s+/).filter((p) => p && !SUFFIXES.has(p));
  const out: string[] = [];
  let prevInitial = false;
  for (const p of parts) {
    const initial = p.length === 1;
    if (initial && prevInitial) out[out.length - 1] += p;
    else out.push(p);
    prevInitial = initial;
  }
  return out.join(' ');
}

export interface EditBudget { max_chars: number | null; edits: number }

export interface MatchConfig {
  variants: Map<string, Set<string>>;
  budget: EditBudget[];
}

export function buildConfig(groups: string[][], budget: EditBudget[]): MatchConfig {
  const variants = new Map<string, Set<string>>();
  for (const g of groups) {
    for (const n of g) {
      let s = variants.get(n);
      if (!s) variants.set(n, (s = new Set()));
      for (const m of g) s.add(m);
    }
  }
  return { variants, budget };
}

export function firstNameVariants(cfg: MatchConfig, fullNorm: string): string[] {
  const parts = fullNorm.split(' ');
  if (parts.length < 2) return [fullNorm];
  const rest = parts.slice(1).join(' ');
  const vs = new Set(cfg.variants.get(parts[0]) ?? []);
  vs.add(parts[0]);
  return [...vs].map((v) => v + ' ' + rest);
}

/** Damerau-Levenshtein (optimal string alignment), stopping early past `cap`. */
export function editDistance(a: string, b: string, cap = 4): number {
  if (Math.abs(a.length - b.length) > cap) return cap + 1;
  let prev2: number[] | null = null;
  let prev: number[] = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const cur = new Array<number>(b.length + 1);
    cur[0] = i;
    let rowMin = i;
    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] !== b[j - 1] ? 1 : 0;
      let v = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost);
      if (prev2 && i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) v = Math.min(v, prev2[j - 2] + 1);
      cur[j] = v;
      if (v < rowMin) rowMin = v;
    }
    if (rowMin > cap) return cap + 1;
    prev2 = prev;
    prev = cur;
  }
  return prev[b.length];
}

export function allowedEdits(cfg: MatchConfig, nChars: number): number {
  for (const b of cfg.budget) if (b.max_chars === null || nChars <= b.max_chars) return b.edits;
  return 0;
}

export type MatchStatus = 'valid' | 'invalid' | 'ambiguous';
export interface Match {
  status: MatchStatus;
  playerId: string | null;
  method: string; // exact | last_name | fuzzy | not_valid_answer | no_match | empty
  candidates: string[];
}

export interface BankAnswer { id: string; names: string[]; last_names: string[] }

/** Every real player's full names, normalized with first-name variants, indexed by last token. */
export interface Others {
  full: Map<string, Set<string>>;
  byLast: Map<string, Map<string, Set<string>>>;
}

export function buildOthers(cfg: MatchConfig, allPlayerNames: Record<string, string[]>): Others {
  const full = new Map<string, Set<string>>();
  for (const [name, ids] of Object.entries(allPlayerNames)) {
    const n = normName(name);
    if (!n || !n.includes(' ')) continue;
    for (const v of firstNameVariants(cfg, n)) {
      let s = full.get(v);
      if (!s) full.set(v, (s = new Set()));
      for (const id of ids) s.add(id);
    }
  }
  const byLast = new Map<string, Map<string, Set<string>>>();
  for (const [name, ids] of full) {
    const last = name.slice(name.lastIndexOf(' ') + 1);
    let m = byLast.get(last);
    if (!m) byLast.set(last, (m = new Map()));
    m.set(name, ids);
  }
  return { full, byLast };
}

const add = (m: Map<string, Set<string>>, k: string, v: string) => {
  let s = m.get(k);
  if (!s) m.set(k, (s = new Set()));
  s.add(v);
};

export class Matcher {
  full = new Map<string, Set<string>>();
  last = new Map<string, Set<string>>();
  private bankIds = new Set<string>();

  constructor(private cfg: MatchConfig, bank: BankAnswer[], private others: Others | null) {
    for (const a of bank) {
      this.bankIds.add(a.id);
      // Like the Python reference with bare strings: one word -> last-name index, else a full name
      // (so a multi-word last name such as "St. Brown" is matched as a full name).
      for (const nm of [...a.names, ...a.last_names]) {
        const n = normName(nm);
        if (!n) continue;
        if (!n.includes(' ')) add(this.last, n, a.id);
        else for (const v of firstNameVariants(cfg, n)) add(this.full, v, a.id);
      }
    }
  }

  private resolve(ids: Set<string>, method: string): Match {
    const list = [...ids].sort();
    if (list.length === 1) return { status: 'valid', playerId: list[0], method, candidates: [] };
    return { status: 'ambiguous', playerId: null, method, candidates: list };
  }

  match(typed: string): Match {
    const q = normName(typed);
    const invalid = (method: string, pid: string | null = null): Match => ({ status: 'invalid', playerId: pid, method, candidates: [] });
    if (!q) return invalid('empty');
    const exact = this.full.get(q);
    if (exact) return this.resolve(exact, 'exact'); // 1
    const ln = this.last.get(q);
    if (ln) return this.resolve(ln, 'last_name'); // 2
    if (this.others) {
      // 3: an exact full name of a real player. If that name also belongs to a valid answer
      // (an alias the bank doesn't list), take the valid one; otherwise it's not a valid answer.
      const outside = new Set<string>();
      for (const v of firstNameVariants(this.cfg, q)) for (const id of this.others.full.get(v) ?? []) outside.add(id);
      if (outside.size) {
        const inBank = new Set([...outside].filter((id) => this.bankIds.has(id)));
        if (inBank.size) return this.resolve(inBank, 'exact');
        return invalid('not_valid_answer', [...outside].sort()[0]);
      }
    }
    const budget = allowedEdits(this.cfg, q.replace(/ /g, '').length); // 4-5
    if (budget === 0) return invalid('no_match');
    const pools: Map<string, Set<string>>[] = q.includes(' ') ? [this.full] : [this.last, this.full];
    let best = budget + 1;
    let bestIds = new Set<string>();
    for (const pool of pools) {
      for (const [name, ids] of pool) {
        const d = editDistance(q, name, budget);
        if (d < best) { best = d; bestIds = new Set(ids); }
        else if (d === best) for (const id of ids) bestIds.add(id);
      }
    }
    if (best > budget) return invalid('no_match');
    if (this.others && q.includes(' ')) {
      const qLast = q.slice(q.lastIndexOf(' ') + 1);
      for (const [last, names] of this.others.byLast) {
        if (Math.abs(last.length - qLast.length) > best || editDistance(qLast, last, best) > best) continue;
        for (const [name, ids] of names) {
          if (editDistance(q, name, best) <= best && ![...ids].some((id) => bestIds.has(id))) {
            return invalid('not_valid_answer', [...ids].sort()[0]);
          }
        }
      }
    }
    return this.resolve(bestIds, 'fuzzy');
  }
}
