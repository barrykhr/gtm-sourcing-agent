/**
 * Session-based auth — Node.js port of src/gtm_sourcing_agent/auth.py.
 * Every constant and algorithm choice below is copied exactly, not
 * reinterpreted, because existing accounts must keep working:
 *
 *  - PBKDF2-HMAC-SHA256, 600,000 iterations, 32-byte digest, 16-byte
 *    random salt stored as hex — see docs/migration.md §6 for the
 *    real byte-for-byte equality test this was validated against.
 *  - Session cookie name "gtm_session", 14-day TTL.
 *  - First account on a fresh deployment becomes "admin"; every account
 *    after that defaults to "recruiter".
 *  - Only "admin"/"recruiter" are assignable roles; "client"/
 *    "interviewer" are reserved (see ASSIGNABLE_ROLES) — same as Python.
 */
import crypto from "node:crypto";
import { prisma } from "../db/client.js";

export const SESSION_COOKIE_NAME = "gtm_session";
export const SESSION_TTL_MS = 14 * 24 * 60 * 60 * 1000;
const PASSWORD_RESET_TTL_MS = 60 * 60 * 1000;
const PBKDF2_ITERATIONS = 600_000;

export const ROLES = ["admin", "recruiter", "client", "interviewer"] as const;
export const ASSIGNABLE_ROLES = ["admin", "recruiter"] as const;

export const SIGNUP_CODE = process.env.GTM_SIGNUP_CODE || null;
export const GOOGLE_CLIENT_ID = process.env.GTM_GOOGLE_CLIENT_ID || null;
export const GOOGLE_ALLOWED_DOMAIN = process.env.GTM_GOOGLE_ALLOWED_DOMAIN || null;

export class AuthError extends Error {}

export interface PublicUser {
  id: string;
  email: string;
  role: string;
}

function hashPassword(password: string, saltHex: string): string {
  const salt = Buffer.from(saltHex, "hex");
  return crypto.pbkdf2Sync(password, salt, PBKDF2_ITERATIONS, 32, "sha256").toString("hex");
}

export function signupRequiresCode(): boolean {
  return SIGNUP_CODE !== null;
}

export async function createUser(
  email: string,
  password: string,
  signupCode?: string | null
): Promise<PublicUser> {
  if (SIGNUP_CODE !== null && signupCode !== SIGNUP_CODE) {
    throw new AuthError("invalid signup code");
  }
  if (password.length < 8) {
    throw new AuthError("password must be at least 8 characters");
  }
  const existing = await prisma.user.findUnique({ where: { email } });
  if (existing) {
    throw new AuthError(`an account already exists for '${email}' — log in instead`);
  }
  const isFirstAccount = (await prisma.user.count()) === 0;
  const salt = crypto.randomBytes(16).toString("hex");
  const user = await prisma.user.create({
    data: {
      id: `user-${crypto.randomBytes(8).toString("hex")}`,
      email,
      role: isFirstAccount ? "admin" : "recruiter",
      passwordHash: hashPassword(password, salt),
      passwordSalt: salt,
    },
  });
  return { id: user.id, email: user.email, role: user.role };
}

export async function verifyCredentials(email: string, password: string): Promise<PublicUser | null> {
  const user = await prisma.user.findUnique({ where: { email } });
  if (!user) return null;
  if (hashPassword(password, user.passwordSalt) !== user.passwordHash) return null;
  return { id: user.id, email: user.email, role: user.role };
}

export async function createPasswordResetToken(email: string): Promise<string | null> {
  const user = await prisma.user.findUnique({ where: { email } });
  if (!user) return null;
  await prisma.passwordResetToken.deleteMany({ where: { userId: user.id } });
  const token = crypto.randomBytes(32).toString("base64url");
  await prisma.passwordResetToken.create({
    data: { token, userId: user.id, expiresAt: new Date(Date.now() + PASSWORD_RESET_TTL_MS) },
  });
  return token;
}

