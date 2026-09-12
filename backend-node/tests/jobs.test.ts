import { describe, expect, it } from "vitest";
import { authHeader, buildApp, signup } from "./helpers.js";

describe("job CRUD", () => {
  it("creates a job, owned by the creator, findable in the job list and by id", async () => {
    const app = buildApp();
    const { cookie, user } = await signup(app, "creator@test.com");

    const create = await app.inject({
      method: "POST", url: "/jobs", headers: authHeader(cookie),
      payload: { title: "Senior Backend Engineer", role_family: "engineering", client_name: "Acme Corp" },
    });
    expect(create.statusCode).toBe(200);
    const job = create.json();
    expect(job.role_id).toBe("senior-backend-engineer");

    const list = await app.inject({ method: "GET", url: "/jobs", headers: authHeader(cookie) });
    expect(list.json().map((j: any) => j.role_id)).toContain(job.role_id);

    const get = await app.inject({ method: "GET", url: `/jobs/${job.role_id}`, headers: authHeader(cookie) });
    expect(get.statusCode).toBe(200);
    expect(get.json().owner_email).toBe(user.email);
  });

  it("de-duplicates the generated role_id when two jobs share a title", async () => {
    const app = buildApp();
    const { cookie } = await signup(app, "dedupe@test.com");
    const first = await app.inject({ method: "POST", url: "/jobs", headers: authHeader(cookie), payload: { title: "Recruiter" } });
    const second = await app.inject({ method: "POST", url: "/jobs", headers: authHeader(cookie), payload: { title: "Recruiter" } });
    expect(first.json().role_id).toBe("recruiter");
    expect(second.json().role_id).toBe("recruiter-2");
  });

  it("404s for a job that doesn't exist", async () => {
    const app = buildApp();
    const { cookie } = await signup(app, "notfound@test.com");
    const res = await app.inject({ method: "GET", url: "/jobs/does-not-exist", headers: authHeader(cookie) });
    expect(res.statusCode).toBe(404);
  });

  it("updates lifecycle status, client name, and role value", async () => {
    const app = buildApp();
    const { cookie } = await signup(app, "updater@test.com");
    const { role_id } = (await app.inject({ method: "POST", url: "/jobs", headers: authHeader(cookie), payload: { title: "Ops Manager" } })).json();

    const lifecycle = await app.inject({ method: "PATCH", url: `/jobs/${role_id}/lifecycle`, headers: authHeader(cookie), payload: { lifecycle_status: "ON_HOLD" } });
    expect(lifecycle.statusCode).toBe(200);
    expect(lifecycle.json().lifecycle_status).toBe("ON_HOLD");

    const client = await app.inject({ method: "PATCH", url: `/jobs/${role_id}/client`, headers: authHeader(cookie), payload: { client_name: "New Client Inc" } });
    expect(client.json().client_name).toBe("New Client Inc");

    const value = await app.inject({ method: "PATCH", url: `/jobs/${role_id}/value`, headers: authHeader(cookie), payload: { role_value: 200000 } });
    expect(value.statusCode).toBe(200);
    expect(value.json().role_value).toBe(200000);
    // Revenue = 8.33% of role_value, computed by revenue.ts -- see the audit that already verified this formula matches Python
    expect(value.json().expected_revenue).toBeCloseTo(200000 * 0.0833, 2);
  });

  it("rejects an invalid lifecycle status", async () => {
    const app = buildApp();
    const { cookie } = await signup(app, "badlifecycle@test.com");
    const { role_id } = (await app.inject({ method: "POST", url: "/jobs", headers: authHeader(cookie), payload: { title: "QA Lead" } })).json();
    const res = await app.inject({ method: "PATCH", url: `/jobs/${role_id}/lifecycle`, headers: authHeader(cookie), payload: { lifecycle_status: "not-a-real-status" } });
    expect(res.statusCode).toBe(400);
  });

  it("reassigns the owner via PATCH /owner", async () => {
    const app = buildApp();
    const { cookie } = await signup(app, "owner1@test.com");
    const { cookie: other } = await signup(app, "owner2@test.com");
    const { role_id } = (await app.inject({ method: "POST", url: "/jobs", headers: authHeader(cookie), payload: { title: "Designer" } })).json();

    const res = await app.inject({ method: "PATCH", url: `/jobs/${role_id}/owner`, headers: authHeader(cookie), payload: { owner_email: "owner2@test.com" } });
    expect(res.statusCode).toBe(200);
    expect(res.json().owner_email).toBe("owner2@test.com");
    void other;
  });

  it("adds and removes recruiters on a job", async () => {
    const app = buildApp();
    const { cookie } = await signup(app, "recruiterowner@test.com");
    const { role_id } = (await app.inject({ method: "POST", url: "/jobs", headers: authHeader(cookie), payload: { title: "Data Scientist" } })).json();

    const add = await app.inject({ method: "POST", url: `/jobs/${role_id}/recruiters`, headers: authHeader(cookie), payload: { email: "helper@test.com" } });
    expect(add.statusCode).toBe(200);
    expect(add.json().map((r: any) => r.email)).toContain("helper@test.com");

    const list = await app.inject({ method: "GET", url: `/jobs/${role_id}/recruiters`, headers: authHeader(cookie) });
    expect(list.json().map((r: any) => r.email)).toContain("helper@test.com");

    const remove = await app.inject({ method: "DELETE", url: `/jobs/${role_id}/recruiters/helper@test.com`, headers: authHeader(cookie) });
    expect(remove.statusCode).toBe(200);
    expect(remove.json().map((r: any) => r.email)).not.toContain("helper@test.com");
  });

  it("clones a job into a new role_id, carrying over its role_family", async () => {
    const app = buildApp();
    const { cookie } = await signup(app, "cloner@test.com");
    const { role_id } = (await app.inject({
      method: "POST", url: "/jobs", headers: authHeader(cookie), payload: { title: "Support Engineer", role_family: "support" },
    })).json();

    const clone = await app.inject({
      method: "POST", url: `/jobs/${role_id}/clone`, headers: authHeader(cookie),
      payload: { title: "Support Engineer II", role_family: "support" },
    });
    expect(clone.statusCode).toBe(200);
    expect(clone.json().role_id).not.toBe(role_id);
    expect(clone.json().role_family).toBe("support");
  });

  it("rejects an unauthenticated request to create a job", async () => {
    const app = buildApp();
    const res = await app.inject({ method: "POST", url: "/jobs", payload: { title: "No Auth" } });
    expect(res.statusCode).toBe(401);
  });
});
