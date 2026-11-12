// Feedback popup (design/Feedback.dc.html): a wristband card over the dimmed recap.
// Shown ~2 s after the recap, after the first completed drive, then at most once every 7 days,
// and never again once the player has sent feedback.
import { now } from './clock';

/** Where feedback is POSTed: the Worker's POST /feedback (same origin). Body is exactly
 *  { drive, rating 1–5, message ≤ 500, device } — unknown fields are rejected. 201 = ok, 400 = bad
 *  payload, 429 = over 5/min. Built but not deployed yet: until then FEEDBACK_STUB logs instead. */
export const FEEDBACK_URL = '/feedback';
const FEEDBACK_STUB = true;

const KEY = 'griddion:feedback';
const WEEK_MS = 7 * 24 * 60 * 60 * 1000;
const WORDS = ['Tap a football', 'Fumble', 'Punt', 'First down', 'Big gain', 'Touchdown!'];

interface FbState { submitted?: boolean; lastShown?: number }
function readState(): FbState {
  try { return JSON.parse(localStorage.getItem(KEY) || '{}') as FbState; } catch { return {}; }
}
function writeState(s: FbState): void {
  try { localStorage.setItem(KEY, JSON.stringify(s)); } catch { /* private mode */ }
}

/** completedDrives: finished drives so far (W + L). */
export function shouldShowFeedback(completedDrives: number): boolean {
  const s = readState();
  if (s.submitted || completedDrives < 1) return false;
  return !s.lastShown || now() - s.lastShown >= WEEK_MS;
}

// 11×7 pixel football at 3 px, as box-shadows (same sprite as the design).
function ballSprite(on: boolean): string {
  const map = on
    ? ['...BBBBB...', '.BBBBBBBBB.', 'BBBWBWBWBBB', 'BBWWWWWWWBB', 'BBBWBWBWBBB', '.BBBBBBBBB.', '...BBBBB...']
    : ['...OOOOO...', '.OO.....OO.', 'O..L.L.L..O', 'O.LLLLLLL.O', 'O..L.L.L..O', '.OO.....OO.', '...OOOOO...'];
  const pal: Record<string, string> = on ? { B: '#8a4f22', W: '#f4f4ee' } : { O: '#1d1a14', L: '#b9ad8c' };
  const sh: string[] = [];
  map.forEach((row, r) => [...row].forEach((k, c) => { if (pal[k]) sh.push(`${c * 3 + 3}px ${r * 3 + 3}px 0 0 ${pal[k]}`); }));
  return `<span class="fb-ball-px" style="box-shadow:${sh.join(',')}"></span>`;
}

let openEl: HTMLElement | null = null;
let lastFocus: Element | null = null;
let closeTimer = 0;

export const feedbackOpen = () => openEl !== null;

export function closeFeedback(): void {
  if (!openEl) return;
  clearTimeout(closeTimer);
  openEl.remove();
  openEl = null;
  document.removeEventListener('keydown', onKey, true);
  if (lastFocus instanceof HTMLElement && document.contains(lastFocus)) lastFocus.focus({ preventScroll: true });
}

function onKey(e: KeyboardEvent): void {
  if (!openEl) return;
  if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeFeedback(); return; }
  if (e.key === 'Tab') { // keep focus inside the dialog
    const f = [...openEl.querySelectorAll<HTMLElement>('button:not([disabled]), textarea, [tabindex="0"]')].filter((x) => x.offsetParent !== null);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
}

