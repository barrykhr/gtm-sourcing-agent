// Port of api.py's integrations routes (lines 1409-1479): account-level
// connection status (honest "not_connected" -- no OAuth flow exists yet,
// same as Python) plus the per-job outbound webhook config/test, which is
// a real HTTP POST via webhooks.ts, not simulated.
import type { FastifyInstance } from "fastify";
import { z } from "zod";
import * as storage from "../db/storage.js";
import { sendWebhook } from "../webhooks.js";
import { logAction } from "../lib/routeHelpers.js";

const WebhookConfigRequest = z.object({ webhook_url: z.string().default("") });

const INTEGRATION_PROVIDERS: Record<string, { label: string; envVar: string; capabilities: string }> = {
  google_workspace: {
    label: "Google Workspace",
    envVar: "GOOGLE_OAUTH_CLIENT_ID",
    capabilities: "Gmail, Google Calendar, Google Meet — schedule interviews and create Meet links from a candidate's record.",
  },
  calendly: {
    label: "Calendly",
    envVar: "CALENDLY_CLIENT_ID",
    capabilities: "Send a candidate a scheduling link for a screening, hiring-manager, technical, or final interview.",
  },
  telephony: {
    label: "Phone / telephony",
    envVar: "TELEPHONY_PROVIDER_API_KEY",
    capabilities: "Place outbound calls, record them, and receive an automatic transcript — today's Call button is a device (tel:) handoff, not a connected line.",
  },
};

export async function registerIntegrationRoutes(app: FastifyInstance) {
  app.get("/integrations/status", async (_request, reply) => {
    reply.send(
      Object.entries(INTEGRATION_PROVIDERS).map(([provider, meta]) => ({
        provider, label: meta.label, status: "not_connected",
        environment_configured: Boolean(process.env[meta.envVar]),
        capabilities: meta.capabilities,
      }))
    );
  });

  app.get("/jobs/:roleId/integrations", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    if (!(await storage.jobExists(roleId))) {
      reply.code(404).send({ detail: `job '${roleId}' not found` });
      return;
    }
    const state = await storage.loadRole(roleId);
    reply.send({ webhook_url: (state.integrations ?? {}).webhook_url ?? "" });
  });

  app.post("/jobs/:roleId/integrations/webhook", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    if (!(await storage.jobExists(roleId))) {
      reply.code(404).send({ detail: `job '${roleId}' not found` });
      return;
    }
    const body = WebhookConfigRequest.parse(request.body);
    await storage.mergeSection(roleId, "integrations", { webhook_url: body.webhook_url });
    await logAction(request, roleId, "configured webhook", { detail: body.webhook_url });
    reply.send({ webhook_url: body.webhook_url });
  });

  app.post("/jobs/:roleId/integrations/webhook/test", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    if (!(await storage.jobExists(roleId))) {
      reply.code(404).send({ detail: `job '${roleId}' not found` });
      return;
    }
    const state = await storage.loadRole(roleId);
    const webhookUrl = (state.integrations ?? {}).webhook_url;
    if (!webhookUrl) {
      reply.code(400).send({ detail: "no webhook URL configured for this job yet" });
      return;
    }
    const result = await sendWebhook(webhookUrl, "webhook.test", { role_id: roleId });
    await logAction(request, roleId, "sent test webhook", { detail: result.detail });
    reply.send(result);
  });
}
