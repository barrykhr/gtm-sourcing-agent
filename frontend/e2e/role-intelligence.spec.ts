import { expect, test } from "@playwright/test";

/**
 * First committed Playwright E2E test in this repo (see
 * playwright.config.ts's docstring for scope/why). Covers Feature 01's
 * create-role-through-edit flow end to end against a real backend,
 * real frontend, and a real (isolated) database — no mocks — for the
 * deterministic, no-LLM-involved parts of Role Intelligence: create a
 * role, add a requirement through the UI, edit it, remove it, and
 * verify the change history records who changed what.
 */

const API_BASE = "http://localhost:8311";

test.describe("Role Intelligence", () => {
  test("create role, add/edit/remove a requirement through the UI, see history", async ({ page }) => {
    const unique = Date.now();
    const email = `e2e-${unique}@example.com`;
    const roleId = `e2e-role-${unique}`;

    await page.goto("/");

    // Sign up and create a role directly via the real API (same as a
    // recruiter would via the UI's own signup/create-role forms — this
    // just skips re-testing those existing, already-covered flows).
    const signup = await page.evaluate(
      async ({ apiBase, email }) => {
        const res = await fetch(`${apiBase}/auth/signup`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password: "test-password-123" }),
        });
        return res.status;
      },
      { apiBase: API_BASE, email },
    );
    expect(signup).toBe(200);

    const createJob = await page.evaluate(
      async ({ apiBase, roleId }) => {
        const res = await fetch(`${apiBase}/jobs`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: "E2E AE Role", role_id: roleId }),
        });
        return res.status;
      },
      { apiBase: API_BASE, roleId },
    );
    expect(createJob).toBe(200);

    await page.goto(`/jobs/${roleId}`);
    await expect(page.locator("nav button:has-text('Role Intelligence')")).toBeVisible();
    await page.click("nav button:has-text('Role Intelligence')");

    // Starts empty.
    await expect(page.getByText("No requirements yet")).toBeVisible();

    // Add a requirement through the real UI form.
    await page.click("text=+ Add requirement");
    await page.selectOption('select[aria-label="Requirement category"]', "skill");
    await page.selectOption('select[aria-label="Requirement priority"]', "must_have");
    await page.fill('input[aria-label="Requirement text"]', "Salesforce");
    await page.click("button:has-text('Save')");

    await expect(page.getByText("Salesforce")).toBeVisible();
    await expect(page.getByText("NOT STATED", { exact: true })).toBeVisible();
    await expect(page.getByText("Must have")).toBeVisible();

    // Edit: flip its priority.
    await page.click("button:has-text('Make nice-to-have')");
    await expect(page.getByText("Nice to have")).toBeVisible();

    // History reflects both the add and the update, attributed to this user.
    await page.click("text=Show change history");
    const historyPanel = page.locator("h3:text-is('Change history')").locator("../..");
    await expect(historyPanel.getByText("add requirement")).toBeVisible();
    await expect(historyPanel.getByText("update requirement")).toBeVisible();
    await expect(historyPanel.getByText(email)).toHaveCount(2);

    // Remove it.
    await page.click("button:has-text('Remove')");
    await expect(page.getByText("No requirements yet")).toBeVisible();
  });
});
