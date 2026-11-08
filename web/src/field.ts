// Pixel stadium + field, ported from design/*.dc.html (box-shadow sprites, 2px pixels, 3px per yard).
import type { TierInfo } from './game';

type Pal = Record<string, string>;

const HOME: Pal = { T: '#2f5bd3', J: '#2f5bd3', W: '#f4f4ee', P: '#e9e3cf', K: '#141414', G: '#c9ced6' };
const AWAY: Pal = { T: '#c8352f', J: '#c8352f', W: '#f4f4ee', P: '#f4f4ee', K: '#141414', G: '#c9ced6' };
const PR = ['.TTT.', 'TTTGG', '.TTT.', 'JJJJJ', 'JJWJJ', '.JJJ.', '.PPP.', '.P.P.', '.K.K.'];
const PL = ['.TTT.', 'GGTTT', '.TTT.', 'JJJJJ', 'JJWJJ', '.JJJ.', '.PPP.', '.P.P.', '.K.K.'];
const CHEER_R = ['T.TTT.T', 'J.TGG.J', 'J.TTT.J', 'JJJJJJJ', '..JWJ..', '..JJJ..', '..PPP..', '..P.P..', '..K.K..'];
const CHEER_L = ['T.TTT.T', 'J.GGT.J', 'J.TTT.J', 'JJJJJJJ', '..JWJ..', '..JJJ..', '..PPP..', '..P.P..', '..K.K..'];
const SLUMP = ['.....', '.TTT.', 'TTTGG', '.TTT.', 'JJJJJ', 'JJWJJ', '.PPP.', '.P.P.', '.K.K.'];
const COACH = ['.CCC.', 'CCCCC', '.SSS.', 'QQQQQ', 'QQQQQ', '.QQQ.', '.BBB.', '.B.B.', '.K.K.'];
const REF = ['.WWW.', '.SSS.', '.SSS.', 'WKWKW', 'WKWKW', '.WKW.', '.KKK.', '.K.K.', '.K.K.'];
const REF_TD = ['S.....S', 'W.WWW.W', 'W.SSS.W', 'WWKWKWW', '.WKWKW.', '..WKW..', '..KKK..', '..K.K..', '..K.K..'];
const CREW = ['.OOO.', '.SSS.', '.SSS.', 'OOOOO', 'OOOOO', '.OOO.', '.KKK.', '.K.K.', '.K.K.'];
const BALL = ['.BBBB.', 'BWWWWB', '.BBBB.'];
const BALL_PAL = { B: '#8a4f22', W: '#f4f4ee' };
const SKINS = ['#f1c9a5', '#d9a27a', '#a8714a', '#6b4429'];
const coachPal = (i: number, q: string): Pal => ({ C: q, S: SKINS[i % 4], Q: q, B: '#c8b48a', K: '#141414' });
const refPal = (i: number): Pal => ({ W: '#f4f4ee', K: '#141414', S: SKINS[i % 4] });

const F = 40; // field top inside the 200px box (sidelines above and below)
const X = (yd: number) => 30 + 3 * yd;

const shadowCache = new Map<string, string>();
function px(map: string[], pal: Pal, x: number, y: number, extra = ''): string {
  const p = 2;
  const key = map.join('|') + JSON.stringify(pal);
  let sh = shadowCache.get(key);
  if (!sh) {
    const parts: string[] = [];
    for (let r = 0; r < map.length; r++) for (let c = 0; c < map[r].length; c++) {
      const k = map[r][c];
      if (k !== '.' && pal[k]) parts.push(`${(c + 1) * p}px ${(r + 1) * p}px 0 0 ${pal[k]}`);
    }
    sh = parts.join(',');
    shadowCache.set(key, sh);
  }
  return `<div class="px" style="left:${x - p}px;top:${y - p}px;box-shadow:${sh};${extra}"></div>`;
}
function box(x: number, y: number, w: number, h: number, bg: string, extra = ''): string {
  return `<div class="px" style="left:${x}px;top:${y}px;width:${w}px;height:${h}px;background:${bg};${extra}"></div>`;
}

const idle = (k: number, dur = 1.2) => `animation:idle ${dur}s steps(1,end) infinite;animation-delay:-${((k % 5) * 0.23).toFixed(2)}s`;
const jump = (k: number) => `animation:jump 0.6s steps(1,end) infinite;animation-delay:-${((k % 4) * 0.15).toFixed(2)}s`;
const still = (k: number) => `animation:idle 2.4s steps(1,end) infinite;animation-delay:-${((k % 5) * 0.4).toFixed(2)}s`;
/** One-shot play animation that holds its last frame. Distances come from CSS variables. */
const play = (name: string, steps: number, v: Record<string, number> = {}) =>
  `animation:${name} 2.4s steps(${steps},end) 1 forwards;` + Object.entries(v).map(([k, n]) => `--${k}:${Math.round(n)}px`).join(';');

