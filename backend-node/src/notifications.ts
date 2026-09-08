// Port of notifications.py -- admin email notifications via plain SMTP
// (nodemailer, not a specific provider's API) so any provider works.
// Never fakes success: without SMTP_* configured, every function here
// is a no-op/false, never an error, and send_email never throws.
import nodemailer from "nodemailer";

const ENV_HOST = "SMTP_HOST";
const ENV_PORT = "SMTP_PORT";
const ENV_USERNAME = "SMTP_USERNAME";
const ENV_PASSWORD = "SMTP_PASSWORD";
const ENV_FROM_ADDRESS = "SMTP_FROM_ADDRESS";

export function isConfigured(): boolean {
  return Boolean(
    process.env[ENV_HOST] && process.env[ENV_USERNAME] && process.env[ENV_PASSWORD] && process.env[ENV_FROM_ADDRESS]
  );
}

function buildTransport() {
  return nodemailer.createTransport({
    host: process.env[ENV_HOST],
    port: Number(process.env[ENV_PORT] ?? 587),
    secure: false,
    requireTLS: true,
    auth: { user: process.env[ENV_USERNAME], pass: process.env[ENV_PASSWORD] },
    connectionTimeout: 10000,
  });
}

/** Best-effort send. Returns whether it actually went out -- false when
 * SMTP isn't configured, or sending failed for any reason. Never throws:
 * a broken mail server must never be the reason a signup, or anything
 * else this rides along with, fails. */
export async function sendEmail(toAddresses: string[], subject: string, body: string): Promise<boolean> {
  if (!toAddresses.length) return false;
  if (!isConfigured()) {
    console.info(`email notifications not configured — skipping: ${subject}`);
    return false;
  }
  const fromAddress = process.env[ENV_FROM_ADDRESS]!;
  try {
    await buildTransport().sendMail({ from: fromAddress, to: toAddresses.join(", "), subject, text: body });
  } catch (e) {
    console.error(`failed to send email notification: ${subject}`, e);
    return false;
  }
  return true;
}

/** Admin diagnostic (POST /admin/test-email): attempts a real SMTP send
 * and reports exactly what happened, error text included -- unlike
 * sendEmail, which deliberately never throws or explains itself. */
export async function sendTestEmail(toAddress: string): Promise<{ sent: boolean; error: string | null }> {
  if (!isConfigured()) {
    const missing = [ENV_HOST, ENV_USERNAME, ENV_PASSWORD, ENV_FROM_ADDRESS].filter((k) => !process.env[k]);
    return { sent: false, error: `not configured — missing env var(s): ${missing.join(", ")}` };
  }
  const fromAddress = process.env[ENV_FROM_ADDRESS]!;
  try {
    await buildTransport().sendMail({
      from: fromAddress, to: toAddress, subject: "Talyn SMTP test",
      text: "This is a test email sent from Talyn's admin SMTP diagnostic tool.",
    });
  } catch (e: any) {
    return { sent: false, error: `${e?.name ?? "Error"}: ${e?.message ?? e}` };
  }
  return { sent: true, error: null };
}

/** Called once per newly created account (never for a returning
 * Google-login or a plain password login). Skipped entirely when there
 * are no admins to notify (the first-ever account on a fresh
 * deployment). */
export async function notifyAdminsOfNewSignup(
  newUserEmail: string, newUserRole: string, adminEmails: string[]
): Promise<boolean> {
  if (!adminEmails.length) return false;
  const subject = `New Talyn account: ${newUserEmail}`;
  const body =
    `${newUserEmail} just created an account (role: ${newUserRole}).\n\n` +
    "Review or change their access under Team -> Accounts & roles.";
  return sendEmail(adminEmails, subject, body);
}
