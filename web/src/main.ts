// Griddion app: screens, game flow, timer, resume, share. Mobile-first 390px column.
import './styles.css';
import { TIERS, LEGEND_ORDER, RULES, driveState, yardsOnPlay, ballSpot, clockText, shareText, playCell, MAX_POINTS, type PlayRecord, type Tier } from './game';
import { preloadSound, unlockSound, sfx, isMuted, setMuted } from './sound';
import { shouldShowFeedback, showFeedback, closeFeedback } from './feedback';
import { now, setMockNow, todayET, msUntilMidnightET, daysBetween } from './clock';
import { load, save, store, displayStreak, recordFinish } from './storage';
import { loadSchedule, loadDay, loadMatchData, matcherFor, HttpError, type Day, type Prompt, type Answer, type Schedule } from './data';
import { stadium, field, type FieldMode } from './field';
import { normName } from './matching';

// ---------------------------------------------------------------- helpers

const $app = document.getElementById('app')!;
const esc = (s: unknown) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
const pad3 = (n: number) => String(n).padStart(3, '0');
const reduceMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const isDesktop = () => window.matchMedia('(min-width: 1100px)').matches;

let toastTimer = 0;
function toast(msg: string) {
  document.querySelector('.toast')?.remove();
  const t = document.createElement('div');
  t.className = 'toast';
  t.setAttribute('role', 'status');
  t.textContent = msg;
  document.body.appendChild(t);
  clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => t.remove(), 2200);
}

// ---------------------------------------------------------------- state

let schedule: Schedule | null = null;
let day: Day | null = null;
let driveNo = 0;
let view: 'game' | 'answers' = 'game';
let answersTab = 0;
let answersSort: 'tier' | 'az' = 'tier';
let answersQuery = '';
let tick = 0;
let submitting = false;
let overlay: { kind: 'picker'; typed: string } | { kind: 'confirm'; typed: string; answer: Answer } | null = null;
let expiring = false;

const game = () => store().game!;
const answerById = (p: Prompt, id: string | null) => (id ? p.answers.find((a) => a.id === id) : undefined);

function stopTimer() { if (tick) { clearInterval(tick); tick = 0; } }

// ---------------------------------------------------------------- shared chrome

/** Published drives (dated today or earlier) in date order. */
function publishedDrives(): number[] {
  if (!schedule) return [];
  const today = todayET();
  return schedule.drives.filter((d) => d.date <= today).sort((a, b) => a.date.localeCompare(b.date)).map((d) => d.drive);
}
function todaysDrive(): number | null {
  const today = todayET();
  return schedule?.drives.find((d) => d.date === today)?.drive ?? null;
}
function streakNow(): number { return displayStreak(publishedDrives(), todaysDrive()); }
/** The published drive just before `drive`, or null. */
function prevDrive(drive: number): number | null {
  const p = publishedDrives(), i = p.indexOf(drive);
  return i > 0 ? p[i - 1] : null;
}

function header(): string {
  const st = store().stats;
  return `<div class="hdr"><span class="silk logo">GRIDDION</span><span class="hdr-r"><span class="rec">STREAK ${streakNow()} · ${st.wins}W ${st.losses}L</span>${muteButton()}</span></div>`;
}

// Pixel speaker icon (16×16 grid): waves when sound is on, an X when muted.
function muteButton(): string {
  const m = isMuted();
  const icon = `<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" shape-rendering="crispEdges" fill="currentColor"><path d="M1 5h3v6H1zM4 5h1V4h1V3h1V2h1v12H7v-1H6v-1H5v-1H4z"/>${m
    ? '<path d="M10 5h1v1h1v1h1V6h1V5h1v1h-1v1h-1v2h1v1h1v1h-1v-1h-1V9h-1v1h-1v1h-1v-1h1V9h1V7h-1V6h-1z"/>'
    : '<path d="M10 6h1v4h-1zM12 4h1v1h1v6h-1v1h-1v-1h1V5h-1z"/>'}</svg>`;
  return `<button type="button" class="mute" aria-label="${m ? 'Unmute sound' : 'Mute sound'}" aria-pressed="${m}">${icon}</button>`;
}
document.addEventListener('click', (e) => {
  const b = (e.target as Element).closest('.mute');
  if (!b) return;
  setMuted(!isMuted());
  document.querySelectorAll('.mute').forEach((el) => { el.outerHTML = muteButton(); });
  inputEl()?.focus({ preventScroll: true });
});
// Audio can only start inside a user gesture; the first tap or key anywhere (normally "Break the huddle") unlocks it.
for (const ev of ['pointerdown', 'keydown', 'touchend']) document.addEventListener(ev, unlockSound, { capture: true, passive: true });

function top(screen: string, foot: string): string {
  return `<div class="top">${stadium(Math.min(390, document.documentElement.clientWidth))}<div class="post" style="left:92px" aria-hidden="true"></div><div class="post" style="right:92px" aria-hidden="true"></div>
    <div class="jumbo">${header()}${screen}${foot ? `<div class="jfoot">${foot}</div>` : ''}</div></div>`;
}

function fieldBox(mode: FieldMode, label: string): string {
  return `<div class="field" role="img" aria-label="${esc(label)}"><div class="field-inner">${field(mode)}</div></div>`;
}