export function showFeedback(drive: number, device: 'mobile' | 'desktop'): void {
  if (openEl) return;
  writeState({ ...readState(), lastShown: now() });
  lastFocus = document.activeElement;
  let rating = 0;

  const el = document.createElement('div');
  el.className = 'fb-back';
  el.innerHTML = `<div class="fb" role="dialog" aria-modal="true" aria-labelledby="fb-title"><div class="wb-dash"><div class="fb-paper">
      <div class="fb-head"><h2 id="fb-title" class="silk">HOW ARE YOU LIKING GRIDDION?</h2><button type="button" class="fb-x" aria-label="Close">✕</button></div>
      <div class="fb-body">
        <div class="fb-balls" role="radiogroup" aria-label="Rating">${[1, 2, 3, 4, 5].map((n) =>
          `<button type="button" role="radio" class="fb-ball" data-n="${n}" aria-checked="false" aria-label="${n} of 5" tabindex="${n === 1 ? 0 : -1}"><span class="fb-ball-box" aria-hidden="true">${ballSprite(false)}</span></button>`).join('')}</div>
        <span class="fb-word" aria-live="polite">${WORDS[0].toUpperCase()}</span>
        <label for="fb-msg" class="fb-label">FEEDBACK <span>(optional)</span></label>
        <textarea id="fb-msg" rows="4" maxlength="500" placeholder="What should we add or fix?"></textarea>
        <p class="fb-err" role="alert"></p>
        <button type="button" class="fb-send silk" disabled>SEND</button>
        <button type="button" class="fb-no">No thanks</button>
      </div>
      <div class="fb-done" hidden><span class="silk">THANKS, COACH!</span><span>Your call has been sent to the booth.</span></div>
    </div></div></div>`;
  document.body.appendChild(el);
  openEl = el;
  document.addEventListener('keydown', onKey, true);

  const balls = [...el.querySelectorAll<HTMLButtonElement>('.fb-ball')];
  const send = el.querySelector<HTMLButtonElement>('.fb-send')!;
  const word = el.querySelector<HTMLElement>('.fb-word')!;
  const err = el.querySelector<HTMLElement>('.fb-err')!;
  const msg = el.querySelector<HTMLTextAreaElement>('#fb-msg')!;

  const setRating = (n: number, focus = false) => {
    rating = n;
    balls.forEach((b, k) => {
      const on = k < n;
      b.classList.toggle('sel', k + 1 === n);
      b.setAttribute('aria-checked', String(k + 1 === n));
      b.tabIndex = k + 1 === n ? 0 : -1;
      b.querySelector('.fb-ball-box')!.innerHTML = ballSprite(on);
    });
    word.textContent = WORDS[n].toUpperCase();
    send.disabled = n === 0;
    if (focus) balls[n - 1].focus();
  };
  balls.forEach((b) => {
    b.addEventListener('click', () => setRating(Number(b.dataset.n)));
    b.addEventListener('keydown', (e) => { // radio-group arrows
      const d = e.key === 'ArrowRight' || e.key === 'ArrowUp' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowDown' ? -1 : 0;
      if (!d) return;
      e.preventDefault();
      setRating(Math.min(5, Math.max(1, (rating || Number(b.dataset.n)) + (rating ? d : 0))), true);
    });
  });

  el.addEventListener('click', (e) => { if (e.target === el) closeFeedback(); }); // tap outside
  el.querySelector('.fb-x')!.addEventListener('click', closeFeedback);
  el.querySelector('.fb-no')!.addEventListener('click', closeFeedback);

  send.addEventListener('click', async () => {
    if (!rating || send.dataset.busy) return;
    send.dataset.busy = '1';
    err.textContent = '';
    const body = { drive, rating, message: msg.value.trim().slice(0, 500), device };
    try {
      if (FEEDBACK_STUB) console.info('[feedback stub] POST', FEEDBACK_URL, body);
      else {
        const res = await fetch(FEEDBACK_URL, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        if (!res.ok) throw new Error(res.status === 429 ? 'Too many calls to the booth. Try again in a minute.' : '');
      }
    } catch (e) {
      delete send.dataset.busy;
      err.textContent = (e as Error).message || 'Couldn’t reach the booth. Try again.';
      return;
    }
    writeState({ ...readState(), submitted: true });
    el.querySelector<HTMLElement>('.fb-body')!.hidden = true;
    el.querySelector<HTMLElement>('.fb-done')!.hidden = false;
    el.querySelector<HTMLElement>('.fb-x')!.focus();
    closeTimer = window.setTimeout(closeFeedback, 1500);
  });

  el.querySelector<HTMLElement>('.fb-x')!.focus({ preventScroll: true });
}
