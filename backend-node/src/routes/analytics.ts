// Port of api.py's cross-job analytics + team routes: lines 726-733 and
// 797-810. Both /team/* routes are admin-only, matching Python's
// Depends(require_role("admin")).
import type { FastifyInstance } from "fastify";
import * as storage from "../db/storage.js";
import { requireRole } from "../lib/authMiddleware.js";

export async function registerAnalyticsRoutes(app: FastifyInstance) {
  app.get("/analytics/overview", async (_request, reply) => {
    reply.send(await storage.analyticsOverview());
  });

  app.get("/analytics/attention", async (_request, reply) => {
    reply.send(await storage.attentionNeeded());
  });

  app.get("/team/usage", { preHandler: requireRole("admin") }, async (_request, reply) => {
    reply.send(await storage.teamUsage());
  });

  app.get("/team/velocity", { preHandler: requireRole("admin") }, async (_request, reply) => {
    reply.send(await storage.velocityReport());
  });
}
