/**
 * POST /feedback (spec §9). Kept out of index.ts: a Worker's entry module may only export handlers.
 *
 *   POST /feedback   { drive, rating 1–5, message? (≤ 500 chars), device "mobile"|"desktop" }
 *                    -> 201 {"ok":true}
 *
 * The answer-logging routes from §9 (POST /log, GET /stats/<prompt_id>) belong here too.
 * Privacy: nothing identifying is stored. The rate limiter is keyed on a hash of the client IP,
 * counted at the edge and never written to D1.
 */

export interface Env {
  DB: D1Database;
  FEEDBACK_LIMITER?: RateLimit;   // absent in unit tests / misconfigured envs: limiter is skipped
  LAUNCH_DATE: string;            // "YYYY-MM-DD", Drive #1
  ALLOWED_ORIGINS: string;        // comma-separated; a request with another Origin is refused
}

export const MAX_BODY_BYTES = 2048;
export const MAX_MESSAGE = 500;
const KEYS = new Set(["drive", "rating", "message", "device"]);

export interface Feedback { drive: number; rating: number; message: string | null; device: "mobile" | "desktop" }

export const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), {
    status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...headers },
  });

/** Drive number "today" in America/New_York (spec §9: rollover at 00:00 ET). */
export function currentDrive(launch: string, now: Date = new Date()): number {
  const et = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" })
    .format(now);                                   // "YYYY-MM-DD"
  const days = (Date.parse(et + "T00:00:00Z") - Date.parse(launch + "T00:00:00Z")) / 86_400_000;
  return Math.round(days) + 1;
}

/** -> a clean Feedback, or an error string. Unknown keys, wrong types and out-of-range values are refused. */
export function validateFeedback(body: unknown, maxDrive: number): Feedback | string {
  if (typeof body !== "object" || body === null || Array.isArray(body)) return "body must be a JSON object";
  const b = body as Record<string, unknown>;
  const extra = Object.keys(b).filter((k) => !KEYS.has(k));
  if (extra.length) return `unknown field(s): ${extra.join(", ")}`;
  const { drive, rating, message, device } = b;
  if (!Number.isInteger(drive) || (drive as number) < 1 || (drive as number) > maxDrive) return `drive must be an integer from 1 to ${maxDrive}`;
  if (!Number.isInteger(rating) || (rating as number) < 1 || (rating as number) > 5) return "rating must be an integer from 1 to 5";
  if (device !== "mobile" && device !== "desktop") return 'device must be "mobile" or "desktop"';
  let msg: string | null = null;
  if (message !== undefined && message !== null) {
    if (typeof message !== "string") return "message must be a string";
    // drop control characters except newline/tab; normalize; trim
    msg = message.normalize("NFC").replace(/[\u0000-\u0008\u000B-\u001F\u007F]/g, "").trim();
    if ([...msg].length > MAX_MESSAGE) return `message must be at most ${MAX_MESSAGE} characters`;
    if (!msg) msg = null;
  }
  return { drive: drive as number, rating: rating as number, message: msg, device };
}

async function clientKey(req: Request): Promise<string> {
  const ip = req.headers.get("cf-connecting-ip") ?? "unknown";
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode("griddion-rl:" + ip));
  return [...new Uint8Array(digest).slice(0, 12)].map((x) => x.toString(16).padStart(2, "0")).join("");
}

export async function handleFeedback(req: Request, env: Env, now: Date = new Date()): Promise<Response> {
  if (req.method !== "POST") return json(405, { error: "method not allowed" }, { allow: "POST" });

  const origin = req.headers.get("origin");
  const allowed = env.ALLOWED_ORIGINS.split(",").map((s) => s.trim()).filter(Boolean);
  if (origin && !allowed.includes(origin)) return json(403, { error: "origin not allowed" });

  if (env.FEEDBACK_LIMITER) {
    const { success } = await env.FEEDBACK_LIMITER.limit({ key: await clientKey(req) });
    if (!success) return json(429, { error: "too many requests" }, { "retry-after": "60" });
  }

  if (!(req.headers.get("content-type") ?? "").toLowerCase().startsWith("application/json"))
    return json(415, { error: "content-type must be application/json" });
  const declared = Number(req.headers.get("content-length") ?? "0");
  if (declared > MAX_BODY_BYTES) return json(413, { error: "payload too large" });
  const raw = await req.text();
  if (new TextEncoder().encode(raw).length > MAX_BODY_BYTES) return json(413, { error: "payload too large" });

  let body: unknown;
  try { body = JSON.parse(raw); } catch { return json(400, { error: "invalid JSON" }); }
  // tomorrow's drive is allowed: a player can finish just after midnight ET on a stale page
  const fb = validateFeedback(body, currentDrive(env.LAUNCH_DATE, now) + 1);
  if (typeof fb === "string") return json(400, { error: fb });

  await env.DB.prepare("INSERT INTO feedback (created_at, drive, rating, message, device) VALUES (?, ?, ?, ?, ?)")
    .bind(now.toISOString(), fb.drive, fb.rating, fb.message, fb.device).run();
  return json(201, { ok: true });
}