function wristband(title: string, meta: string, body: string, metaStyle = ''): string {
  return `<div class="wb"><div class="wb-dash"><div class="paper">
    <div class="paper-head"><span class="silk">${title}</span><span class="meta" ${metaStyle ? `style="${metaStyle}"` : ''}>${meta}</span></div>
    ${body}</div></div></div>`;
}

function cellHtml(plays: PlayRecord[], i: number): string {
  const c = playCell(plays, i);
  if (c.kind === 'td') return '<span class="v td">TD</span>';
  if (c.kind === 'pts') return `<span class="v pts">+${c.value}<small>PTS</small></span>`;
  return `<span class="v">+${c.value}</span>`;
}

function driveLog(plays: PlayRecord[], current: number): string {
  let s = '<div class="log" aria-label="Drive log">';
  for (let i = 0; i < RULES.plays; i++) {
    const p = plays[i];
    if (p) {
      const t = TIERS[p.tier];
      s += `<div><span class="n">P${i + 1}</span>${cellHtml(plays, i)}<span class="bar" style="background:${t.color}"></span></div>`;
    } else if (i === current) {
      s += `<div class="cur"><span class="n">P${i + 1}</span><span class="v">?</span><span class="bar"></span></div>`;
    } else {
      s += `<div><span class="n">P${i + 1}</span><span class="v"></span><span class="bar"></span></div>`;
    }
  }
  return s + '</div>';
}

function legend(): string {
  return `<div class="legend">${LEGEND_ORDER.map((k) => {
    const t = TIERS[k];
    return `<div><span class="chipdot" style="background:${t.color}"></span><span>${k === 'Botched Trick Play' ? 'Trick play' : t.key} +${t.yards}</span></div>`;
  }).join('')}</div>`;
}

let feedbackTimer = 0;
function mount(html: string, cls = '') {
  clearTimeout(feedbackTimer);
  closeFeedback();
  $app.className = 'app ' + cls;
  $app.innerHTML = html;
  window.scrollTo(0, 0);
}

// ---------------------------------------------------------------- simple screens

function messageScreen(title: string, sub: string, card: string, opts: { blink?: boolean; button?: string; onButton?: () => void } = {}) {
  stopTimer();
  const screen = `<div class="screen center dot"><h1 class="s32 ${opts.blink ? 'blink' : ''}" style="color:#ffd23f">${esc(title)}</h1><p class="s16 dim">${esc(sub)}</p><div class="grow"></div></div>`;
  const body = `<p class="copy">${card}</p>${opts.button ? `<button type="button" class="btn" id="msgbtn">${esc(opts.button)}</button>` : ''}`;
  mount(top(screen, '') + fieldBox({ kind: 'huddle', los: 25 }, 'Pixel football field. The offense waits in a huddle at its own 25-yard line.') + wristband("COACH'S CALL", '', body));
  if (opts.onButton) document.getElementById('msgbtn')?.addEventListener('click', opts.onButton);
}