// ---------------------------------------------------------------- stadium

function crowd(y0: number, y1: number, near: boolean, width: number): string {
  const pal = near
    ? ['#2f5bd3', '#f4f4ee', '#2f5bd3', '#d9a27a', '#1d3b8f', '#c8352f', '#2f5bd3', '#6b4429', '#f1c9a5', '#ffd23f']
    : ['#23317a', '#77779a', '#23317a', '#7a5a45', '#1a2558', '#7a2420', '#23317a', '#3e2a1c'];
  let out = '';
  let r = 0;
  for (let y = y0; y <= y1; y += 6, r++) {
    const x0 = 1 + (r % 2) * 2;
    let first: string | null = null;
    const sh: string[] = [];
    for (let x = x0, c = 0; x < width - 2; x += 5, c++) {
      const col = pal[(r * 31 + c * 17 + ((c * c) % 7)) % pal.length];
      if (first === null) { first = col; continue; }
      sh.push(`${x - x0}px 0 0 0 ${col}`);
    }
    out += `<div class="px" style="left:${x0}px;top:${y}px;width:3px;height:4px;background:${first};box-shadow:${sh.join(',')}"></div>`;
  }
  return out;
}

/** The night stadium behind the jumbotron (390×266 on mobile). */
export function stadium(width = 390, height = 266): string {
  let d = '';
  const stars = Math.round(16 * width / 390);
  for (let s = 0; s < stars; s++) d += box(((s * 97 + 23) % (width - 10)) + 5, 4 + ((s * 41) % 88), 2, 2, '#8f8ac2');
  d += box(0, 96, width, height - 96, '#211a45');
  d += crowd(100, 166, false, width) + crowd(172, height - 4, true, width);
  const flashes = Math.round(14 * width / 390);
  for (let i = 0; i < flashes; i++) {
    d += box(((i * 67 + 11) % (width - 10)) + 4, 104 + ((i * 29) % (height - 116)), 3, 3, '#ffffff', `opacity:0;animation:flash 3.2s steps(1,end) infinite;animation-delay:-${(i * 0.37).toFixed(2)}s`);
  }
  for (const hx of [6, width - 30]) {
    d += box(hx + 10, 30, 4, 120, '#3a3550') + box(hx, 14, 24, 18, '#4a4466');
    for (let a = 0; a < 3; a++) for (let b = 0; b < 2; b++) d += box(hx + 3 + a * 7, 17 + b * 7, 5, 5, '#fff6c8');
  }
  return `<div class="stadium" aria-hidden="true">${d}</div>`;
}

// ---------------------------------------------------------------- field

export type FieldMode =
  | { kind: 'huddle'; los: number }
  | { kind: 'formation'; los: number; afterTD?: boolean }
  | { kind: 'play'; los: number; gain: number; tier: TierInfo; afterTD?: boolean }
  | { kind: 'td' }
  | { kind: 'stalled'; los: number };

interface Sprite { y: number; html: string }

function turf(): string {
  let s = box(0, 0, 360, F, '#2c6e33') + box(0, F + 120, 360, 40, '#2c6e33');
  for (let i = 0; i < 12; i++) s += box(30 * i, F, 30, 120, i === 0 ? '#22408f' : i === 11 ? '#8e2330' : i % 2 ? '#3f9a45' : '#378a3d');
  s += box(0, F - 2, 360, 2, '#f4f4ee') + box(0, F + 120, 360, 2, '#f4f4ee');
  for (let a = 0; a <= 10; a++) s += box(X(10 * a) - 1, F, 2, 120, '#f4f4ee');
  for (let b = 0; b < 10; b++) s += box(X(10 * b + 5), F, 1, 120, 'rgba(244,244,238,0.45)');
  for (let h = 1; h < 100; h++) if (h % 5) s += box(X(h), F + 44, 1, 4, 'rgba(244,244,238,0.6)') + box(X(h), F + 72, 1, 4, 'rgba(244,244,238,0.6)');
  for (const yd of [10, 20, 30, 40, 50, 60, 70, 80, 90]) {
    s += `<div class="ydnum" style="left:${X(yd) - 10}px;top:${F + 104}px">${yd <= 50 ? yd : 100 - yd}</div>`;
  }
  return s;
}

