// Port of api.py's global candidate roster + search routes (Phase 2 /
// Phase 10 in the Python history): lines 699-717.
import type { FastifyInstance } from "fastify";
import * as storage from "../db/storage.js";

export async function registerCandidateRoutes(app: FastifyInstance) {
  app.get("/candidates", async (_request, reply) => {
    reply.send(await storage.listCanonicalCandidates());
  });

  app.get("/candidates/:candidateId", async (request, reply) => {
    const { candidateId } = request.params as { candidateId: string };
    const detail = await storage.getCanonicalCandidate(candidateId);
    if (detail === null) {
      reply.code(404).send({ detail: `candidate '${candidateId}' not found` });
      return;
    }
    reply.send(detail);
  });

  app.get("/search", async (request, reply) => {
    const { q } = request.query as { q?: string };
    reply.send(await storage.search(q ?? ""));
  });
}
