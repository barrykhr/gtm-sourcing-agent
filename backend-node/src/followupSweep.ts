/**
 * Port of followup_sweep.py — background sweep that auto-sends due
 * outreach follow-ups. Runs on a timer instead of consuming a queue,
 * since there's nothing to enqueue here, just a periodic "what's due
 * right now" check.
 *
 * Sends nothing unless getWorkspaceSettings().auto_send_followups is
 * true — off by default. This is the one place in the app that emails
 * a candidate with no recruiter clicking "send" that day, so it stays
 * inert until a recruiter explicitly opts in.
 */
import * as storage from "./db/storage.js";
import { sendEmail } from "./notifications.js";

const SWEEP_INTERVAL_MS = 6 * 60 * 60 * 1000; // every 6 hours

let started = false;

export async function runOnce(): Promise<Record<string, any>[]> {
  const settings = await storage.getWorkspaceSettings();
  if (!settings.auto_send_followups) return [];

  const sent: Record<string, any>[] = [];
  for (const entry of await storage.dueFollowups()) {
    const ok = await sendEmail([entry.email], `Following up: ${entry.role_title}`, entry.draft_message);
    if (!ok) {
      console.warn(
        `followup sweep: failed to send stage ${entry.followup_stage} to ${entry.email} (role ${entry.role_id})`
      );
      continue;
    }
    await storage.logCommunication(entry.role_id, entry.candidate_id, {
      channel: "email", direction: "outbound", content: entry.draft_message,
      contactUsed: entry.email, loggedBy: "auto-followup", followupStage: entry.followup_stage,
    });
    sent.push(entry);
  }
  if (sent.length) console.log(`followup sweep: auto-sent ${sent.length} follow-up(s)`);
  return sent;
}

async function loop(): Promise<void> {
  await new Promise((resolve) => {
    const timer = setTimeout(resolve, SWEEP_INTERVAL_MS);
    timer.unref(); // daemon-like: never keeps the process (or a test run) alive
  });
  try {
    await runOnce();
  } catch (err) {
    console.error("followup sweep: unhandled error", err);
  }
  void loop();
}

export function start(): void {
  if (started) return;
  started = true;
  void loop();
}
