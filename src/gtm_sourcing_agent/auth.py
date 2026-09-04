"""Session-based auth — Phase 7, extended to multiple accounts in Phase 8
(docs/product-plan.md). Deliberately plain: this is a small-team
recruiting tool with no per-user data isolation, not multi-tenant SaaS —
every logged-in account sees every job. That's why this is a bearer
session token in an HTTP-only cookie plus a shared-secret signup gate,
not OAuth/SSO or a full user-management system with roles/permissions
this product has no use for yet.

Password hashing is PBKDF2-HMAC-SHA256 via the stdlib `hashlib` — no new
dependency, and a deliberately conservative choice: correct salted
hashing beats no hashing, and a heavier scheme (bcrypt/argon2) can
replace this later without changing anything above this module, same
"swap what's below" pattern as db_storage.py.
"""

import hashlib
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from . import db
from .models_orm import Session, User

SESSION_COOKIE_NAME = "gtm_session"
SESSION_TTL = timedelta(days=14)
_PBKDF2_ITERATIONS = 600_000

# Role/permission foundation (production-readiness phase). Only "admin"
# and "recruiter" are actually assignable/enforced right now — "client"
# and "interviewer" are reserved so a future account type doesn't need a
# schema/enum change, per the explicit brief for this phase. Enforcement
# lives server-side (require_role in api.py), never in frontend nav —
# hiding a button is not a permission boundary.
ROLES = ("admin", "recruiter", "client", "interviewer")
ASSIGNABLE_ROLES = ("admin", "recruiter")

# Optional invite-code gate on signup — unset (the default) means anyone
# who can reach this server can create an account. Set it once a shared
# workspace needs to control who joins.
SIGNUP_CODE = os.environ.get("GTM_SIGNUP_CODE") or None


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _PBKDF2_ITERATIONS).hex()


def signup_requires_code() -> bool:
    return SIGNUP_CODE is not None


def create_user(email: str, password: str, signup_code: str | None = None) -> dict[str, Any]:
    """Any number of accounts, all sharing the same workspace — see
    module docstring. Raises ValueError (mapped to 400 by the API layer)
    on a duplicate email, a too-weak password, or a missing/wrong signup
    code when one is configured. The very first account on a fresh
    deployment becomes "admin" automatically (there is otherwise no way
    to grant that role — the change-role endpoint itself requires an
    existing admin); every account after that defaults to "recruiter"
    and an existing admin can promote them later."""
    if SIGNUP_CODE is not None and signup_code != SIGNUP_CODE:
        raise ValueError("invalid signup code")
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    with db.get_session() as db_session:
        if db_session.scalars(select(User).where(User.email == email)).first() is not None:
            raise ValueError(f"an account already exists for '{email}' — log in instead")
        is_first_account = db_session.scalars(select(User.id).limit(1)).first() is None
        salt = secrets.token_hex(16)
        user = User(
            id=f"user-{secrets.token_hex(8)}", email=email, role="admin" if is_first_account else "recruiter",
            password_hash=_hash_password(password, salt), password_salt=salt,
        )
        db_session.add(user)
        db_session.commit()
        return {"id": user.id, "email": user.email, "role": user.role}


def verify_credentials(email: str, password: str) -> dict[str, Any] | None:
    with db.get_session() as db_session:
        user = db_session.scalars(select(User).where(User.email == email)).first()
        if user is None:
            return None
        if _hash_password(password, user.password_salt) != user.password_hash:
            return None
        return {"id": user.id, "email": user.email, "role": user.role}


def set_user_role(user_id: str, role: str) -> dict[str, Any]:
    """The one admin-only mutation this phase adds — see
    api.py's PATCH /users/{user_id}/role, gated by require_role("admin").
    Only "admin"/"recruiter" are assignable; "client"/"interviewer" are
    reserved for a later phase (see ASSIGNABLE_ROLES)."""
    if role not in ASSIGNABLE_ROLES:
        raise ValueError(f"'{role}' is not an assignable role — must be one of {ASSIGNABLE_ROLES}")
    with db.get_session() as db_session:
        user = db_session.get(User, user_id)
        if user is None:
            raise ValueError(f"user '{user_id}' not found")
        user.role = role
        db_session.commit()
        return {"id": user.id, "email": user.email, "role": user.role}


