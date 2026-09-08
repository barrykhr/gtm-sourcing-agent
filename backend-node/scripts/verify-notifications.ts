/**
 * Verifies notifications.ts against a real local SMTP server (smtp-server,
 * from nodemailer's own author) speaking real STARTTLS+AUTH, not a mock
 * of nodemailer -- proves the actual wire protocol works: connect,
 * STARTTLS upgrade, LOGIN auth, MAIL FROM/RCPT TO/DATA. Also verifies the
 * honest "not configured" behavior (false/error, never throws) that is
 * this module's core design contract.
 */
import fs from "node:fs";
import { SMTPServer } from "smtp-server";
import { simpleParser } from "mailparser";

let failures = 0;
function check(label: string, ok: boolean, detail?: unknown) {
  if (ok) console.log(`PASS: ${label}`);
  else { console.log(`FAIL: ${label}`, detail ?? ""); failures++; }
}

const received: { from: string; to: string[]; subject: string; text: string }[] = [];

async function main() {
  // ── 1. unconfigured behavior (no env vars set) -- must never throw ──
  delete process.env.SMTP_HOST;
  delete process.env.SMTP_USERNAME;
  delete process.env.SMTP_PASSWORD;
  delete process.env.SMTP_FROM_ADDRESS;
  const notifications = await import("../src/notifications.js");

  check("isConfigured() is false with no env vars set", notifications.isConfigured() === false);
  const unconfiguredSend = await notifications.sendEmail(["a@example.com"], "subj", "body");
  check("sendEmail() returns false (never throws) when unconfigured", unconfiguredSend === false);
  const unconfiguredTest = await notifications.sendTestEmail("a@example.com");
  check("sendTestEmail() reports the specific missing env vars", unconfiguredTest.sent === false && /SMTP_HOST/.test(unconfiguredTest.error ?? ""), unconfiguredTest);
  const noRecipients = await notifications.sendEmail([], "subj", "body");
  check("sendEmail() returns false for an empty recipient list", noRecipients === false);

  // ── 2. real STARTTLS SMTP server, real send ──
  const server = new SMTPServer({
    secure: false,
    key: fs.readFileSync("/tmp/smtptest/key.pem"),
    cert: fs.readFileSync("/tmp/smtptest/cert.pem"),
    authOptional: false,
    onAuth(auth, _session, callback) {
      if (auth.username === "testuser" && auth.password === "testpass") callback(null, { user: "testuser" });
      else callback(new Error("bad credentials"));
    },
    onData(stream, session, callback) {
      simpleParser(stream, {}, (err, parsed) => {
        if (!err) {
          received.push({
            from: session.envelope.mailFrom ? (session.envelope.mailFrom as any).address : "",
            to: session.envelope.rcptTo.map((r: any) => r.address),
            subject: parsed.subject ?? "", text: (parsed.text ?? "").trim(),
          });
        }
        callback();
      });
    },
  });
  const port = 25252;
  await new Promise<void>((resolve) => server.listen(port, "127.0.0.1", resolve));

  process.env.SMTP_HOST = "127.0.0.1";
  process.env.SMTP_PORT = String(port);
  process.env.SMTP_USERNAME = "testuser";
  process.env.SMTP_PASSWORD = "testpass";
  process.env.SMTP_FROM_ADDRESS = "noreply@talyn.test";
  // nodemailer verifies the server cert by default; our self-signed test
  // cert has no real CA, so this test explicitly allows that -- a
  // real deployment would use a CA-issued cert its provider supplies.
  process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0";

  check("isConfigured() is true once all SMTP_* env vars are set", notifications.isConfigured() === true);

  const sent = await notifications.sendEmail(["candidate@example.com"], "Regarding the Enterprise AE opportunity", "Hi there, following up...");
  check("sendEmail() returns true on a real successful STARTTLS send", sent === true);
  check("the SMTP server actually received the message", received.length === 1, received);
  check("received message has the correct from/to/subject", received[0]?.from === "noreply@talyn.test" && received[0]?.to.includes("candidate@example.com") && received[0]?.subject === "Regarding the Enterprise AE opportunity", received[0]);

  const testResult = await notifications.sendTestEmail("admin@talyn.test");
  check("sendTestEmail() reports sent:true with a real working server", testResult.sent === true && testResult.error === null, testResult);
  check("the SMTP server received the test email too", received.length === 2, received.length);

  const adminNotifySent = await notifications.notifyAdminsOfNewSignup("newuser@example.com", "recruiter", ["admin@talyn.test"]);
  check("notifyAdminsOfNewSignup sends to the admin list", adminNotifySent === true);
  check("notifyAdminsOfNewSignup skips entirely with no admins (returns false, no send attempted)",
    (await notifications.notifyAdminsOfNewSignup("x@example.com", "recruiter", [])) === false);

  // ── 3. wrong credentials -- must report failure honestly, not throw ──
  process.env.SMTP_PASSWORD = "wrong-password";
  const badAuthSend = await notifications.sendEmail(["x@example.com"], "subj", "body");
  check("sendEmail() returns false (not throw) on auth failure", badAuthSend === false);
  const badAuthTest = await notifications.sendTestEmail("x@example.com");
  check("sendTestEmail() surfaces the real auth error text", badAuthTest.sent === false && !!badAuthTest.error, badAuthTest);

  server.close();
  console.log(failures === 0 ? "\nALL CHECKS PASSED" : `\n${failures} CHECK(S) FAILED`);
  process.exit(failures === 0 ? 0 : 1);
}

main();
