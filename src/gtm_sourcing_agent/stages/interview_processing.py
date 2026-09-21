"""Interview Intelligence, Phase 1 (Notetaker) pipeline: recorded audio
-> speaker-labeled transcript -> recruitment-specific summary. Runs as a
single task_queue runner (see api.py's "process_interview" task kind)
rather than several chained tasks — a linear function is easier to
reason about and retry than an event-driven multi-stage pipeline, and
this product deliberately avoids that complexity (see task_queue.py's
own module docstring).

Unlike every other stage in this package, this one doesn't take a
`storage_backend=` kwarg — db_storage's interview functions are the
only implementation (no file-backed storage.py equivalent exists for
interviews, since the feature was built after storage.py was already
frozen in favor of db_storage.py everywhere), so importing db_storage
directly here doesn't lose any real swappability.
"""

from .. import db_storage, file_storage, llm_client, transcription
from ..models import InterviewSummaryResult


def run(interview_id: str) -> dict:
    interview = db_storage.get_interview(interview_id)
    if interview is None:
        raise ValueError(f"interview '{interview_id}' not found")
    if not interview["recording_file_key"]:
        raise ValueError(f"interview '{interview_id}' has no recording to process")

    db_storage.update_interview(interview_id, transcript_status="processing", error=None)

    audio_bytes = file_storage.download_file(interview["recording_file_key"])
    if audio_bytes is None:
        db_storage.update_interview(
            interview_id, status="failed", transcript_status="failed",
            error="the recording could not be retrieved from storage",
        )
        raise RuntimeError("the recording could not be retrieved from storage")

    try:
        segments = transcription.transcribe(
            audio_bytes, interview["recording_content_type"] or "audio/webm"
        )
    except transcription.TranscriptionError as e:
        db_storage.update_interview(interview_id, status="failed", transcript_status="failed", error=str(e))
        raise RuntimeError(str(e)) from e

    # A retry (api.py's /interviews/{id}/retry) re-enters here with old
    # segments from a previous attempt still in the table — clear them
    # first so a retry never doubles up the transcript.
    db_storage.delete_transcript_segments(interview_id)
    db_storage.save_transcript_segments(interview_id, segments)
    db_storage.update_interview(interview_id, transcript_status="completed")

    if not segments:
        # Real, if rare (e.g. a silent/empty recording) — surface it
        # honestly rather than generating a summary from nothing.
        db_storage.update_interview(
            interview_id, status="failed",
            error="transcription produced no speech — the recording may be silent or too short",
        )
        raise RuntimeError("transcription produced no speech")

    transcript_text = "\n".join(f"{s['speaker'].upper()}: {s['text']}" for s in segments)
    prompt = llm_client.render_prompt("interview_summary.md", transcript_text=transcript_text)
    result = llm_client.generate(prompt, InterviewSummaryResult, stage="interview_summary")

    db_storage.update_interview(interview_id, summary=result.model_dump(), status="completed")
    return {"summary": result.model_dump(), "segment_count": len(segments)}
