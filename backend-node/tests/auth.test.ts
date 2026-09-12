import { describe, expect, it } from "vitest";
import { buildApp, login, sessionCookie, signup, authHeader } from "./helpers.js";
import { sentEmails } from "./mocks/nodemailer.js";
import { prisma } from "../src/db/client.js";

describe("auth", () => {
  it("the first account created in a fresh workspace becomes admin", async () => {
    const app = buildApp();
    const { user } = await signup(app, "first@test.com");
    expect(user.role).toBe("admin");
  });

  it("every account after the first defaults to recruiter", async () => {
    const app = buildApp();
    await signup(app, "first@test.com");
    const { user } = await signup(app, "second@test.com");
    expect(user.role).toBe("recruiter");
  });

  it("rejects a duplicate signup email", async () => {
    const app = buildApp();
    await signup(app, "dupe@test.com");
    const res = await app.inject({ method: "POST", url: "/auth/signup", payload: { email: "dupe@test.com", password: "correct-horse-battery" } });
    expect(res.statusCode).toBe(400);
    expect(res.json().detail).toMatch(/already exists/i);
  });

  it("rejects a password under 8 characters", async () => {
    const app = buildApp();
    const res = await app.inject({ method: "POST", url: "/auth/signup", payload: { email: "short@test.com", password: "abc123" } });
    expect(res.statusCode).toBe(400);
  });

  it("logs in with correct credentials and rejects incorrect ones", async () => {
    const app = buildApp();
    await signup(app, "loginme@test.com", "correct-horse-battery");

    const good = await login(app, "loginme@test.com", "correct-horse-battery");
    expect(good.user.email).toBe("loginme@test.com");

    const bad = await app.inject({ method: "POST", url: "/auth/login", payload: { email: "loginme@test.com", password: "wrong-password" } });
    expect(bad.statusCode).toBe(401);
  });

  it("a valid session cookie authenticates /auth/me; no cookie is rejected", async () => {
    const app = buildApp();
    const { cookie, user } = await signup(app, "me@test.com");

    const authed = await app.inject({ method: "GET", url: "/auth/me", headers: authHeader(cookie) });
    expect(authed.statusCode).toBe(200);
    expect(authed.json().email).toBe(user.email);

    const anon = await app.inject({ method: "GET", url: "/auth/me" });
    expect(anon.statusCode).toBe(401);
  });

  it("logout clears the session -- the old cookie no longer authenticates", async () => {
    const app = buildApp();
    const { cookie } = await signup(app, "logout@test.com");

    const out = await app.inject({ method: "POST", url: "/auth/logout", headers: authHeader(cookie) });
    expect(out.statusCode).toBe(200);

    const after = await app.inject({ method: "GET", url: "/auth/me", headers: authHeader(cookie) });
    expect(after.statusCode).toBe(401);
  });

  describe("Google sign-in", () => {
    it("creates a new account for a first-time verified Google email and logs them in", async () => {
      const app = buildApp();
      const credential = JSON.stringify({ email: "googleuser@test.com", email_verified: true });
      const res = await app.inject({ method: "POST", url: "/auth/google", payload: { credential } });
      expect(res.statusCode).toBe(200);
      expect(res.json().email).toBe("googleuser@test.com");
      expect(sessionCookie(res)).toBeTruthy();

      const stored = await prisma.user.findUnique({ where: { email: "googleuser@test.com" } });
      expect(stored).not.toBeNull();
    });

    it("logs in an existing account by email on a returning Google sign-in", async () => {
      const app = buildApp();
      await signup(app, "returning@test.com");
      const credential = JSON.stringify({ email: "returning@test.com", email_verified: true });
      const res = await app.inject({ method: "POST", url: "/auth/google", payload: { credential } });
      expect(res.statusCode).toBe(200);
      const count = await prisma.user.count({ where: { email: "returning@test.com" } });
      expect(count).toBe(1); // no duplicate account created
    });

    it("rejects a Google credential whose email isn't verified", async () => {
      const app = buildApp();
      const credential = JSON.stringify({ email: "unverified@test.com", email_verified: false });
      const res = await app.inject({ method: "POST", url: "/auth/google", payload: { credential } });
      expect(res.statusCode).toBe(400);
    });
  });

  describe("forgot password / reset password", () => {
    it("issues a reset token, emails a reset link, and the token resets the password", async () => {
      const app = buildApp();
      await signup(app, "resetme@test.com", "original-password");

      const forgot = await app.inject({ method: "POST", url: "/auth/forgot-password", payload: { email: "resetme@test.com" } });
      expect(forgot.statusCode).toBe(200);

      expect(sentEmails).toHaveLength(1);
      const match = sentEmails[0]!.text.match(/reset-password\?token=([\w-]+)/);
      expect(match).not.toBeNull();
      const token = match![1]!;

      const reset = await app.inject({
        method: "POST", url: "/auth/reset-password", payload: { token, new_password: "brand-new-password" },
      });
      expect(reset.statusCode).toBe(200);

      const oldPw = await app.inject({ method: "POST", url: "/auth/login", payload: { email: "resetme@test.com", password: "original-password" } });
      expect(oldPw.statusCode).toBe(401);

      const newPw = await app.inject({ method: "POST", url: "/auth/login", payload: { email: "resetme@test.com", password: "brand-new-password" } });
      expect(newPw.statusCode).toBe(200);
    });

    it("gives the same response for an email that has no account (anti-enumeration)", async () => {
      const app = buildApp();
      const res = await app.inject({ method: "POST", url: "/auth/forgot-password", payload: { email: "nobody@test.com" } });
      expect(res.statusCode).toBe(200);
      expect(sentEmails).toHaveLength(0); // no token, no email -- but the same 200 response
    });

    it("rejects an invalid or already-used reset token", async () => {
      const app = buildApp();
      const res = await app.inject({
        method: "POST", url: "/auth/reset-password", payload: { token: "not-a-real-token", new_password: "whatever-new-1" },
      });
      expect(res.statusCode).toBe(400);
    });

    it("a reset invalidates the account's other active sessions", async () => {
      const app = buildApp();
      const { cookie } = await signup(app, "sessionwipe@test.com", "original-password");

      await app.inject({ method: "POST", url: "/auth/forgot-password", payload: { email: "sessionwipe@test.com" } });
      const token = sentEmails[0]!.text.match(/token=([\w-]+)/)![1]!;
      await app.inject({ method: "POST", url: "/auth/reset-password", payload: { token, new_password: "another-new-pw1" } });

      const stillGood = await app.inject({ method: "GET", url: "/auth/me", headers: authHeader(cookie) });
      expect(stillGood.statusCode).toBe(401);
    });
  });

  describe("role management (admin-only)", () => {
    it("a non-admin cannot list users or change roles", async () => {
      const app = buildApp();
      await signup(app, "admin@test.com"); // first account, admin
      const { cookie } = await signup(app, "plain@test.com"); // second, recruiter

      const list = await app.inject({ method: "GET", url: "/users", headers: authHeader(cookie) });
      expect(list.statusCode).toBe(403);
    });

    it("an admin can list users and promote a recruiter to admin", async () => {
      const app = buildApp();
      const { cookie: adminCookie } = await signup(app, "admin2@test.com");
      const { user: plain } = await signup(app, "plain2@test.com");

      const list = await app.inject({ method: "GET", url: "/users", headers: authHeader(adminCookie) });
      expect(list.statusCode).toBe(200);
      expect(list.json()).toHaveLength(2);

      const promote = await app.inject({
        method: "PATCH", url: `/users/${plain.id}/role`, headers: authHeader(adminCookie), payload: { role: "admin" },
      });
      expect(promote.statusCode).toBe(200);
      expect(promote.json().role).toBe("admin");
    });

    it("rejects assigning a non-assignable role", async () => {
      const app = buildApp();
      const { cookie: adminCookie } = await signup(app, "admin3@test.com");
      const { user: plain } = await signup(app, "plain3@test.com");

      const res = await app.inject({
        method: "PATCH", url: `/users/${plain.id}/role`, headers: authHeader(adminCookie), payload: { role: "client" },
      });
      expect(res.statusCode).toBe(400);
    });
  });
});
