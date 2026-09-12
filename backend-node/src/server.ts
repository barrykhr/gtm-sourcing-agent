// Port of api.py's app setup. Mirrors: CORS origin allowlist, cookie
// parsing, the AuthMiddleware hook applied to every route, and the
// health/root routes Render's platform probes hit (see api.py:519-530
// and the earlier session's fix for exactly why both need to answer
// GET+HEAD and be public).
import Fastify from "fastify";
import cors from "@fastify/cors";
import cookie from "@fastify/cookie";
import multipart from "@fastify/multipart";
import { authHook } from "./lib/authMiddleware.js";
import { registerAuthRoutes } from "./routes/auth.js";
import { registerJobRoutes } from "./routes/jobs.js";
import { registerCandidateRoutes } from "./routes/candidates.js";
import { registerAnalyticsRoutes } from "./routes/analytics.js";
import { registerOutreachRoutes } from "./routes/outreach.js";
import { registerFunnelRoutes } from "./routes/funnel.js";
import { registerJobCandidateRoutes } from "./routes/jobCandidates.js";
import { registerIntegrationRoutes } from "./routes/integrations.js";
import { registerAiStageRoutes } from "./routes/aiStages.js";
import { registerChatRoutes } from "./routes/chat.js";
import { start as startFollowupSweep } from "./followupSweep.js";

const CORS_ORIGINS = (process.env.GTM_CORS_ORIGINS ?? "http://localhost:3000")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);

export function buildServer() {
  const app = Fastify({ logger: process.env.NODE_ENV !== "test" });

  // Started here so every process that builds the app runs the sweep
  // (mirrors api.py calling followup_sweep.start() at app setup).
  startFollowupSweep();

  app.register(cors, { origin: CORS_ORIGINS, credentials: true });
  app.register(cookie);
  app.register(multipart, { attachFieldsToBody: true, limits: { fileSize: 25 * 1024 * 1024 } });

  // Many routes below have no request body at all (matching Python's
  // routes with no Pydantic `body` param) -- Fastify's default JSON
  // parser rejects an empty body outright even when the route never
  // reads it. Treat empty/whitespace-only JSON bodies as `undefined`
  // instead of a parse error, same leniency FastAPI has for a bodyless
  // route.
  app.addContentTypeParser("application/json", { parseAs: "string" }, (_req, body, done) => {
    const text = (body as string).trim();
    if (!text) {
      done(null, undefined);
      return;
    }
    try {
      done(null, JSON.parse(text));
    } catch (err) {
      done(err as Error, undefined);
    }
  });

  app.addHook("onRequest", authHook);

  app.route({
    method: ["GET", "HEAD"],
    url: "/health",
    handler: async () => ({ status: "ok" }),
  });
  app.route({
    method: ["GET", "HEAD"],
    url: "/",
    handler: async () => ({ status: "ok", service: "Talyn API (Node)" }),
  });

  app.register(registerAuthRoutes);
  app.register(registerJobRoutes);
  app.register(registerCandidateRoutes);
  app.register(registerAnalyticsRoutes);
  app.register(registerOutreachRoutes);
  app.register(registerFunnelRoutes);
  app.register(registerJobCandidateRoutes);
  app.register(registerIntegrationRoutes);
  app.register(registerAiStageRoutes);
  app.register(registerChatRoutes);

  app.setErrorHandler((error: any, request, reply) => {
    const status = error.statusCode ?? 500;
    if (error.issues) {
      // zod validation error
      reply.code(400).send({ detail: error.issues });
      return;
    }
    reply.code(status).send({ detail: error.message });
  });

  return app;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const app = buildServer();
  const port = Number(process.env.PORT ?? 8001);
  app.listen({ port, host: "0.0.0.0" }, (err) => {
    if (err) {
      app.log.error(err);
      process.exit(1);
    }
  });
}
