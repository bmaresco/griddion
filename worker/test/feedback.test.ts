import { describe, expect, it } from "vitest";
import worker from "../src/index";
import { currentDrive, handleFeedback, validateFeedback, type Env } from "../src/feedback";

function fakeEnv(limitOk = true) {
  const rows: unknown[][] = [];
  const keys: string[] = [];
  const env = {
    DB: { prepare: (_sql: string) => ({ bind: (...v: unknown[]) => ({ run: async () => { rows.push(v); return {}; } }) }) },
    FEEDBACK_LIMITER: { limit: async ({ key }: { key: string }) => { keys.push(key); return { success: limitOk }; } },
    LAUNCH_DATE: "2026-11-09",
    ALLOWED_ORIGINS: "https://griddion.io",
  } as unknown as Env;
  return { env, rows, keys };
}

const NOW = new Date("2026-11-11T15:00:00Z");   // Drive #3
const post = (body: unknown, headers: Record<string, string> = {}) =>
  new Request("https://griddion.io/feedback", {
    method: "POST",
    headers: { "content-type": "application/json", origin: "https://griddion.io", "cf-connecting-ip": "203.0.113.7", ...headers },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
const good = { drive: 3, rating: 4, message: "  Fun! Hard P7  ", device: "mobile" };

describe("POST /feedback", () => {
  it("stores a valid payload with a server timestamp and nothing else", async () => {
    const { env, rows } = fakeEnv();
    const r = await handleFeedback(post(good), env, NOW);
    expect(r.status).toBe(201);
    expect(await r.json()).toEqual({ ok: true });
    expect(rows).toEqual([["2026-11-11T15:00:00.000Z", 3, 4, "Fun! Hard P7", "mobile"]]);
    expect(JSON.stringify(rows)).not.toContain("203.0.113.7");
  });

  it("message is optional; blank becomes null", async () => {
    const { env, rows } = fakeEnv();
    expect((await handleFeedback(post({ drive: 1, rating: 5, device: "desktop" }), env, NOW)).status).toBe(201);
    expect((await handleFeedback(post({ ...good, message: "   " }), env, NOW)).status).toBe(201);
    expect(rows.map((r) => r[3])).toEqual([null, null]);
  });

  it.each([
    [{ ...good, rating: 0 }, "rating"], [{ ...good, rating: 6 }, "rating"], [{ ...good, rating: 4.5 }, "rating"],
    [{ ...good, rating: "5" }, "rating"], [{ ...good, drive: 0 }, "drive"], [{ ...good, drive: 5 }, "drive"],
    [{ ...good, device: "tablet" }, "device"], [{ ...good, message: 42 }, "message"],
    [{ ...good, message: "x".repeat(501) }, "message"], [{ ...good, email: "a@b.c" }, "unknown"],
    [[1, 2], "object"], ["{not json", "JSON"],
  ])("rejects %j", async (body, err) => {
    const { env, rows } = fakeEnv();
    const r = await handleFeedback(post(body), env, NOW);
    expect(r.status).toBe(400);
    expect((await r.json() as { error: string }).error).toContain(err);
    expect(rows).toHaveLength(0);
  });

  it("500 characters is fine (counted as characters, not bytes)", async () => {
    const { env } = fakeEnv();
    expect((await handleFeedback(post({ ...good, message: "é".repeat(500) }), env, NOW)).status).toBe(201);
  });

  it("tomorrow's drive is allowed (stale page after midnight ET), later ones are not", async () => {
    const { env } = fakeEnv();
    expect((await handleFeedback(post({ ...good, drive: 4 }), env, NOW)).status).toBe(201);
    expect((await handleFeedback(post({ ...good, drive: 5 }), env, NOW)).status).toBe(400);
  });

  it("rate limits per client on a hashed key, never the raw IP", async () => {
    const { env, rows, keys } = fakeEnv(false);
    const r = await handleFeedback(post(good), env, NOW);
    expect(r.status).toBe(429);
    expect(r.headers.get("retry-after")).toBe("60");
    expect(rows).toHaveLength(0);
    expect(keys[0]).toMatch(/^[0-9a-f]{24}$/);
    expect(keys[0]).not.toContain("203");
  });

  it("refuses other origins, methods, content types and oversized bodies", async () => {
    const { env } = fakeEnv();
    expect((await handleFeedback(post(good, { origin: "https://evil.example" }), env, NOW)).status).toBe(403);
    expect((await handleFeedback(new Request("https://griddion.io/feedback"), env, NOW)).status).toBe(405);
    expect((await handleFeedback(post(good, { "content-type": "text/plain" }), env, NOW)).status).toBe(415);
    expect((await handleFeedback(post({ ...good, message: "x".repeat(3000) }), env, NOW)).status).toBe(413);
  });

  it("routes only /feedback", async () => {
    const { env } = fakeEnv();
    expect((await worker.fetch(new Request("https://griddion.io/nope"), env)).status).toBe(404);
  });
});

describe("helpers", () => {
  it("drive number rolls over at midnight ET", () => {
    expect(currentDrive("2026-11-09", new Date("2026-11-09T05:00:00Z"))).toBe(1);   // 00:00 ET
    expect(currentDrive("2026-11-09", new Date("2026-11-10T04:59:00Z"))).toBe(1);   // 23:59 ET
    expect(currentDrive("2026-11-09", new Date("2026-11-10T05:00:00Z"))).toBe(2);
  });
  it("strips control characters", () => {
    expect(validateFeedback({ drive: 1, rating: 3, device: "mobile", message: "a\u0000b\nc" }, 10))
      .toEqual({ drive: 1, rating: 3, device: "mobile", message: "ab\nc" });
  });
});