type SideMood = 'normal' | 'td' | 'stalled';

function sidelines(mood: SideMood, chainsAt: [number, number] | null): string {
  const B0 = F + 122;
  const sp: Sprite[] = [];
  const top: { x: number; y: number; t: 'p' | 'c'; k: number }[] = [];
  for (let k = 0; k < 24; k++) top.push({ x: 86 + k * 9 + ((k * 37) % 7) - 3, y: 3 + ((k * 53) % 14), t: 'p', k });
  top.push({ x: 40, y: 10, t: 'p', k: 3 }, { x: 322, y: 7, t: 'p', k: 1 }, { x: 166, y: 20, t: 'c', k: 0 }, { x: 196, y: 19, t: 'c', k: 2 });
  for (const m of top) {
    const anim = mood === 'td' ? jump(m.k) : mood === 'stalled' ? still(m.k) : idle(m.k, m.t === 'c' ? 1.6 : 1.2);
    const map = m.t === 'c' ? COACH : mood === 'stalled' ? SLUMP : PR;
    sp.push({ y: m.y, html: px(map, m.t === 'c' ? coachPal(m.k, '#1d3b8f') : HOME, m.x, m.y, anim) });
  }
  const bot: { x: number; y: number; t: 'p' | 'c'; k: number }[] = [];
  for (let j = 0; j < 22; j++) {
    const bx = 78 + j * 9 + ((j * 29) % 7) - 3, by = B0 + 3 + ((j * 41) % 15);
    const blocked = chainsAt && by < B0 + 12 && (Math.abs(bx - chainsAt[0]) < 12 || Math.abs(bx - chainsAt[1]) < 12);
    if (!blocked) bot.push({ x: bx, y: by, t: 'p', k: j });
  }
  bot.push({ x: 300, y: B0 + 6, t: 'p', k: 2 }, { x: 150, y: B0 + 20, t: 'c', k: 1 }, { x: 178, y: B0 + 20, t: 'c', k: 3 });
  for (const m of bot) {
    if (m.t === 'c') sp.push({ y: m.y, html: px(COACH, coachPal(m.k, '#7a1b17'), m.x, m.y, mood === 'stalled' ? jump(m.k) : idle(m.k, 1.6)) });
    else if (mood === 'stalled') sp.push({ y: m.y, html: px(CHEER_L, AWAY, m.x - 1, m.y, jump(m.k)) });
    else sp.push({ y: m.y, html: px(PL, AWAY, m.x, m.y, idle(m.k, mood === 'td' ? 1.6 : 1.2)) });
  }
  if (chainsAt) {
    const [L, FD] = chainsAt;
    sp.push({ y: B0, html: box(L, B0 + 3, FD - L, 1, '#d7dbe2') + box(L - 1, B0, 2, 14, '#ff7a1a') + box(FD - 1, B0, 2, 14, '#ff7a1a') });
    sp.push({ y: B0 + 2, html: px(CREW, { O: '#ff7a1a', S: SKINS[1], K: '#141414' }, L + 3, B0 + 2) + px(CREW, { O: '#ff7a1a', S: SKINS[3], K: '#141414' }, FD + 3, B0 + 2) });
  }
  return sp.sort((a, b) => a.y - b.y).map((s) => s.html).join('');
}

const clampX = (x: number) => Math.min(344, x);

/** Offense + defense lined up at L. `anims` overrides the default idle animation per role. */
function formation(L: number, anims: Partial<Record<string, string>> = {}): Sprite[] {
  const on: Sprite[] = [];
  const add = (role: string, map: string[], pal: Pal, x: number, y: number, dflt: string) =>
    on.push({ y, html: px(map, pal, x, y, anims[role] ?? dflt) });
  [29, 40, 51, 62, 73].forEach((t, n) => add('ol' + n, PR, HOME, L - 12, F + t, anims.ol ? anims.ol.replace('DELAY', (n * 0.1).toFixed(1)) : idle(n, 0.9)));
  add('te', PR, HOME, L - 12, F + 84, anims.ol ? anims.ol.replace('DELAY', '0') : idle(5, 0.9));
  add('qb', PR, HOME, L - 34, F + 51, idle(1, 0.9));
  add('rb', PR, HOME, L - 36, F + 66, idle(2, 0.9));
  add('wr1', PR, HOME, L - 12, F + 4, idle(3, 0.9));
  add('slot', PR, HOME, L - 20, F + 16, 'animation:motion 2.4s steps(8,end) infinite');
  add('wr2', PR, HOME, L - 12, F + 100, idle(4, 0.9));
  [33, 45, 57, 69].forEach((t, n) => add('dl' + n, PL, AWAY, L + 3, F + t, anims.dl ? anims.dl.replace('DELAY', (n * 0.12).toFixed(2)) : idle(n + 2, 0.9)));
  [24, 51, 80].forEach((t, n) => add('lb' + n, PL, AWAY, L + 22, F + t, idle(n + 1, 1.1)));
  add('cb1', PL, AWAY, L + 5, F + 4, idle(0, 1.1));
  add('cb2', PL, AWAY, L + 5, F + 100, idle(2, 1.1));
  add('s1', PL, AWAY, L + 56, F + 28, idle(3, 1.3));
  add('s2', PL, AWAY, L + 56, F + 76, idle(4, 1.3));
  add('ref', REF, refPal(1), L + 84, F + 51, '');
  return on;
}

