import { describe, expect, it } from "vitest";
import { authHeader, buildApp, createJob, multipartPayload, pollTask, seedIcp, signup } from "./helpers.js";
import { anthropicMock } from "./mocks/anthropic.js";
import { s3Puts } from "./mocks/awsS3.js";

describe("resume/JD file upload", () => {
  it("uploads a .txt JD, extracts its text, and logs the action -- no candidate involved", async () => {
    const app = buildApp();
    const { cookie } = await signup(app, "jdupload@test.com");
    await createJob("jd-upload-role");

    const { buffer, contentType } = await multipartPayload(
      {},
      { field: "file", filename: "job-description.txt", content: "Senior Backend Engineer, 5+ years Node.js.", contentType: "text/plain" }
    );
    const res = await app.inject({
      method: "POST", url: "/jobs/jd-upload-role/intake/upload",
      headers: { ...authHeader(cookie), "content-type": contentType }, payload: buffer,
    });
    expect(res.statusCode).toBe(200);
    expect(res.json().text).toContain("Senior Backend Engineer");
  });

  it("rejects a JD upload with no extractable text", async () => {
    const app = buildApp();
    const { cookie } = await signup(app, "jdempty@test.com");
    await createJob("jd-empty-role");
    const { buffer, contentType } = await multipartPayload({}, { field: "file", filename: "empty.txt", content: "   ", contentType: "text/plain" });
    const res = await app.inject({
      method: "POST", url: "/jobs/jd-empty-role/intake/upload", headers: { ...authHeader(cookie), "content-type": contentType }, payload: buffer,
    });
    expect(res.statusCode).toBe(400);
  });

  it("rejects an unsupported file type", async () => {
    const app = buildApp();
    const { cookie } = await signup(app, "jdbadtype@test.com");
    await createJob("jd-badtype-role");
    const { buffer, contentType } = await multipartPayload({}, { field: "file", filename: "resume.exe", content: "binary junk", contentType: "application/octet-stream" });
    const res = await app.inject({
      method: "POST", url: "/jobs/jd-badtype-role/intake/upload", headers: { ...authHeader(cookie), "content-type": contentType }, payload: buffer,
    });
    expect(res.statusCode).toBe(400);
  });

  it("uploads a candidate resume: extracts text, persists the file to object storage, and creates the candidate", async () => {
    const app = buildApp();
    const { cookie } = await signup(app, "resumeupload@test.com");
    await createJob("resume-upload-role");
    await seedIcp("resume-upload-role"); // candidateAnalysisStage.run() requires an ICP to exist first

    anthropicMock.nextParsedOutput = { candidate_id: "cand-jordan", name: "Jordan Reyes", email: "jordan@example.com" };

    const { buffer, contentType } = await multipartPayload(
      { role_family: "engineering" },
      { field: "file", filename: "jordan-reyes-resume.txt", content: "Jordan Reyes\nSenior Engineer, 6 years experience.", contentType: "text/plain" }
    );
    const upload = await app.inject({
      method: "POST", url: "/jobs/resume-upload-role/candidates/upload",
      headers: { ...authHeader(cookie), "content-type": contentType }, payload: buffer,
    });
    expect(upload.statusCode).toBe(202);
    const task = upload.json();

    // The original file actually reached object storage (mocked S3) --
    // best-effort per fileStorage.ts, but here storage IS configured
    // (see tests/setup.ts's RESUME_STORAGE_* env vars), so it must succeed.
    expect(s3Puts).toHaveLength(1);
    expect(s3Puts[0]!.key).toContain("resume-upload-role");
    expect(s3Puts[0]!.key).toContain("jordan-reyes-resume.txt");

    const finished = await pollTask(app, cookie, "resume-upload-role", task.task_id);
    expect(finished.status).toBe("succeeded");
    expect(finished.result.name).toBe("Jordan Reyes");

    const job = await app.inject({ method: "GET", url: "/jobs/resume-upload-role", headers: authHeader(cookie) });
    const candidates = job.json().state.candidates;
    const candidateIds = Object.keys(candidates);
    expect(candidateIds).toHaveLength(1);
    expect(candidates[candidateIds[0]!].name).toBe("Jordan Reyes");
    expect(candidates[candidateIds[0]!].resume_file_key).toBeTruthy();
  });

  it("rejects a candidate upload missing role_family", async () => {
    const app = buildApp();
    const { cookie } = await signup(app, "norolefamily@test.com");
    await createJob("no-role-family-role");
    await seedIcp("no-role-family-role");
    const { buffer, contentType } = await multipartPayload({}, { field: "file", filename: "resume.txt", content: "Someone", contentType: "text/plain" });
    const res = await app.inject({
      method: "POST", url: "/jobs/no-role-family-role/candidates/upload", headers: { ...authHeader(cookie), "content-type": contentType }, payload: buffer,
    });
    expect(res.statusCode).toBe(400);
  });

  it("a stored resume is retrievable via a signed download URL", async () => {
    const app = buildApp();
    const { cookie } = await signup(app, "download@test.com");
    await createJob("download-role");
    await seedIcp("download-role");
    anthropicMock.nextParsedOutput = { candidate_id: "cand-download", name: "Download Candidate" };
    const { buffer, contentType } = await multipartPayload(
      { role_family: "sales" },
      { field: "file", filename: "candidate.txt", content: "Download Candidate, sales lead.", contentType: "text/plain" }
    );
    const upload = await app.inject({
      method: "POST", url: "/jobs/download-role/candidates/upload", headers: { ...authHeader(cookie), "content-type": contentType }, payload: buffer,
    });
    const task = await pollTask(app, cookie, "download-role", upload.json().task_id);
    const candidateId = task.result.candidate_id;

    const download = await app.inject({ method: "GET", url: `/jobs/download-role/candidates/${candidateId}/resume`, headers: authHeader(cookie) });
    expect(download.statusCode).toBe(200);
    expect(download.json().url).toContain("fake-signed-url.test");
  });

  it("404s a resume download for a candidate with no stored file", async () => {
    const app = buildApp();
    const { cookie } = await signup(app, "nofile@test.com");
    await createJob("nofile-role");
    await seedIcp("nofile-role");
    // add a candidate the deterministic way (no upload -> no resume_file_key)
    anthropicMock.nextParsedOutput = { candidate_id: "cand-nofile", name: "No File Candidate" };
    const addRes = await app.inject({
      method: "POST", url: "/jobs/nofile-role/candidates", headers: authHeader(cookie),
      payload: { source_text: "No File Candidate, pasted text.", role_family: "ops" },
    });
    const task = await pollTask(app, cookie, "nofile-role", addRes.json().task_id);
    const download = await app.inject({ method: "GET", url: `/jobs/nofile-role/candidates/${task.result.candidate_id}/resume`, headers: authHeader(cookie) });
    expect(download.statusCode).toBe(404);
  });
});
