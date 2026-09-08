// Port of api.py's /auth/* and /users routes (lines 168-317 in the
// Python source). Request bodies below mirror api.py's Pydantic
// BaseModel classes field-for-field.
import type { FastifyInstance } from "fastify";
import { z } from "zod";
import * as auth from "../auth/service.js";
import { SESSION_COOKIE_NAME, SESSION_TTL_MS } from "../auth/service.js";
import { requireRole } from "../lib/authMiddleware.js";
import * as notifications from "../notifications.js";

const SignupRequest = z.object({
  email: z.string(),
  password: z.string(),
  signup_code: z.string().nullable().optional(),
});
const LoginRequest = z.object({ email: z.string(), password: z.string() });
const GoogleAuthRequest = z.object({ credential: z.string() });
const ForgotPasswordRequest = z.object({ email: z.string() });
const ResetPasswordRequest = z.object({ token: z.string(), new_password: z.string() });
const UserRoleRequest = z.object({ role: z.string() });
const TestEmailRequest = z.object({ to: z.string() });

const COOKIE_SECURE = (process.env.GTM_COOKIE_SECURE ?? "false").toLowerCase() === "true";
let COOKIE_SAMESITE = (process.env.GTM_COOKIE_SAMESITE ?? "lax").toLowerCase();
const cookieSecure = COOKIE_SAMESITE === "none" ? true : COOKIE_SECURE;

function setSessionCookie(reply: any, token: string) {
  reply.setCookie(SESSION_COOKIE_NAME, token, {
    path: "/",
    httpOnly: true,
    secure: cookieSecure,
    sameSite: COOKIE_SAMESITE as "lax" | "strict" | "none",
    maxAge: SESSION_TTL_MS / 1000,
  });
}

function mapAuthError(e: unknown): never {
  if (e instanceof auth.AuthError) {
    const err: any = new Error(e.message);
    err.statusCode = 400;
    throw err;
  }
  throw e;
}

// Best-effort -- see notifications.ts. Skipped entirely for the
// first-ever account (its own role is "admin"; there's no one else to
// tell yet). Never throws, never blocks the signup response on it.
async function notifyAdminsOfNewSignup(newUser: { email: string; role: string }): Promise<void> {
  if (newUser.role === "admin") return;
  try {
    const adminEmails = (await auth.listUsers()).filter((u) => u.role === "admin").map((u) => u.email);
    await notifications.notifyAdminsOfNewSignup(newUser.email, newUser.role, adminEmails);
  } catch (e) {
    console.error(`failed to notify admins of new signup: ${newUser.email}`, e);
  }
}

// Where the "forgot password" email's reset link points -- the deployed
// frontend's own URL, since the backend has no page of its own for a
// user to land on. Defaults to the local dev frontend.
const FRONTEND_URL = (process.env.GTM_FRONTEND_URL ?? "http://localhost:3000").replace(/\/+$/, "");

// Prototype-only: every "Forgot password?" reset link is sent HERE
// instead of the requesting account's own email -- edit this line to
// change where it goes, or set it to null to restore real per-account
// delivery. FORGOT_PASSWORD_OVERRIDE_RECIPIENT env var, if set, takes
// precedence over this -- leave it unset to let this hardcoded value
// control it. Ported verbatim from api.py's own hardcoded override.
const FORGOT_PASSWORD_HARDCODED_RECIPIENT: string | null = "kumar12795@gmail.com";

export async function registerAuthRoutes(app: FastifyInstance) {
  app.get("/auth/status", async () => ({
    signup_requires_code: auth.signupRequiresCode(),
    google_client_id: auth.GOOGLE_CLIENT_ID,
  }));

  app.post("/auth/signup", async (request, reply) => {
    const body = SignupRequest.parse(request.body);
    try {
      const user = await auth.createUser(body.email, body.password, body.signup_code ?? null);
      const token = await auth.createSession(user.id);
      setSessionCookie(reply, token);
      await notifyAdminsOfNewSignup(user);
      return user;
    } catch (e) {
      mapAuthError(e);
    }
  });

  app.post("/auth/login", async (request, reply) => {
    const body = LoginRequest.parse(request.body);
    const user = await auth.verifyCredentials(body.email, body.password);
    if (!user) {
      const err: any = new Error("incorrect email or password");
      err.statusCode = 401;
      throw err;
    }
    const token = await auth.createSession(user.id);
    setSessionCookie(reply, token);
    return user;
  });

  app.post("/auth/google", async (request, reply) => {
    const body = GoogleAuthRequest.parse(request.body);
    try {
      const user = await auth.googleLogin(body.credential);
      const { _is_new_account, ...publicUser } = user;
      const token = await auth.createSession(publicUser.id);
      setSessionCookie(reply, token);
      if (_is_new_account) await notifyAdminsOfNewSignup(publicUser);
      return publicUser;
    } catch (e) {
      mapAuthError(e);
    }
  });

  app.post("/auth/forgot-password", async (request) => {
    const body = ForgotPasswordRequest.parse(request.body);
    // Same anti-enumeration contract as Python: always the same response
    // regardless of whether the email matches an account.
    const token = await auth.createPasswordResetToken(body.email);
    if (token !== null) {
      const resetUrl = `${FRONTEND_URL}/reset-password?token=${token}`;
      const overrideRecipient = (process.env.FORGOT_PASSWORD_OVERRIDE_RECIPIENT ?? "").trim() || FORGOT_PASSWORD_HARDCODED_RECIPIENT || "";
      const recipient = overrideRecipient || body.email;
      const forLine = overrideRecipient ? `Password reset requested for account: ${body.email}\n\n` : "";
      await notifications.sendEmail(
        [recipient], "Reset your Talyn password",
        `${forLine}We received a request to reset your password. This link expires in 1 hour ` +
        `and can only be used once:\n\n${resetUrl}\n\n` +
        "If you didn't request this, you can safely ignore this email — your password won't change."
      );
    }
    return { status: "if an account exists for that email, we've sent a reset link" };
  });

  app.post("/auth/reset-password", async (request) => {
    const body = ResetPasswordRequest.parse(request.body);
    try {
      await auth.resetPassword(body.token, body.new_password);
      return { status: "password reset — log in with your new password" };
    } catch (e) {
      mapAuthError(e);
    }
  });

  app.post("/auth/logout", async (request, reply) => {
    const token = request.cookies[SESSION_COOKIE_NAME];
    if (token) await auth.deleteSession(token);
    reply.clearCookie(SESSION_COOKIE_NAME, { path: "/" });
    return { status: "logged out" };
  });

  app.get("/auth/me", async (request) => {
    return (request as any).user;
  });

  app.get("/users", { preHandler: requireRole("admin") }, async () => {
    return auth.listUsers();
  });

  app.patch("/users/:userId/role", { preHandler: requireRole("admin") }, async (request) => {
    const { userId } = request.params as { userId: string };
    const body = UserRoleRequest.parse(request.body);
    try {
      return await auth.setUserRole(userId, body.role);
    } catch (e) {
      mapAuthError(e);
    }
  });

  app.post("/admin/test-email", { preHandler: requireRole("admin") }, async (request) => {
    const body = TestEmailRequest.parse(request.body);
    return notifications.sendTestEmail(body.to);
  });
}
