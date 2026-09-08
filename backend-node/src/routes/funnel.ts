// Port of api.py's funnel routes (lines 1384-1399, 1482-1495) --
// deterministic arithmetic, no LLM call, so these ship in Phase 4 rather
// than waiting on the AI stage port.
import type { FastifyInstance } from "fastify";
import { z } from "zod";
import * as funnelStage from "../stages/funnel.js";
import { logAction, runStage } from "../lib/routeHelpers.js";

const FunnelUpdateRequest = z.object({
  stage: z.string(),
  note: z.string().default(""),
  scheduled_at: z.string().nullable().optional(),
});

const ForecastRequest = z.object({
  hires: z.number().int(),
  weeks: z.number().int(),
  source: z.enum(["historical", "market_default"]).default("market_default"),
  screen_to_hm: z.number().default(0.5),
  hm_to_final: z.number().default(0.5),
  final_to_offer: z.number().default(0.5),
  offer_to_accept: z.number().default(0.8),
  contacted_to_screen: z.number().default(0.3),
  sourced_to_contacted: z.number().default(0.3),
});

export async function registerFunnelRoutes(app: FastifyInstance) {
  app.post("/jobs/:roleId/funnel/:candidateId", async (request, reply) => {
    const { roleId, candidateId } = request.params as { roleId: string; candidateId: string };
    const body = FunnelUpdateRequest.parse(request.body);
    const stage = body.stage.toUpperCase();
    const result = await runStage(() => funnelStage.update(roleId, candidateId, stage, {
      note: body.note, scheduledAt: body.scheduled_at ?? null,
    }));
    const detail = stage + (body.scheduled_at ? ` (scheduled ${body.scheduled_at})` : "");
    await logAction(request, roleId, "moved pipeline stage", { detail, candidateId });
    reply.send(result);
  });

  app.get("/jobs/:roleId/funnel/report", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    reply.send(await funnelStage.report(roleId));
  });

  app.post("/funnel/forecast", async (request, reply) => {
    const body = ForecastRequest.parse(request.body);
    const assumptions: funnelStage.ForecastAssumptions = {
      source: body.source,
      screen_to_hm_interview: body.screen_to_hm,
      hm_interview_to_final: body.hm_to_final,
      final_to_offer: body.final_to_offer,
      offer_to_accept: body.offer_to_accept,
      contacted_to_screen: body.contacted_to_screen,
      sourced_to_contacted: body.sourced_to_contacted,
    };
    reply.send(funnelStage.forecast(body.hires, body.weeks, assumptions));
  });
}