function countdownScreen(launch: string) {
  stopTimer();
  const left = () => {
    const ms = msUntilMidnightET() + Math.max(0, daysBetween(todayET(), launch) - 1) * 86400000;
    const s = Math.ceil(ms / 1000);
    return `${Math.floor(s / 3600)}:${String(Math.floor(s / 60) % 60).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
  };
  const screen = `<div class="screen center dot"><p class="s16 dim">KICKOFF AT MIDNIGHT</p><p class="s48" id="cd" aria-live="off">${left()}</p><p class="s16" style="color:#6fb4ff">DRIVE #1 · 12:00 AM ET</p><div class="grow"></div></div>`;
  const body = `<p class="copy">Griddion kicks off at midnight Eastern. Come back for Drive #1: seven plays, 25 seconds each, and rarer answers go deeper.</p>
    <p class="rule">ONE DRIVE A DAY · NEW DRIVE EVERY MIDNIGHT ET</p>`;
  mount(top(screen, '<span>BALL · OWN 25</span><span>PTS · 000</span>') +
    fieldBox({ kind: 'huddle', los: 25 }, 'Pixel football field. The offense waits in a huddle at its own 25-yard line before kickoff.') +
    wristband("COACH'S CALL", 'PREGAME', body));
  tick = window.setInterval(() => {
    if (todayET() >= launch) { stopTimer(); boot(); return; }
    const el = document.getElementById('cd');
    if (el) el.textContent = left();
  }, 500);
}

// ---------------------------------------------------------------- intro

function introScreen() {
  const st = driveState([]);
  const screen = `<div class="screen dot" style="padding:14px 16px 12px;gap:10px">
      <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;text-align:center">
        <div style="display:flex;flex-direction:column;align-items:center;gap:6px"><span class="s16" style="color:var(--home-led)">HOME · YOU</span><span class="s48">${RULES.trail[0]}</span></div>
        <div style="display:flex;flex-direction:column;align-items:center;gap:6px"><span class="s16" style="color:var(--away-led)">AWAY</span><span class="s48">${RULES.trail[1]}</span></div>
      </div><div class="grow"></div>
      <div style="display:flex;justify-content:center;align-items:baseline;gap:16px"><span class="s16 dim">4TH QTR</span><span class="s32 blink" style="color:#ffd23f">${clockText(st.clock)}</span></div>
    </div>`;
  const body = `<p class="copy">Your team is down 4 points with 2:55 left in the game. Use your ball knowledge to get your team down the field and complete the game-winning drive!</p>
    <p class="rule">7 PLAYS · 25 SECONDS EACH · RARER ANSWERS GO DEEPER</p>
    <button type="button" class="btn" id="go">BREAK THE HUDDLE</button>`;
  mount(top(screen, `<span>BALL · ${ballSpot(st.yardline)}</span><span>PTS · 000</span>`) +
    fieldBox({ kind: 'huddle', los: 25 }, 'Pixel football field. Your eleven players are in a huddle behind the ball at your own 25-yard line while the defense waits across the line.') +
    wristband("COACH'S CALL", `DRIVE #${driveNo}`, body));
  const go = document.getElementById('go')!;
  go.addEventListener('click', startPlay);
  if (isDesktop()) go.focus();
}

// ---------------------------------------------------------------- play

function startPlay() {
  const g = game();
  g.phase = 'play';
  g.deadline = now() + RULES.secondsPerPlay * 1000;
  overlay = null;
  expiring = false;
  save();
  render();
}

function secondsLeft(): number {
  const d = game().deadline;
  return d === null ? RULES.secondsPerPlay : Math.max(0, Math.ceil((d - now()) / 1000));
}

function playScreen() {
  const g = game();
  const i = g.plays.length;
  const p = day!.prompts[i];
  const st = driveState(g.plays);
  const secs = secondsLeft();
  const screen = `<div class="screen dot">
      <span class="s16 dim">PLAY ${i + 1} OF ${RULES.plays}</span>
      <h1 class="s32 upper${p.text.length > 40 ? ' long' : ''}" id="prompt">${esc(p.text)}</h1>
      <p class="s16 dim upper" style="font-size:16px">${esc(p.subtitle)}</p>
      <div class="grow"></div>
      <div class="timer" id="timer" role="timer" aria-label="Time left"><div class="segs">${'<i></i>'.repeat(25)}</div><span class="s16" id="secs">${clockText(secs)}</span></div>
    </div>`;
  const mode: FieldMode = { kind: 'formation', los: st.yardline, afterTD: st.tdPlay !== null };
  const label = st.tdPlay !== null
    ? 'Pixel football field. You already scored; the offense lines up again near the goal line.'
    : `Pixel football field. Both teams, eleven a side, are lined up at ${ballSpot(st.yardline).toLowerCase().replace('own', 'your own').replace('opp', "the opponent's")}${st.yardline !== 50 ? '-yard line' : ''}.`;
  const desk = isDesktop();
  const form = `<form class="callit" id="callit" autocomplete="off">
      <label for="answer"${desk ? '' : ' class="sr-only"'}>CALL IT</label>
      <div class="row"><input id="answer" type="text" autocomplete="off" autocapitalize="words" autocorrect="off" spellcheck="false" enterkeyhint="go" placeholder="type a player…" maxlength="60"><button type="submit" class="btn">SNAP</button></div>
      <p class="flash" id="flash" role="status" aria-live="assertive"></p>
    </form>`;
  const jumboHtml = top(screen, `<span>BALL · ${ballSpot(st.yardline)}</span><span class="desk">4TH QTR · ${clockText(st.clock)}</span><span>PTS · ${pad3(st.points)}</span>`);
  // Desktop: wristband holds log + input + key. Phone: input sits right under the jumbotron so the
  // prompt, subtitle, clock and input all fit above the on-screen keyboard; then field, then log + key.
  const layout = desk
    ? jumboHtml + fieldBox(mode, label) + wristband('QB WRISTBAND', `DRIVE #${driveNo}`, `${driveLog(g.plays, i)}${form}${legend()}`)
    : jumboHtml + `<div class="callcard"><div class="paper">${form}</div></div>` + fieldBox(mode, label) + wristband('QB WRISTBAND', `DRIVE #${driveNo}`, `${driveLog(g.plays, i)}${legend()}`);
  mount(`<div class="mini dot" id="mini" aria-hidden="true"><span class="upper" style="overflow:hidden;white-space:nowrap;text-overflow:ellipsis">${esc(p.text)}</span><span id="minisecs">${clockText(secs)}</span></div>` + layout, desk ? '' : 'playm');

  const input = document.getElementById('answer') as HTMLInputElement;
  document.getElementById('callit')!.addEventListener('submit', (e) => { e.preventDefault(); submit(input.value); });
  input.focus({ preventScroll: true });
  // Phone: when the keyboard opens the browser scrolls to the input; put the page back at the top so
  // the jumbotron and input sit together above the keyboard.
  if (!desk) input.addEventListener('focus', () => setTimeout(() => { if (!isDesktop()) window.scrollTo(0, 0); }, 300));

  // When the phone keyboard pushes the jumbotron off screen, pin a mini prompt bar.
  const mini = document.getElementById('mini')!;
  const jumbo = document.querySelector('.jumbo')!;
  new IntersectionObserver(([e]) => mini.classList.toggle('show', !e.isIntersecting && view === 'game' && game().phase === 'play'), { threshold: 0.35 }).observe(jumbo);

  stopTimer();
  updateTimer();
  tick = window.setInterval(updateTimer, 200);
  matcherFor(p); // warm the matcher
}

let lastSecs = -1; // for the last-5-seconds tick
function updateTimer() {
  const g = game();
  if (g.phase !== 'play' || g.deadline === null) return;
  const msLeft = g.deadline - now();
  const secs = Math.max(0, Math.ceil(msLeft / 1000));
  const segs = document.querySelectorAll('#timer .segs i');
  segs.forEach((el, k) => el.classList.toggle('on', k < secs));
  document.getElementById('timer')?.classList.toggle('low', secs <= 5);
  if (secs !== lastSecs) { if (secs > 0 && secs <= 5 && lastSecs !== -1) sfx.tick(); lastSecs = secs; }
  const txt = clockText(secs);
  for (const id of ['secs', 'minisecs']) { const el = document.getElementById(id); if (el && el.textContent !== txt) el.textContent = txt; }
  if (msLeft <= 0) expire();
}

const inputEl = () => document.getElementById('answer') as HTMLInputElement | null;
const timeoutRec = (typed = ''): PlayRecord => ({ typed, playerId: null, name: null, tier: 'Incomplete', reason: 'timeout' });
const validRec = (typed: string, a: Answer): PlayRecord => ({ typed, playerId: a.id, name: a.name, tier: a.tier, reason: 'valid' });

/** Clock hit 0:00 (§9): an open "Did you mean" is accepted; otherwise whatever is typed is submitted once. */
function expire() {
  const g = game();
  if (g.phase !== 'play' || expiring) return;
  expiring = true;
  stopTimer();
  if (overlay?.kind === 'confirm') { const o = overlay; return record(validRec(o.typed, o.answer)); }
  if (overlay?.kind === 'picker') return record(timeoutRec(overlay.typed)); // no valid answer chosen in time
  submit(inputEl()?.value ?? '', true);
}

/** Run a guess through the matcher. Wrong guesses don't end the play unless the clock has run out. */
async function submit(typed: string, timedOut = false) {
  const g = game();
  if (g.phase !== 'play' || overlay) return;
  if (!timedOut && (submitting || expiring)) return;
  const p = day!.prompts[g.plays.length];
  if (!typed.trim()) { if (timedOut) record(timeoutRec()); return; }
  submitting = true;
  try {
    const m = await matcherFor(p);
    if (g.phase !== 'play' || (expiring && !timedOut)) return; // the clock ran out while loading; expire() handles it
    const r = m.match(typed);
    if (r.status === 'valid') {
      const a = answerById(p, r.playerId)!;
      if (r.method === 'fuzzy' && !timedOut) showConfirm(typed, a);
      else record(validRec(typed, a));
    } else if (r.status === 'ambiguous') {
      if (timedOut) return record(timeoutRec(typed));
      const cands = r.candidates.map((id) => answerById(p, id)).filter((a): a is Answer => !!a);
      const last = (cands[0]?.name ?? typed).split(' ').filter((w) => !/^(jr|sr|ii|iii|iv|v)\.?$/i.test(w)).pop() ?? typed;
      showPicker(typed, cands, cands.every((c) => c.name === cands[0].name) ? `Which ${cands[0].name}?` : `Which ${last}?`);
    } else if (timedOut) {
      const d = await loadMatchData();
      record({
        typed, playerId: r.playerId, name: r.playerId ? d.nameById.get(r.playerId) ?? null : null,
        tier: 'Incomplete', reason: r.method === 'not_valid_answer' ? 'not_valid_answer' : 'no_match',
      });
    } else {
      wrongGuess();
    }
  } finally {
    submitting = false;
  }
}

let flashTimer = 0;
function wrongGuess() {
  const input = inputEl();
  if (!input) return;
  input.value = '';
  input.focus({ preventScroll: true });
  sfx.buzzer();
  const row = input.closest('.row')!;
  row.classList.remove('shake');
  void (row as HTMLElement).offsetWidth; // restart the animation
  row.classList.add('shake');
  const fl = document.getElementById('flash')!;
  fl.textContent = 'Not on the board';
  fl.classList.add('show');
  clearTimeout(flashTimer);
  flashTimer = window.setTimeout(() => fl.classList.remove('show'), 1400);
}

function openOverlay(label: string, html: string): HTMLElement {
  const paper = document.querySelector('.callcard .paper') ?? document.querySelector('.wb .paper')!;
  const el = document.createElement('div');
  el.className = 'picker';
  el.setAttribute('role', 'dialog');
  el.setAttribute('aria-label', label);
  el.innerHTML = html;
  paper.appendChild(el);
  return el;
}

function showPicker(typed: string, cands: Answer[], label: string) {
  overlay = { kind: 'picker', typed };
  const el = openOverlay(label, `<h2 class="silk">${esc(label.toUpperCase())}</h2>
    ${cands.map((a, k) => `<button type="button" class="pick" data-k="${k}"><b>${esc(a.name)}</b><span>${esc(a.context)}</span></button>`).join('')}
    <button type="button" class="back">Not them, let me retype</button>`);
  el.querySelectorAll<HTMLButtonElement>('.pick').forEach((b) => b.addEventListener('click', () => {
    if (overlay?.kind !== 'picker') return;
    record(validRec(typed, cands[Number(b.dataset.k)]));
  }));
  el.querySelector('.back')!.addEventListener('click', () => closeOverlay(false));
  (el.querySelector('.pick') as HTMLButtonElement | null)?.focus({ preventScroll: true });
}

function showConfirm(typed: string, a: Answer) {
  overlay = { kind: 'confirm', typed, answer: a };
  const el = openOverlay(`Did you mean ${a.name}?`, `<h2 class="silk">DID YOU MEAN</h2>
    <div class="pick" style="cursor:default;box-shadow:none"><b>${esc(a.name)}?</b><span>${esc(a.context)}</span></div>
    <div class="btns"><button type="button" class="btn" id="yes">YES</button><button type="button" class="btn2" id="no">NO</button></div>`);
  el.querySelector('#yes')!.addEventListener('click', () => { if (overlay?.kind === 'confirm') record(validRec(typed, a)); });
  el.querySelector('#no')!.addEventListener('click', () => closeOverlay(true));
  (el.querySelector('#yes') as HTMLButtonElement).focus({ preventScroll: true });
}

/** Close a picker/confirmation and go back to guessing (the clock never stopped). */
function closeOverlay(clear: boolean) {
  overlay = null;
  document.querySelector('.picker')?.remove();
  const input = inputEl();
  if (input) { if (clear) input.value = ''; input.focus({ preventScroll: true }); }
}

function record(rec: PlayRecord) {
  const g = game();
  if (g.phase !== 'play') return;
  stopTimer();
  overlay = null;
  g.plays.push(rec);
  g.phase = 'result';
  g.deadline = null;
  save();
  sfx.whistle();
  render();
  window.setTimeout(() => sfx.tier(rec.tier), 380);
}

// ---------------------------------------------------------------- result

function resultScreen() {
  const g = game();
  const i = g.plays.length - 1;
  const rec = g.plays[i];
  const p = day!.prompts[i];
  const t = TIERS[rec.tier];
  const before = driveState(g.plays.slice(0, i));
  const after = driveState(g.plays);
  const gain = yardsOnPlay(g.plays, i);
  const scoredNow = before.tdPlay === null && after.tdPlay !== null;
  const valid = rec.reason === 'valid';

  const headline = valid ? t.short + '!' : "TIME'S UP";
  const who = valid ? rec.name! : rec.reason === 'timeout' || rec.reason === 'empty' ? 'NO CALL' : rec.name ?? rec.typed;
  const playLine = `${t.play.toUpperCase()} · +${gain} YDS · +${t.points} PTS`;
  const screen = `<div class="screen dot">
      <span class="s16 dim upper" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">PLAY ${i + 1} · ${esc(p.text)}</span>
      <h1 class="s32 blink" style="color:${scoredNow ? '#ffd23f' : t.led};animation-duration:0.8s">${scoredNow ? 'TOUCHDOWN!' : headline}</h1>
      <p class="s32 upper" style="overflow-wrap:anywhere">${esc(who)}</p>
      <div class="grow"></div>
      <p class="s16" style="line-height:1.1">${playLine}</p>
    </div>`;

  let ctx: string;
  if (valid) {
    const a = answerById(p, rec.playerId);
    ctx = `<b>${esc(rec.name)}</b>${esc(a?.context ?? '')}`;
  } else if (rec.reason === 'not_valid_answer') {
    ctx = `<b>${esc(rec.name ?? rec.typed)}</b>Real player, but not a valid answer for this one. Time ran out. No gain.`;
  } else if (rec.reason === 'no_match') {
    ctx = `<b>“${esc(rec.typed.trim())}”</b>Not on the board, and time ran out. No gain.`;
  } else if (rec.reason === 'timeout') {
    ctx = `<b>Play clock hit zero.</b>No valid answer in time. No gain.`;
  } else {
    ctx = `<b>No call made.</b>No gain on the play.`;
  }
  if (before.tdPlay !== null) ctx += `<br><span style="color:var(--muted)">Already in the end zone. The points still count.</span>`;
  if (scoredNow && i < RULES.plays - 1) ctx += `<br><span style="color:var(--muted)">Touchdown on P${i + 1}! Keep playing all 7 for points.</span>`;

  const last = i === RULES.plays - 1;
  const body = `${driveLog(g.plays, -1)}
    <div class="ctx"><span class="chipdot" style="background:${t.color}"></span><p>${ctx}</p></div>
    <button type="button" class="btn" id="next">${last ? 'FINAL WHISTLE' : 'NEXT PLAY'}</button>`;

  const mode: FieldMode = reduceMotion()
    ? (after.tdPlay !== null ? { kind: 'formation', los: after.yardline, afterTD: true } : { kind: 'formation', los: after.yardline })
    : { kind: 'play', los: before.yardline, gain, tier: t, afterTD: before.tdPlay !== null };
  const label = valid ? `Pixel football field. ${t.play}: the offense gains ${gain} yards.` : 'Pixel football field. The pass falls incomplete. No gain.';
  mount(top(screen, `<span>BALL · ${ballSpot(after.yardline)}</span><span class="desk">4TH QTR · ${clockText(after.clock)}</span><span>PTS · ${pad3(after.points)}</span>`) + fieldBox(mode, label) +
    wristband('QB WRISTBAND', `DRIVE #${driveNo}`, body));
  const next = document.getElementById('next')!;
  next.addEventListener('click', advance);
  next.focus({ preventScroll: true });
}

function advance() {
  const g = game();
  if (g.phase !== 'result') return;
  if (g.plays.length >= RULES.plays) {
    g.phase = 'done';
    save();
    const td = driveState(g.plays).tdPlay !== null;
    recordFinish(driveNo, td, prevDrive(driveNo));
    render();
    window.setTimeout(() => (td ? sfx.touchdown() : sfx.stalled()), 250);
  } else startPlay();
}

// ---------------------------------------------------------------- recap

function chartCell(plays: PlayRecord[], i: number): string {
  const c = playCell(plays, i);
  if (c.kind === 'td') return '<span class="yd td">TD</span>';
  if (c.kind === 'pts') return `<span class="yd pts">+${c.value}<small>PTS</small></span>`;
  return `<span class="yd">+${c.value}</span>`;
}

function recapScreen() {
  const g = game();
  const st = driveState(g.plays);
  const td = st.tdPlay !== null;
  const stats = store().stats;
  const score = td ? RULES.win : RULES.trail;
  const squares = g.plays.map((p) => `<i style="background:${TIERS[p.tier].color};border:2px solid #0a0a10" title="${esc(TIERS[p.tier].key)}"></i>`).join('');
  const screen = `<div class="screen center dot">
      <h1 class="s32 ${td ? 'blink-fast' : 'blink'}" style="color:${td ? '#ffd23f' : '#ff8a80'}">${td ? 'TOUCHDOWN!' : 'DRIVE STALLED'}</h1>
      <div class="score"><span class="s16" style="color:var(--home-led)">YOU</span><span class="s32">${score[0]}</span><span class="s16 dim">–</span><span class="s32">${score[1]}</span><span class="s16" style="color:var(--away-led)">AWAY</span></div>
      <p class="s16 dim">${st.points} / ${MAX_POINTS} PTS · ${st.yards} YDS · ${td && st.tdPlay! < RULES.plays ? 'TD ON P' + st.tdPlay : '7 PLAYS'}</p>
      <div class="grow"></div>
      <div class="leds" aria-label="Play results">${squares}</div>
    </div>`;
  const rows = g.plays.map((p, i) => {
    const t = TIERS[p.tier];
    return `<div><span class="n">${i + 1}</span><span class="play">${esc(t.play)}</span><span class="chip" style="background:${t.color};color:${t.ink}">${t.short}</span>${chartCell(g.plays, i)}</div>`;
  }).join('');
  const meta = td ? `RECORD ${stats.wins}–${stats.losses}` : `${RULES.touchdownYards - st.yards} YDS SHORT · RECORD ${stats.wins}–${stats.losses}`;
  const body = `<div class="chart" aria-label="Drive chart">${rows}</div>
    <div class="btns"><button type="button" class="btn" id="share">SHARE</button><a class="btn2" href="#answers" id="all">ALL ANSWERS</a></div>`;
  mount(top(screen, `<span>DRIVE #${driveNo} COMPLETE</span><span class="desk">FINAL · 0:00</span><span>${st.points} / ${MAX_POINTS} PTS</span>`) +
    fieldBox(td ? { kind: 'td' } : { kind: 'stalled', los: st.yardline },
      td ? 'Pixel football field. Touchdown! Your players jump in the end zone, the ref signals the score, and confetti falls.'
        : 'Pixel football field. The drive stalled. The defense and the visiting sideline celebrate while your offense slumps.') +
    wristband('DRIVE CHART', meta, body, `color:${td ? '#198a4a' : '#c8352f'}`));
  document.getElementById('share')!.addEventListener('click', share);
  // Feedback popup ~2 s after the recap appears, so the result lands first.
  if (shouldShowFeedback(stats.wins + stats.losses)) {
    feedbackTimer = window.setTimeout(() => {
      if (view === 'game' && document.getElementById('share')) showFeedback(driveNo, isDesktop() ? 'desktop' : 'mobile');
    }, 2000);
  }
}

async function share() {
  const text = shareText(driveNo, game().plays);
  const mobile = window.matchMedia('(pointer: coarse)').matches;
  if (navigator.share && mobile) {
    try { await navigator.share({ text }); return; } catch (e) { if ((e as Error).name === 'AbortError') return; }
  }
  try {
    await navigator.clipboard.writeText(text);
    toast('Copied!');
  } catch {
    // last resort: a selectable textarea copy
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    ta.remove();
    toast(ok ? 'Copied!' : "Couldn't copy. Try again.");
  }
}

// ---------------------------------------------------------------- all answers

const GROUP_ORDER: Exclude<Tier, 'Incomplete'>[] = ['YKB Kid', 'Sleeper Pick', 'Hidden Gem', 'Backup', 'Botched Trick Play', 'Starter'];

function answersScreen() {
  stopTimer();
  const g = game();
  const p = day!.prompts[answersTab];
  const mine = g.plays[answersTab];
  const tabs = day!.prompts.map((_, i) => {
    const t = g.plays[i] ? TIERS[g.plays[i].tier] : null;
    return `<button type="button" class="tab" data-i="${i}" aria-pressed="${i === answersTab}" aria-label="Play ${i + 1}"><span>P${i + 1}</span><span class="bar" style="background:${t ? t.color : 'transparent'}"></span></button>`;
  }).join('');
  mount(`<div class="jumbo">${header()}
      <div class="screen dot"><span class="s16 dim">ALL ANSWERS · DRIVE #${driveNo}</span><h1 class="s32 upper">${esc(p.text)}</h1><span class="s16 dim">${p.answers.length} ANSWERS</span></div></div>
    <nav class="tabs" aria-label="Prompts">${tabs}</nav>
    <div class="findrow"><label for="find" class="sr-only">Search answers</label><input id="find" type="search" autocomplete="off" placeholder="search players…" value="${esc(answersQuery)}">
      <div class="sort" role="group" aria-label="Sort"><button type="button" class="sortbtn" data-s="tier" aria-pressed="${answersSort === 'tier'}">TIER</button><button type="button" class="sortbtn" data-s="az" aria-pressed="${answersSort === 'az'}">A–Z</button></div></div>
    <div class="list-wrap"><div><div class="list" id="list">${answersList(p, mine)}</div></div></div>
    <a class="btn" href="#" id="back">BACK TO RECAP</a>`, 'ans');

  document.querySelectorAll<HTMLButtonElement>('.tab').forEach((b) => b.addEventListener('click', () => { answersTab = Number(b.dataset.i); answersScreen(); }));
  document.querySelectorAll<HTMLButtonElement>('.sortbtn').forEach((b) => b.addEventListener('click', () => { answersSort = b.dataset.s as 'tier' | 'az'; answersScreen(); }));
  const find = document.getElementById('find') as HTMLInputElement;
  find.addEventListener('input', () => { answersQuery = find.value; document.getElementById('list')!.innerHTML = answersList(p, mine); });
}

function aRow(a: Answer, cls = '', tag = ''): string {
  return `<div class="arow ${cls}">${tag}<div class="who"><b>${esc(a.name)}</b><span>${esc(a.context)}</span></div></div>`;
}

function answersList(p: Prompt, mine: PlayRecord | undefined): string {
  const q = normName(answersQuery);
  const hit = (a: Answer) => !q || [a.name, ...a.names, ...a.last_names].some((n) => normName(n).includes(q));
  let pinned = '';
  if (!q) {
    if (mine) {
      const t = TIERS[mine.tier];
      const a = answerById(p, mine.playerId);
      const chip = `<span class="tag" style="background:${t.color};color:${t.ink};border:2px solid var(--ink)">${t.short.replace(' PICK', '')} +${t.points}</span>`;
      const yp = `<span class="tag" style="background:var(--ink);color:var(--cream)">YOUR PICK</span>`;
      if (mine.reason === 'valid' && a) pinned += `<div class="arow mine">${yp}<div class="who"><b>${esc(a.name)}</b><span>${esc(a.context)}</span></div>${chip}</div>`;
      else {
        const what = mine.reason === 'timeout' ? 'Time ran out' : mine.reason === 'empty' ? 'No call' : mine.name ?? `“${mine.typed.trim()}”`;
        const why = mine.reason === 'not_valid_answer' ? 'Not a valid answer' : mine.reason === 'no_match' ? 'No match' : 'No gain';
        pinned += `<div class="arow mine">${yp}<div class="who"><b>${esc(what)}</b><span>${why}</span></div>${chip}</div>`;
      }
    }
    const ykb = answerById(p, p.ykb_kid);
    if (ykb) pinned += `<div class="arow ykb"><span class="tag" style="background:#e0a800;color:var(--ink);border:2px solid var(--ink)">YKB KID</span><div class="who"><b>${esc(ykb.name)}</b><span>${esc(ykb.context)}</span></div><span class="tag" style="color:var(--muted);font-size:13px">+100</span></div>`;
  }
  const list = p.answers.filter(hit);
  if (!list.length) return (pinned ? `<div class="pinned">${pinned}</div>` : '') + `<p class="empty">No answers match “${esc(answersQuery)}”.</p>`;
  const byName = (a: Answer, b: Answer) => a.name.localeCompare(b.name);
  let rows = '';
  if (answersSort === 'az') {
    rows = list.slice().sort(byName).map((a) => aRow(a, '', `<span class="chipdot" style="background:${TIERS[a.tier].color}" title="${esc(a.tier)}"></span>`)).join('');
  } else {
    for (const k of GROUP_ORDER) {
      const grp = list.filter((a) => a.tier === k).sort((a, b) => b.r - a.r || byName(a, b));
      if (!grp.length) continue;
      const t = TIERS[k];
      rows += `<div class="ghdr" style="background:${t.color};color:${t.ink}"><span>${t.short} · +${t.points}</span><span>${grp.length}</span></div>` + grp.map((a) => aRow(a)).join('');
    }
  }
  return (pinned ? `<div class="pinned">${pinned}</div>` : '') + rows;
}

// ---------------------------------------------------------------- routing / boot

function render() {
  if (!day) return;
  const g = game();
  view = location.hash === '#answers' && g.phase === 'done' ? 'answers' : 'game';
  if (view === 'answers') return answersScreen();
  if (g.phase === 'intro') return introScreen();
  if (g.phase === 'play') {
    if (g.deadline !== null && g.deadline <= now()) {
      // timer ran out while the page was closed
      g.phase = 'play';
      return record(timeoutRec());
    }
    return playScreen();
  }
  if (g.phase === 'result') return resultScreen();
  return recapScreen();
}

window.addEventListener('hashchange', () => { if (day) render(); });

document.addEventListener('keydown', (e) => {
  if (!day || view !== 'game') return;
  const g = game();
  if (e.key === 'Escape' && overlay) { e.preventDefault(); closeOverlay(overlay.kind === 'confirm'); return; }
  if (g.phase === 'result' && (e.key === 'Enter' || e.key === ' ') && !(e.target instanceof HTMLButtonElement)) { e.preventDefault(); advance(); }
});

// Day rollover: when the ET date changes, reload into the new drive unless mid-play.
let rolloverTimer = 0;
function scheduleRollover() {
  clearTimeout(rolloverTimer);
  rolloverTimer = window.setTimeout(function check() {
    const g = store().game;
    if (g && (g.phase === 'play' || g.phase === 'result')) { rolloverTimer = window.setTimeout(check, 30000); return; }
    boot();
  }, msUntilMidnightET() + 1500);
}
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState !== 'visible' || !schedule) return;
  const g = store().game;
  const today = todayET();
  const entry = schedule.drives.find((d) => d.date === today);
  if ((entry?.drive ?? 0) !== driveNo && !(g && (g.phase === 'play' || g.phase === 'result'))) boot();
  else if (g?.phase === 'play') updateTimer();
});