const PUSH = 'animation:push 0.5s steps(1,end) infinite;animation-delay:-DELAYs';
const PUSHBACK = 'animation:pushback 0.5s steps(1,end) infinite;animation-delay:-DELAYs';

export function field(mode: FieldMode): string {
  let under = '', over = '';
  let on: Sprite[] = [];
  let mood: SideMood = 'normal';
  let chains: [number, number] | null = null;

  if (mode.kind === 'huddle') {
    const L = X(mode.los), FD = X(Math.min(100, mode.los + 10));
    chains = [L, FD];
    const cx = L - 26, cy = F + 52;
    for (let n = 0; n < 11; n++) {
      const ang = (n / 11) * Math.PI * 2;
      const hx = Math.round(cx + 15 * Math.cos(ang)), hy = Math.round(cy + 13 * Math.sin(ang));
      on.push({ y: hy, html: px(Math.cos(ang) > 0 ? PL : PR, HOME, hx, hy, idle(n, 1.0)) });
    }
    [[13, 30], [13, 60], [15, 86], [35, 20], [37, 50], [33, 76], [57, 36], [60, 66], [85, 28], [87, 80], [109, 52]].forEach(([dx, dy], n) =>
      on.push({ y: F + dy, html: px(PL, AWAY, L + dx, F + dy, idle(n + 2, 1.3)) }));
    on.push({ y: F + 96, html: px(REF, refPal(1), L - 5, F + 96) });
    under = box(L - 1, F, 2, 120, '#4aa3ff') + box(FD - 1, F, 2, 120, '#ffd23f');
    over = px(BALL, BALL_PAL, L - 6, F + 59);
  } else if (mode.kind === 'formation' || (mode.kind === 'play' && mode.afterTD)) {
    // after a touchdown the offense lines up in victory formation near the goal line
    const los = mode.afterTD ? 92 : mode.los;
    const L = X(los);
    if (!mode.afterTD) {
      const FD = X(Math.min(100, los + 10));
      chains = [L, FD];
      under = box(L - 1, F, 2, 120, '#4aa3ff') + box(FD - 1, F, 2, 120, '#ffd23f');
    }
    on = formation(L);
    over = px(BALL, BALL_PAL, L - 6, F + 59);
  } else if (mode.kind === 'play') {
    const L = X(mode.los), FD = X(Math.min(100, mode.los + 10));
    chains = [L, FD];
    const end = clampX(X(mode.los + mode.gain));
    const g = mode.gain;
    under = box(FD - 1, F, 2, 120, 'rgba(255,210,63,0.6)');
    for (let d = 0; d < 120; d += 8) under += box(L - 1, F + d, 2, 4, 'rgba(74,163,255,0.8)');
    const base = { ol: PUSH, dl: PUSHBACK };
    const a = mode.tier.anim;
    if (a === 'deep') {
      const arc = -Math.min(58, 20 + 2 * g);
      for (let s = 1; s < 16; s++) {
        const t = s / 16;
        const tx = Math.round(L - 40 + (end - L + 40) * t), ty = Math.round(F + 56 + (arc * 4 - 4) * t * (1 - t));
        under += box(tx - 1, Math.max(F + 2, ty) - 1, 2, 2, 'rgba(255,210,63,0.55)');
      }
      on = formation(L, {
        ...base,
        qb: play('drop', 4, { dx: -8 }),
        wr1: play('route', 12, { dx: end - (L - 12) - 2, dy: 40 }),
        slot: play('route', 10, { dx: 20, dy: 46 }),
        wr2: play('route', 10, { dx: 5, dy: -20 }),
        cb1: play('route', 12, { dx: end - (L + 5) - 10, dy: 40 }),
        s1: play('route', 12, { dx: Math.max(4, end - (L + 56) + 4), dy: 18 }),
      });
      over = px(BALL, BALL_PAL, L - 40, F + 52, play('bomb', 16, { dx: end - (L - 40) - 4, dy: -2, mx: (end - (L - 40)) / 2, arc }));
    } else if (a === 'short') {
      const tx = end - (L - 20);
      on = formation(L, {
        ...base,
        qb: play('drop', 4, { dx: -6 }),
        slot: play('route', 10, { dx: tx, dy: 26 }),
        lb0: play('route', 10, { dx: Math.max(2, end - (L + 22) + 8), dy: 18 }),
      });
      over = px(BALL, BALL_PAL, L - 40, F + 52, play('pass', 12, { dx: end - (L - 40) - 2, dy: -6, mx: (end - (L - 40)) / 2, arc: -16 }));
    } else if (a === 'run') {
      const dx = end - (L - 36) - 4;
      on = formation(L, {
        ...base,
        rb: play('run', 10, { dx, dy: -10 }),
        lb1: play('route', 10, { dx: Math.max(0, end - (L + 22) + 4), dy: 6 }),
        qb: play('drop', 4, { dx: -4 }),
      });
      over = px(BALL, BALL_PAL, L - 34, F + 66, play('run', 10, { dx: dx + 2, dy: -10 }));
    } else {
      // incomplete: the ball falls short, no gain
      on = formation(L, {
        ...base,
        qb: play('drop', 4, { dx: -8 }),
        wr1: play('route', 12, { dx: 40, dy: 30 }),
        cb1: play('route', 12, { dx: 30, dy: 32 }),
      });
      over = px(BALL, BALL_PAL, L - 40, F + 52, play('miss', 12, { dx: 50, dy: 30, mx: 30, arc: -30 }));
    }
  } else if (mode.kind === 'td') {
    mood = 'td';
    on = [
      { y: F + 46, html: px(CHEER_R, HOME, 332, F + 46, jump(0)) },
      { y: F + 30, html: px(CHEER_R, HOME, 314, F + 30, jump(1)) },
      { y: F + 64, html: px(CHEER_R, HOME, 316, F + 64, jump(2)) },
      { y: F + 20, html: px(PR, HOME, 292, F + 20, jump(3)) },
      { y: F + 84, html: px(PR, HOME, 290, F + 84, jump(1)) },
      { y: F + 50, html: px(PL, AWAY, 268, F + 50, idle(0, 1.8)) },
      { y: F + 72, html: px(PL, AWAY, 252, F + 72, idle(2, 1.8)) },
      { y: F + 28, html: px(PL, AWAY, 260, F + 28, idle(4, 1.8)) },
      { y: F + 100, html: px(REF_TD, refPal(0), 296, F + 100, jump(2)) },
    ];
    over = px(BALL, BALL_PAL, 340, F + 40, jump(0));
    const conf = ['#ffd23f', '#5aa9ff', '#46d17a', '#ff8a3d', '#b57aff', '#f4f4ee'];
    for (let c = 0; c < 48; c++) {
      over += box((c * 53 + 17) % 352, F - 10 + ((c * 37) % 80), 3, 3, conf[c % 6],
        `animation:fall ${(1.6 + (c % 4) * 0.3).toFixed(1)}s steps(10,end) infinite;animation-delay:-${((c * 0.13) % 2).toFixed(2)}s`);
    }
  } else {
    mood = 'stalled';
    const L = X(mode.los);
    under = box(L - 1, F, 2, 120, '#4aa3ff');
    [[-14, 30], [-12, 42], [-14, 54], [-12, 66], [-14, 78], [-30, 50], [-34, 70], [-24, 14], [-20, 96], [-44, 36], [-46, 84]].forEach(([dx, dy], n) =>
      on.push({ y: F + dy, html: px(SLUMP, HOME, L + dx, F + dy, still(n)) }));
    [[4, 26], [6, 40], [4, 56], [6, 72], [22, 18], [24, 48], [22, 82], [40, 30], [44, 66], [62, 42], [64, 92]].forEach(([dx, dy], n) =>
      on.push({ y: F + dy, html: px(CHEER_L, AWAY, L + dx, F + dy, jump(n)) }));
    on.push({ y: F + 100, html: px(REF, refPal(1), Math.min(L + 84, 340), F + 100) });
    over = px(BALL, BALL_PAL, L - 6, F + 59);
  }

  return turf() + under + sidelines(mood, chains) + on.sort((a, b) => a.y - b.y).map((s) => s.html).join('') + over;
}
