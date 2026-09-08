// Port of api.py's AuthMiddleware (BaseHTTPMiddleware) + require_role
// dependency. _PUBLIC_PATHS is copied exactly from api.py's set — every
// path an unauthenticated request may reach, verbatim.
import type { FastifyReply, FastifyRequest } from "fastify";
import * as auth from "../auth/service.js";
import { SESSION_COOKIE_NAME } from "../auth/service.js";

export const PUBLIC_PATHS = new Set([
  "/",
  "/health",
  "/auth/signup",
  "/auth/login",
  "/auth/status",
  "/auth/google",
  "/auth/forgot-password",
  "/auth/reset-password",
]);

export function isPublicPath(path: string): boolean {
  return PUBLIC_PATHS.has(path) || path.startsWith("/public/");
}

export async function authHook(request: FastifyRequest, reply: FastifyReply) {
  const pathname = request.url.split("?")[0]!;
  if (request.method === "OPTIONS" || isPublicPath(pathname)) {
    return;
  }
  const token = request.cookies[SESSION_COOKIE_NAME];
  const user = await auth.getUserFromSession(token);
  if (!user) {
    reply.code(401).send({ detail: "not authenticated" });
    return reply;
  }
  (request as any).user = user;
}

export function requireRole(...allowedRoles: string[]) {
  return async (request: FastifyRequest, reply: FastifyReply) => {
    const user = (request as any).user;
    if (!user || !allowedRoles.includes(user.role)) {
      reply.code(403).send({ detail: `requires one of role(s): ${allowedRoles.join(", ")}` });
      return reply;
    }
  };
}