function fitWidth() {
  const w = document.documentElement.clientWidth;
  document.documentElement.style.setProperty('--fs', w < 378 ? String((w - 12) / 366) : '1');
}
window.addEventListener('resize', fitWidth);
window.matchMedia('(min-width: 1100px)').addEventListener('change', () => {
  if (!day) return;
  if (game().phase === 'play') {
    // The play screen's DOM order differs between phone and desktop: rebuild it, keeping what's typed.
    if (overlay || view !== 'game') return;
    const typed = inputEl()?.value ?? '';
    playScreen();
    const input = inputEl(); if (input) input.value = typed;
    return;
  }
  render();
});

async function boot() {
  stopTimer();
  preloadSound();
  fitWidth();
  const params = new URLSearchParams(location.search);
  if (import.meta.env.DEV) {
    const t = params.get('today'), n = params.get('now');
    if (n) setMockNow(new Date(n));
    else if (t) setMockNow(new Date(`${t}T12:00:00-05:00`));
    if (params.has('reset')) {
      try { localStorage.removeItem('griddion:v1'); } catch {}
      params.delete('reset');
      history.replaceState(null, '', `${location.pathname}${params.size ? `?${params}` : ''}${location.hash}`);
    }
  }
  load();
  try {
    schedule ??= await loadSchedule();
  } catch (e) {
    console.error(e);
    return messageScreen('TECHNICAL TIMEOUT', "COULDN'T LOAD THE DRIVE", 'Something went wrong loading today’s drive. Check your connection and try again.', { button: 'TRY AGAIN', onButton: () => location.reload() });
  }
  const today = todayET();
  scheduleRollover();
  if (today < schedule.launch_date) return countdownScreen(schedule.launch_date);
  let entry = schedule.drives.find((d) => d.date === today);
  if (!entry) {
    // A stale schedule.json (CDN or browser cache) can miss a drive that was just deployed: refetch once, bypassing caches.
    try { schedule = await loadSchedule(true); entry = schedule.drives.find((d) => d.date === today); } catch (e) { console.warn(e); }
  }
  if (!entry) {
    day = null;
    return messageScreen('NO DRIVE TODAY', 'CHECK BACK TOMORROW', 'The offense is off today. A new drive kicks off at midnight Eastern.');
  }
  try {
    try {
      day = await loadDay(entry.file);
    } catch (e) {
      console.warn(e, '- retrying without cache');
      day = await loadDay(entry.file, true);
    }
  } catch (e) {
    console.error(e);
    day = null;
    if (e instanceof HttpError && e.status === 404) return messageScreen('NO DRIVE TODAY', 'CHECK BACK TOMORROW', 'The offense is off today. A new drive kicks off at midnight Eastern.');
    return messageScreen('TECHNICAL TIMEOUT', "COULDN'T LOAD THE DRIVE", 'Something went wrong loading today’s drive. Check your connection and try again.', { button: 'TRY AGAIN', onButton: () => location.reload() });
  }
  driveNo = entry.drive;
  const s = store();
  if (!s.game || s.game.drive !== driveNo) {
    s.game = { drive: driveNo, plays: [], phase: 'intro', deadline: null, counted: false };
    save();
  }
  if (s.game.phase === 'done') recordFinish(driveNo, driveState(s.game.plays).tdPlay !== null, prevDrive(driveNo)); // no-op if already counted
  loadMatchData(); // start the big download while the intro shows
  render();
}

boot();