export async function resetPassword(token: string, newPassword: string): Promise<void> {
  if (newPassword.length < 8) {
    throw new AuthError("password must be at least 8 characters");
  }
  const reset = await prisma.passwordResetToken.findUnique({ where: { token } });
  if (!reset) throw new AuthError("invalid or expired reset link — request a new one");
  const userId = reset.userId;
  await prisma.passwordResetToken.delete({ where: { token } });
  if (reset.expiresAt.getTime() < Date.now()) {
    throw new AuthError("invalid or expired reset link — request a new one");
  }
  const user = await prisma.user.findUnique({ where: { id: userId } });
  if (!user) throw new AuthError("invalid or expired reset link — request a new one");
  const salt = crypto.randomBytes(16).toString("hex");
  await prisma.user.update({
    where: { id: userId },
    data: { passwordHash: hashPassword(newPassword, salt), passwordSalt: salt },
  });
  await prisma.session.deleteMany({ where: { userId } });
}

export async function setUserRole(userId: string, role: string): Promise<PublicUser> {
  if (!(ASSIGNABLE_ROLES as readonly string[]).includes(role)) {
    throw new AuthError(`'${role}' is not an assignable role — must be one of ${ASSIGNABLE_ROLES}`);
  }
  const existing = await prisma.user.findUnique({ where: { id: userId } });
  if (!existing) throw new AuthError(`user '${userId}' not found`);
  const user = await prisma.user.update({ where: { id: userId }, data: { role } });
  return { id: user.id, email: user.email, role: user.role };
}

export async function listUsers(): Promise<(PublicUser & { created_at: Date })[]> {
  const users = await prisma.user.findMany({ orderBy: { createdAt: "asc" } });
  return users.map((u) => ({ id: u.id, email: u.email, role: u.role, created_at: u.createdAt }));
}

export async function createSession(userId: string): Promise<string> {
  const token = crypto.randomBytes(32).toString("base64url");
  await prisma.session.create({
    data: { token, userId, expiresAt: new Date(Date.now() + SESSION_TTL_MS) },
  });
  return token;
}

export async function getUserFromSession(token: string | undefined): Promise<PublicUser | null> {
  if (!token) return null;
  const session = await prisma.session.findUnique({ where: { token } });
  if (!session) return null;
  if (session.expiresAt.getTime() < Date.now()) {
    await prisma.session.delete({ where: { token } });
    return null;
  }
  const user = await prisma.user.findUnique({ where: { id: session.userId } });
  return user ? { id: user.id, email: user.email, role: user.role } : null;
}

export async function deleteSession(token: string): Promise<void> {
  await prisma.session.deleteMany({ where: { token } });
}

// ── Google Sign-In ─────────────────────────────────────────────────────

async function verifyGoogleIdToken(credential: string): Promise<string> {
  const { OAuth2Client } = await import("google-auth-library");
  const client = new OAuth2Client(GOOGLE_CLIENT_ID ?? undefined);
  const ticket = await client.verifyIdToken({ idToken: credential, audience: GOOGLE_CLIENT_ID ?? undefined });
  const payload = ticket.getPayload();
  if (!payload?.email_verified) {
    throw new AuthError("Google account email is not verified");
  }
  return payload.email!;
}

export async function googleLogin(credential: string): Promise<PublicUser & { _is_new_account: boolean }> {
  if (GOOGLE_CLIENT_ID === null) {
    throw new AuthError("Google sign-in is not configured on this server");
  }
  const email = await verifyGoogleIdToken(credential);
  if (GOOGLE_ALLOWED_DOMAIN !== null && !email.toLowerCase().endsWith(`@${GOOGLE_ALLOWED_DOMAIN.toLowerCase()}`)) {
    throw new AuthError(`'${email}' is not on the allowed domain for this workspace`);
  }
  let user = await prisma.user.findUnique({ where: { email } });
  const isNewAccount = user === null;
  if (!user) {
    const isFirstAccount = (await prisma.user.count()) === 0;
    const salt = crypto.randomBytes(16).toString("hex");
    user = await prisma.user.create({
      data: {
        id: `user-${crypto.randomBytes(8).toString("hex")}`,
        email,
        role: isFirstAccount ? "admin" : "recruiter",
        passwordHash: hashPassword(crypto.randomBytes(24).toString("base64url"), salt),
        passwordSalt: salt,
      },
    });
  }
  return { id: user.id, email: user.email, role: user.role, _is_new_account: isNewAccount };
}