def list_users() -> list[dict[str, Any]]:
    """Admin-only account roster — see api.py's GET /users."""
    with db.get_session() as db_session:
        users = db_session.scalars(select(User).order_by(User.created_at)).all()
        return [{"id": u.id, "email": u.email, "role": u.role, "created_at": u.created_at} for u in users]


def create_session(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    with db.get_session() as db_session:
        db_session.add(Session(token=token, user_id=user_id, expires_at=datetime.now(UTC) + SESSION_TTL))
        db_session.commit()
    return token


def get_user_from_session(token: str) -> dict[str, Any] | None:
    if not token:
        return None
    with db.get_session() as db_session:
        session = db_session.get(Session, token)
        if session is None:
            return None
        expires_at = session.expires_at.replace(tzinfo=UTC) if session.expires_at.tzinfo is None else session.expires_at
        if expires_at < datetime.now(UTC):
            db_session.delete(session)
            db_session.commit()
            return None
        user = db_session.get(User, session.user_id)
        return {"id": user.id, "email": user.email, "role": user.role} if user else None


def delete_session(token: str) -> None:
    with db.get_session() as db_session:
        session = db_session.get(Session, token)
        if session is not None:
            db_session.delete(session)
            db_session.commit()


# ── Google Sign-In (optional) ────────────────────────────────────────────
# Verifies a Google Identity Services ID token obtained client-side; no
# client secret needed since we only verify a signed token, never do a
# server-side code exchange. Unset GTM_GOOGLE_CLIENT_ID (the default)
# means the "Continue with Google" button never appears — see
# api.py's /auth/status and /auth/google.
GOOGLE_CLIENT_ID = os.environ.get("GTM_GOOGLE_CLIENT_ID") or None
# Optional allowlist so a personal Gmail address can't self-provision an
# account into an internal workspace — e.g. GTM_GOOGLE_ALLOWED_DOMAIN=
# acme.com only accepts someone@acme.com. Unset (the default) accepts any
# verified Google account, same "open unless configured" default as
# SIGNUP_CODE above.
GOOGLE_ALLOWED_DOMAIN = os.environ.get("GTM_GOOGLE_ALLOWED_DOMAIN") or None


def _verify_google_id_token(credential: str) -> str:
    """Returns the verified, email_verified email from a Google Identity
    Services credential. A separate top-level function (not inlined into
    google_login) so tests can monkeypatch it instead of hitting Google's
    network endpoint — same "swap what's below" pattern as db_storage.py."""
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token

    claims = google_id_token.verify_oauth2_token(credential, google_requests.Request(), GOOGLE_CLIENT_ID)
    if not claims.get("email_verified"):
        raise ValueError("Google account email is not verified")
    return claims["email"]


def google_login(credential: str) -> dict[str, Any]:
    """Verify a Google Identity Services credential and get-or-create the
    matching account (password-less — password_hash/password_salt are
    still populated with an unusable random value so the column stays
    non-null, but this account can never log in with a password). Raises
    ValueError (mapped to 400 by the API layer) if Google sign-in isn't
    configured, the token is invalid, or the email's domain isn't
    allowlisted."""
    if GOOGLE_CLIENT_ID is None:
        raise ValueError("Google sign-in is not configured on this server")
    email = _verify_google_id_token(credential)
    if GOOGLE_ALLOWED_DOMAIN is not None and not email.lower().endswith(f"@{GOOGLE_ALLOWED_DOMAIN.lower()}"):
        raise ValueError(f"'{email}' is not on the allowed domain for this workspace")
    with db.get_session() as db_session:
        user = db_session.scalars(select(User).where(User.email == email)).first()
        if user is None:
            is_first_account = db_session.scalars(select(User.id).limit(1)).first() is None
            salt = secrets.token_hex(16)
            user = User(
                id=f"user-{secrets.token_hex(8)}", email=email, role="admin" if is_first_account else "recruiter",
                password_hash=_hash_password(secrets.token_urlsafe(32), salt), password_salt=salt,
            )
            db_session.add(user)
            db_session.commit()
        return {"id": user.id, "email": user.email, "role": user.role}
