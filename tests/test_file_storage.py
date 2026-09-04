"""Covers file_storage.py's S3-compatible object storage for resume
files (Batch 4, production readiness). Uses moto to mock S3 — no real
cloud credentials needed, and no real network calls.
"""

import boto3
import pytest
from moto import mock_aws

from gtm_sourcing_agent import file_storage

BUCKET = "talyn-resumes-test"


@pytest.fixture
def unconfigured(monkeypatch):
    for var in (
        file_storage.ENV_ENDPOINT_URL,
        file_storage.ENV_BUCKET,
        file_storage.ENV_ACCESS_KEY_ID,
        file_storage.ENV_SECRET_ACCESS_KEY,
        file_storage.ENV_REGION,
    ):
        monkeypatch.delenv(var, raising=False)
    file_storage._client = None
    file_storage._client_env_key = None


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv(file_storage.ENV_BUCKET, BUCKET)
    monkeypatch.setenv(file_storage.ENV_ACCESS_KEY_ID, "test-access-key")
    monkeypatch.setenv(file_storage.ENV_SECRET_ACCESS_KEY, "test-secret-key")
    monkeypatch.setenv(file_storage.ENV_REGION, "us-east-1")
    monkeypatch.delenv(file_storage.ENV_ENDPOINT_URL, raising=False)
    file_storage._client = None
    file_storage._client_env_key = None
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
        yield
    file_storage._client = None
    file_storage._client_env_key = None


def test_is_configured_false_when_env_vars_missing(unconfigured):
    assert file_storage.is_configured() is False


def test_is_configured_true_when_all_env_vars_set(configured):
    assert file_storage.is_configured() is True


def test_upload_resume_returns_none_when_not_configured(unconfigured):
    assert file_storage.upload_resume("role-1", "resume.pdf", b"pdf bytes", "application/pdf") is None


def test_get_resume_download_url_returns_none_when_not_configured(unconfigured):
    assert file_storage.get_resume_download_url("resumes/role-1/whatever.pdf") is None


def test_upload_resume_round_trips_content(configured):
    key = file_storage.upload_resume("role-1", "resume.pdf", b"pdf bytes here", "application/pdf")
    assert key is not None
    assert key.startswith("resumes/role-1/")
    assert key.endswith("-resume.pdf")

    client = boto3.client("s3", region_name="us-east-1")
    obj = client.get_object(Bucket=BUCKET, Key=key)
    assert obj["Body"].read() == b"pdf bytes here"
    assert obj["ContentType"] == "application/pdf"


def test_upload_resume_keys_are_unique_per_call(configured):
    key1 = file_storage.upload_resume("role-1", "resume.pdf", b"a", "application/pdf")
    key2 = file_storage.upload_resume("role-1", "resume.pdf", b"b", "application/pdf")
    assert key1 != key2


def test_get_resume_download_url_returns_a_usable_url(configured):
    key = file_storage.upload_resume("role-1", "resume.pdf", b"pdf bytes", "application/pdf")
    url = file_storage.get_resume_download_url(key)
    assert url is not None
    assert BUCKET in url
    assert key.split("/")[-1] in url
