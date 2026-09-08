// Port of api.py's outreach settings + due-followups routes (lines
// 743-765). The actual SMTP send routes (POST .../outreach/send and
// .../followup/send) are deferred to Phase 7 alongside notifications.py's
// port -- see docs/migration.md. Read-only/config routes here are fully
// real, not stubbed.
import type { FastifyInstance } from "fastify";
import { z } from "zod";
import * as storage from "../db/storage.js";
import { requireRole } from "../lib/authMiddleware.js";

const WorkspaceSettingsRequest = z.object({
  followup_template: z.string().nullable().optional(),
  auto_send_followups: z.boolean().nullable().optional(),
});

export async function registerOutreachRoutes(app: FastifyInstance) {
  app.get("/outreach/settings", async (_request, reply) => {
    reply.send(await storage.getWorkspaceSettings());
  });

  app.put("/outreach/settings", { preHandler: requireRole("admin") }, async (request, reply) => {
    const body = WorkspaceSettingsRequest.parse(request.body);
    reply.send(await storage.setWorkspaceSettings({
      followupTemplate: body.followup_template ?? null, autoSendFollowups: body.auto_send_followups ?? null,
    }));
  });

  app.get("/outreach/followups/due", async (_request, reply) => {
    reply.send(await storage.dueFollowups());
  });
}
