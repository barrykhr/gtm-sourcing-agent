"""Provider-swappable speech-to-text + speaker diarization for interview
recordings (Interview Intelligence, Phase 1). AssemblyAI is the only
implementation today, chosen because its "utterances" response already
comes speaker-labeled with start/end timestamps — the shape this app
needs directly, no extra alignment step. To swap providers later,
implement a `transcribe(audio_bytes, content_type) -> list[Segment]`
function with the same contract and change what `transcribe()` below
calls — nothing in stages/interview_processing.py needs to change, same
"swap what's below" pattern as db_storage.py and file_storage.py.

Never fakes a transcript: if the provider isn't configured, or the API
call fails, this raises TranscriptionError rather than returning
placeholder text.
"""

import logging
import os
import time
from typing import Any, TypedDict

import httpx

logger = logging.getLogger(__name__)

ENV_ASSEMBLYAI_API_KEY = "ASSEMBLYAI_API_KEY"

_UPLOAD_URL = "https://api.assemblyai.com/v2/upload"
_TRANSCRIPT_URL = "https://api.assemblyai.com/v2/transcript"
_POLL_INTERVAL_SECONDS = 3
_POLL_TIMEOUT_SECONDS = 600  # a 30-45 min interview can take several minutes to transcribe


class Segment(TypedDict):
    speaker: str  # "recruiter" | "candidate" | "unknown"
    text: str
    start_time: float
    end_time: float


class TranscriptionError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(os.environ.get(ENV_ASSEMBLYAI_API_KEY))


def transcribe(audio_bytes: bytes, content_type: str) -> list[Segment]:
    """Uploads `audio_bytes` to AssemblyAI, requests a diarized
    transcript, and polls until it's done. Raises TranscriptionError on
    any failure — including "not configured" — since a caller silently
    treating a missing transcript as "nothing to show yet" would hide a
    real problem from the recruiter."""
    if not is_configured():
        raise TranscriptionError(f"transcription is not configured — set {ENV_ASSEMBLYAI_API_KEY}")
    api_key = os.environ[ENV_ASSEMBLYAI_API_KEY]
    headers = {"authorization": api_key}
    try:
        upload_resp = httpx.post(_UPLOAD_URL, headers=headers, content=audio_bytes, timeout=120)
        upload_resp.raise_for_status()
        upload_url = upload_resp.json()["upload_url"]

        submit_resp = httpx.post(
            _TRANSCRIPT_URL, headers=headers, json={"audio_url": upload_url, "speaker_labels": True}, timeout=30,
        )
        submit_resp.raise_for_status()
        transcript_id = submit_resp.json()["id"]
    except httpx.HTTPError as e:
        raise TranscriptionError(f"transcription request failed: {e}") from e

    poll_url = f"{_TRANSCRIPT_URL}/{transcript_id}"
    deadline = time.monotonic() + _POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            poll_resp = httpx.get(poll_url, headers=headers, timeout=30)
            poll_resp.raise_for_status()
        except httpx.HTTPError as e:
            raise TranscriptionError(f"transcription status check failed: {e}") from e
        data = poll_resp.json()
        status = data.get("status")
        if status == "completed":
            return _to_segments(data)
        if status == "error":
            raise TranscriptionError(data.get("error") or "transcription failed")
        time.sleep(_POLL_INTERVAL_SECONDS)
    raise TranscriptionError("transcription timed out")


def _to_segments(data: dict[str, Any]) -> list[Segment]:
    utterances = data.get("utterances") or []
    if not utterances:
        # Diarization can come back empty for very short/quiet audio even
        # when transcription itself succeeded — fall back to the plain
        # text as a single unlabeled segment rather than losing it.
        text = (data.get("text") or "").strip()
        return [Segment(speaker="unknown", text=text, start_time=0.0, end_time=0.0)] if text else []
    # AssemblyAI labels speakers "A"/"B"/... by acoustic identity, not
    # role — it has no idea who's the recruiter. The recruiter always
    # speaks first in this product's flow (they start the interview),
    # so map whichever label speaks first to "recruiter" as a starting
    # guess; the recruiter corrects labels afterward if it's wrong (see
    # db_storage.set_segment_speaker).
    first_label = utterances[0]["speaker"]
    label_map = {first_label: "recruiter"}
    segments: list[Segment] = []
    for u in utterances:
        speaker = label_map.setdefault(u["speaker"], "candidate")
        segments.append(Segment(
            speaker=speaker, text=u["text"], start_time=u["start"] / 1000.0, end_time=u["end"] / 1000.0,
        ))
    return segments
