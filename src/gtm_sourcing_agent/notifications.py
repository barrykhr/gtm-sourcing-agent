"""Admin email notifications — currently just "a new account signed up."
Same never-fake-it stance as webhooks.py and file_storage.py: without
SMTP_* configured, every function here is a no-op, and callers must
treat that as "not sent in this environment," never as an error. A
notification failure must never break the signup it rides along with —
send_email never raises.

Sends via plain SMTP (Python's stdlib smtplib) rather than a specific
provider's API, so any provider works: Resend, SES, Mailgun, Postmark,
or a Google Workspace account all speak SMTP. No new third-party
dependency either way.
"""

import logging
import os
import smtplib
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

ENV_HOST = "SMTP_HOST"
ENV_PORT = "SMTP_PORT"
ENV_USERNAME = "SMTP_USERNAME"
ENV_PASSWORD = "SMTP_PASSWORD"
ENV_FROM_ADDRESS = "SMTP_FROM_ADDRESS"


def is_configured() -> bool:
    return bool(
        os.environ.get(ENV_HOST)
        and os.environ.get(ENV_USERNAME)
        and os.environ.get(ENV_PASSWORD)
        and os.environ.get(ENV_FROM_ADDRESS)
    )


def send_email(to_addresses: list[str], subject: str, body: str) -> bool:
    """Best-effort send. Returns whether it actually went out — False
    when SMTP isn't configured, or when sending failed for any reason.
    Never raises: a broken mail server must never be the reason a
    signup, or anything else this rides along with, fails."""
    if not to_addresses:
        return False
    if not is_configured():
        logger.info("email notifications not configured — skipping: %s", subject)
        return False
    from_address = os.environ[ENV_FROM_ADDRESS]
    message = MIMEText(body)
    message["Subject"] = subject
    message["From"] = from_address
    message["To"] = ", ".join(to_addresses)
    port = int(os.environ.get(ENV_PORT, "587"))
    try:
        with smtplib.SMTP(os.environ[ENV_HOST], port, timeout=10) as server:
            server.starttls()
            server.login(os.environ[ENV_USERNAME], os.environ[ENV_PASSWORD])
            server.sendmail(from_address, to_addresses, message.as_string())
    except Exception:
        logger.exception("failed to send email notification: %s", subject)
        return False
    return True


def send_test_email(to_address: str) -> dict[str, str | bool | None]:
    """Admin diagnostic (POST /admin/test-email): attempts a real SMTP
    send and reports exactly what happened, error text included. Unlike
    send_email above — which deliberately never raises or explains
    itself, since a broken mail server must never break the signup or
    password-reset flow it rides along with — this exists purely so an
    admin can see *why* delivery is failing without needing server log
    access (which, on Render's free tier, may not even be available)."""
    if not is_configured():
        missing = [
            name
            for name, val in (
                (ENV_HOST, os.environ.get(ENV_HOST)),
                (ENV_USERNAME, os.environ.get(ENV_USERNAME)),
                (ENV_PASSWORD, os.environ.get(ENV_PASSWORD)),
                (ENV_FROM_ADDRESS, os.environ.get(ENV_FROM_ADDRESS)),
            )
            if not val
        ]
        return {"sent": False, "error": f"not configured — missing env var(s): {', '.join(missing)}"}
    from_address = os.environ[ENV_FROM_ADDRESS]
    message = MIMEText("This is a test email sent from Talyn's admin SMTP diagnostic tool.")
    message["Subject"] = "Talyn SMTP test"
    message["From"] = from_address
    message["To"] = to_address
    port = int(os.environ.get(ENV_PORT, "587"))
    try:
        with smtplib.SMTP(os.environ[ENV_HOST], port, timeout=10) as server:
            server.starttls()
            server.login(os.environ[ENV_USERNAME], os.environ[ENV_PASSWORD])
            server.sendmail(from_address, [to_address], message.as_string())
    except Exception as e:
        return {"sent": False, "error": f"{type(e).__name__}: {e}"}
    return {"sent": True, "error": None}


def notify_admins_of_new_signup(new_user_email: str, new_user_role: str, admin_emails: list[str]) -> bool:
    """Called once per newly created account (never for a returning
    Google-login or a plain password login) — see api.py's signup
    routes. Skipped entirely when the new account IS the admin list
    (the first-ever account on a fresh deployment): there's no one to
    notify yet, and it would just be telling the admin about themselves."""
    if not admin_emails:
        return False
    subject = f"New Talyn account: {new_user_email}"
    body = (
        f"{new_user_email} just created an account (role: {new_user_role}).\n\n"
        "Review or change their access under Team -> Accounts & roles."
    )
    return send_email(admin_emails, subject, body)
