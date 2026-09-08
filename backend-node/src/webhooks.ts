// Port of webhooks.py -- a real HTTP POST to a recruiter-configured URL,
// never a fabricated "sent" state. Always best-effort: never throws.
const TIMEOUT_MS = 5000;

export async function sendWebhook(url: string, event: string, payload: Record<string, any>) {
  const body = { event, ...payload };
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    let response: Response;
    try {
      response = await fetch(url, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timer);
    }
    if (response.status >= 400) {
      return { ok: false, detail: `webhook URL returned HTTP ${response.status}` };
    }
    return { ok: true, detail: `delivered (HTTP ${response.status})` };
  } catch (e: any) {
    return { ok: false, detail: `could not reach webhook URL: ${e?.message ?? e}` };
  }
}
