"""transcription.py — mocked at httpx.post/httpx.get, the two real
network calls this module makes, same pattern test_webhooks.py uses for
webhooks.py's one real network call. Never touches the real AssemblyAI
API."""

import httpx
import pytest

from gtm_sourcing_agent import transcription


class _FakeResponse:
    def __init__(self, json_data: dict, status_code: int = 200):
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)

    def json(self) -> dict:
        return self._json


def test_is_configured_false_by_default(monkeypatch):
    monkeypatch.delenv("ASSEMBLYAI_API_KEY", raising=False)
    assert transcription.is_configured() is False


def test_is_configured_true_when_set(monkeypatch):
    monkeypatch.setenv("ASSEMBLYAI_API_KEY", "test-key")
    assert transcription.is_configured() is True


def test_transcribe_raises_when_not_configured(monkeypatch):
    monkeypatch.delenv("ASSEMBLYAI_API_KEY", raising=False)
    with pytest.raises(transcription.TranscriptionError, match="not configured"):
        transcription.transcribe(b"fake audio bytes", "audio/webm")


def test_transcribe_happy_path_maps_first_speaker_to_recruiter(monkeypatch):
    monkeypatch.setenv("ASSEMBLYAI_API_KEY", "test-key")

    def fake_post(url, **kwargs):
        if url == transcription._UPLOAD_URL:
            return _FakeResponse({"upload_url": "https://cdn.assemblyai.com/upload/abc"})
        if url == transcription._TRANSCRIPT_URL:
            return _FakeResponse({"id": "transcript-123"})
        raise AssertionError(f"unexpected POST to {url}")

    def fake_get(url, **kwargs):
        assert url == f"{transcription._TRANSCRIPT_URL}/transcript-123"
        return _FakeResponse({
            "status": "completed",
            "utterances": [
                {"speaker": "A", "text": "Tell me about your n8n experience.", "start": 0, "end": 3200},
                {"speaker": "B", "text": "I built a lead enrichment workflow.", "start": 3500, "end": 7100},
                {"speaker": "A", "text": "Great, walk me through it.", "start": 7500, "end": 9000},
            ],
        })

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "get", fake_get)

    segments = transcription.transcribe(b"fake audio bytes", "audio/webm")

    assert segments == [
        {"speaker": "recruiter", "text": "Tell me about your n8n experience.", "start_time": 0.0, "end_time": 3.2},
        {"speaker": "candidate", "text": "I built a lead enrichment workflow.", "start_time": 3.5, "end_time": 7.1},
        {"speaker": "recruiter", "text": "Great, walk me through it.", "start_time": 7.5, "end_time": 9.0},
    ]


def test_transcribe_falls_back_to_plain_text_when_no_utterances(monkeypatch):
    monkeypatch.setenv("ASSEMBLYAI_API_KEY", "test-key")

    def fake_post(url, **kwargs):
        if url == transcription._UPLOAD_URL:
            return _FakeResponse({"upload_url": "https://cdn.assemblyai.com/upload/abc"})
        return _FakeResponse({"id": "transcript-123"})

    def fake_get(url, **kwargs):
        return _FakeResponse({"status": "completed", "utterances": [], "text": "hello there"})

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "get", fake_get)

    segments = transcription.transcribe(b"fake audio bytes", "audio/webm")
    assert segments == [{"speaker": "unknown", "text": "hello there", "start_time": 0.0, "end_time": 0.0}]


def test_transcribe_empty_text_and_no_utterances_returns_no_segments(monkeypatch):
    monkeypatch.setenv("ASSEMBLYAI_API_KEY", "test-key")
    monkeypatch.setattr(httpx, "post", lambda url, **kwargs: _FakeResponse({"upload_url": "x", "id": "t-1"}))
    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: _FakeResponse({"status": "completed", "utterances": [], "text": ""}))
    assert transcription.transcribe(b"fake audio bytes", "audio/webm") == []


def test_transcribe_raises_on_provider_error_status(monkeypatch):
    monkeypatch.setenv("ASSEMBLYAI_API_KEY", "test-key")
    monkeypatch.setattr(httpx, "post", lambda url, **kwargs: _FakeResponse({"upload_url": "x", "id": "t-1"}))
    monkeypatch.setattr(
        httpx, "get", lambda url, **kwargs: _FakeResponse({"status": "error", "error": "audio too short"})
    )
    with pytest.raises(transcription.TranscriptionError, match="audio too short"):
        transcription.transcribe(b"fake audio bytes", "audio/webm")


def test_transcribe_raises_on_http_error_during_upload(monkeypatch):
    monkeypatch.setenv("ASSEMBLYAI_API_KEY", "test-key")

    def fake_post(url, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(transcription.TranscriptionError, match="transcription request failed"):
        transcription.transcribe(b"fake audio bytes", "audio/webm")


def test_transcribe_polls_until_completed(monkeypatch):
    monkeypatch.setenv("ASSEMBLYAI_API_KEY", "test-key")
    monkeypatch.setattr(transcription.time, "sleep", lambda _seconds: None)  # no real waiting in tests
    call_count = {"n": 0}

    def fake_get(url, **kwargs):
        call_count["n"] += 1
        if call_count["n"] < 3:
            return _FakeResponse({"status": "processing"})
        return _FakeResponse({
            "status": "completed",
            "utterances": [{"speaker": "A", "text": "hi", "start": 0, "end": 500}],
        })

    monkeypatch.setattr(httpx, "post", lambda url, **kwargs: _FakeResponse({"upload_url": "x", "id": "t-1"}))
    monkeypatch.setattr(httpx, "get", fake_get)

    segments = transcription.transcribe(b"fake audio bytes", "audio/webm")
    assert call_count["n"] == 3
    assert segments[0]["speaker"] == "recruiter"
