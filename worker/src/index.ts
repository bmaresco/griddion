/**
 * Griddion API Worker (spec §9). Same origin as the game (Cloudflare Pages at griddion.io).
 *
 *   POST /feedback   { drive, rating 1–5, message? (≤ 500 chars), device "mobile"|"desktop" } -> 201 {"ok":true}
 *
 * The answer-logging routes from §9 (POST /log, GET /stats/<prompt_id>) belong here too.
 * Only the default handler may be exported from this module.
 */
import { handleFeedback, json, type Env } from "./feedback";

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const { pathname } = new URL(req.url);
    try {
      if (pathname === "/feedback") return await handleFeedback(req, env);
      return json(404, { error: "not found" });
    } catch (e) {
      console.error("unhandled", (e as Error).message);   // no request data in logs
      return json(500, { error: "server error" });
    }
  },
} satisfies ExportedHandler<Env>;
