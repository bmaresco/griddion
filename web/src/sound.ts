// 8-bit sound effects, synthesized on the fly with ZzFX (MIT, Frank Force): no audio files.
// ZzFX builds its AudioContext when the module loads, so it's imported lazily and guarded: a browser
// without Web Audio just stays silent. Browsers start that context suspended; unlock() resumes it
// inside the first tap. Muting is remembered per device; muted means nothing plays at all.
import type { Tier } from './game';

type Params = (number | undefined)[];
interface ZzfxModule { zzfx: (...p: Params) => unknown; ZZFX: { volume: number; audioContext: AudioContext } }

const MUTE_KEY = 'griddion:sound';
let mod: ZzfxModule | null = null;
let unlocked = false;
let muted = readMuted();

function readMuted(): boolean {
  try { return localStorage.getItem(MUTE_KEY) === 'off'; } catch { return false; }
}

/** Start loading the synth early so the first tap can unlock audio synchronously. */
export function preloadSound(): void {
  if (mod) return;
  import('zzfx').then((m) => { mod = m as unknown as ZzfxModule; mod.ZZFX.volume = 0.22; }).catch(() => { /* no Web Audio */ });
}

/** Call from inside a user gesture (tap / key). Safe to call repeatedly. */
export function unlockSound(): void {
  if (unlocked || !mod) return;
  try {
    const ctx = mod.ZZFX.audioContext;
    if (ctx.state !== 'running') void ctx.resume();
    // iOS only unlocks after something actually plays inside the gesture: a 1-sample silent buffer.
    const src = ctx.createBufferSource();
    src.buffer = ctx.createBuffer(1, 1, 22050);
    src.connect(ctx.destination);
    src.start(0);
    unlocked = true;
  } catch { /* ignore */ }
}

export const isMuted = () => muted;
export function setMuted(m: boolean): void {
  muted = m;
  try { localStorage.setItem(MUTE_KEY, m ? 'off' : 'on'); } catch { /* private mode */ }
}

function fx(...p: Params): void {
  if (muted || !unlocked || !mod) return;
  try { if (mod.ZZFX.audioContext.state === 'running') mod.zzfx(...p); } catch { /* ignore */ }
}
const later = (ms: number, f: () => void) => window.setTimeout(f, ms);

// ZzFX params: volume, randomness, frequency, attack, sustain, release, shape, shapeCurve, slide,
// deltaSlide, pitchJump, pitchJumpTime, repeatTime, noise, modulation, bitCrush, delay,
// sustainVolume, decay, tremolo, filter (filter: + high-pass, − low-pass). Shapes: 0 sin, 1 tri,
// 2 saw, 3 tan, 4 noise, 5 square.

/** Crowd noise: filtered noise with a swell. size 0..1 scales loudness and length. */
function crowd(size: number): void {
  const vol = 0.25 + 0.55 * size;
  const len = 0.25 + 0.9 * size;
  fx(vol, 0.1, 380 + 300 * size, 0.08 + 0.12 * size, len, 0.35 + 0.4 * size, 4, 1, 0, 0, 0, 0, 0.11, 0, 0, 0, 0, 0.75, 0.06, 0.25, -1500 - 1200 * size);
}

/** Square-wave arpeggio. */
function fanfare(notes: number[], step: number, vol = 0.35): void {
  notes.forEach((f, k) => later(k * step, () => fx(vol, 0, f, 0.005, step / 1000 * (k === notes.length - 1 ? 2.2 : 0.7), 0.08, 5, 0.5, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.8, 0.02)));
}

const C5 = 523.25, E5 = 659.25, G5 = 783.99, C6 = 1046.5;

export const sfx = {
  /** Ref whistle when the ball is snapped. */
  whistle: () => fx(0.32, 0, 2350, 0.01, 0.16, 0.05, 0, 1, 0, 0, 0, 0, 0.03, 0, 0, 0, 0, 0.9, 0, 0.35),
  /** Crowd reaction scaled by tier. */
  tier: (t: Tier) => {
    switch (t) {
      case 'Incomplete': return fx(0.35, 0.1, 300, 0.05, 0.25, 0.35, 4, 1, -0.6, 0, 0, 0, 0, 0, 0, 0, 0, 0.7, 0.05, 0, -900); // aww
      case 'Starter': return crowd(0.1);
      case 'Botched Trick Play': return crowd(0.15);
      case 'Backup': return crowd(0.35);
      case 'Hidden Gem': return crowd(0.55);
      case 'Sleeper Pick': return crowd(0.75);
      case 'YKB Kid': crowd(1); return fanfare([C5, E5, G5], 90, 0.25);
    }
  },
  /** "Not on the board". */
  buzzer: () => fx(0.28, 0, 110, 0.01, 0.22, 0.04, 2, 1, 0, 0, 0, 0, 0, 0, 0, 0.08, 0, 1),
  /** Last-5-seconds tick. */
  tick: () => fx(0.22, 0, 1700, 0, 0.005, 0.03, 0, 1),
  touchdown: () => { fanfare([C5, E5, G5, C6, G5, C6], 120); later(150, () => crowd(1)); },
  /** Crowd groan: low noise sliding down. */
  stalled: () => fx(0.45, 0.1, 340, 0.08, 0.5, 0.6, 4, 1, -0.4, 0, 0, 0, 0, 0, 0, 0, 0, 0.7, 0.05, 0, -800),
};
