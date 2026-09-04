"""S3-compatible object storage for the original uploaded resume file
(Batch 4, production readiness). resume_extraction.py already turns an
upload into plain text independently, and candidate_analysis.py already
turns that text into structured candidate data — neither of those
depends on this module at all. This is purely additive: it lets a
recruiter open the original PDF/DOCX later, instead of only ever seeing
what the model extracted from it.

Configured entirely through environment variables so any S3-compatible
provider works — Cloudflare R2 is the recommended one (see
docs/deployment.md), but this talks to plain AWS S3 or any other
S3-compatible endpoint identically, since it's just boto3's S3 client
pointed at a configurable endpoint_url.

Never fakes success: if the required env vars aren't set, every
function here is a no-op that returns None, and callers treat that as
"not persisted in this environment" — never raise, never pretend a file
was stored when it wasn't.
"""

import logging
import os
import uuid

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

ENV_ENDPOINT_URL = "RESUME_STORAGE_ENDPOINT_URL"
ENV_BUCKET = "RESUME_STORAGE_BUCKET"
ENV_ACCESS_KEY_ID = "RESUME_STORAGE_ACCESS_KEY_ID"
ENV_SECRET_ACCESS_KEY = "RESUME_STORAGE_SECRET_ACCESS_KEY"
ENV_REGION = "RESUME_STORAGE_REGION"  # optional — R2 ignores it, but boto3's client requires some value

_client = None
_client_env_key: tuple[str | None, str | None, str | None] | None = None


def is_configured() -> bool:
    return bool(
        os.environ.get(ENV_BUCKET)
        and os.environ.get(ENV_ACCESS_KEY_ID)
        and os.environ.get(ENV_SECRET_ACCESS_KEY)
    )


def _get_client():
    """Lazily builds (and caches) the boto3 client. Rebuilds it if the
    relevant env vars change — this matters for tests, which monkeypatch
    them per-test rather than restarting the process."""
    global _client, _client_env_key
    key = (
        os.environ.get(ENV_ENDPOINT_URL),
        os.environ.get(ENV_ACCESS_KEY_ID),
        os.environ.get(ENV_SECRET_ACCESS_KEY),
    )
    if _client is None or key != _client_env_key:
        _client = boto3.client(
            "s3",
            endpoint_url=os.environ.get(ENV_ENDPOINT_URL) or None,
            aws_access_key_id=os.environ[ENV_ACCESS_KEY_ID],
            aws_secret_access_key=os.environ[ENV_SECRET_ACCESS_KEY],
            region_name=os.environ.get(ENV_REGION) or "auto",
            config=BotoConfig(signature_version="s3v4"),
        )
        _client_env_key = key
    return _client


def upload_resume(role_id: str, filename: str, content: bytes, content_type: str) -> str | None:
    """Uploads the original resume file. Namespaced by `role_id` rather
    than a candidate id — this runs synchronously in the upload request,
    before the async add_candidate task has created the candidate (see
    api.py's upload_candidate route), so no candidate id exists yet.

    Returns the storage key on success, or None if storage isn't
    configured in this environment — callers must treat None as "not
    persisted, and that's fine", never as an error; resume text
    extraction already happened independently and this upload is never
    on that critical path."""
    if not is_configured():
        return None
    bucket = os.environ[ENV_BUCKET]
    key = f"resumes/{role_id}/{uuid.uuid4().hex[:12]}-{filename}"
    try:
        _get_client().put_object(Bucket=bucket, Key=key, Body=content, ContentType=content_type)
    except (ClientError, BotoCoreError):
        logger.exception("resume upload failed for candidate %s", candidate_id)
        return None
    return key


def get_resume_download_url(file_key: str, expires_in: int = 3600) -> str | None:
    """A time-limited presigned URL the recruiter's browser can fetch
    directly — this app never proxies the file bytes, and the link is
    never permanently public. Returns None if storage isn't configured,
    or if generating the URL fails for any reason."""
    if not is_configured():
        return None
    bucket = os.environ[ENV_BUCKET]
    try:
        return _get_client().generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": file_key}, ExpiresIn=expires_in
        )
    except (ClientError, BotoCoreError):
        logger.exception("failed to generate a resume download URL for key %s", file_key)
        return None
