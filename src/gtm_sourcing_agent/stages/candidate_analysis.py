"""Stage 7: Candidate Identification / evidence capture. See
prompts/candidate_analysis.md. Takes recruiter-supplied source text —
this repo does not scrape candidate profiles (Architecture §7)."""

import json
import re
import unicodedata

from .. import llm_client, storage
from ..models import Candidate


def _slugify(name: str, role_id: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return f"{role_id}-{slug}"


def run(
    role_id: str,
    candidate_source_text: str,
    role_family: str,
    source_url: str = "",
    *,
    storage_backend=storage,
    resume_file_key: str | None = None,
    resume_filename: str | None = None,
) -> Candidate:
    icp = storage_backend.require_section(role_id, "icp")
    prompt = llm_client.render_prompt(
        "candidate_analysis.md",
        icp_json=json.dumps(icp),
        candidate_source_text=candidate_source_text,
        role_family=role_family,
    )
    result = llm_client.generate(prompt, Candidate, stage="candidate_analysis")
    if not result.candidate_id:
        result.candidate_id = _slugify(result.name, role_id)
    if source_url and not result.source_url:
        result.source_url = source_url
    storage_backend.merge_candidate(role_id, result.candidate_id, result.model_dump())
    # Auto-populate the same phone/email fields the WhatsApp/call handoff
    # reads (set_candidate_contact) so a recruiter never re-types contact
    # info the resume already gave us. None means "leave unchanged" —
    # only set when the extraction actually found something, and this
    # only runs at creation (before any recruiter correction could exist).
    # hasattr-guarded: the CLI's plain storage backend predates the
    # product layer's contact-info concept and doesn't implement this.
    if (result.email or result.phone) and hasattr(storage_backend, "set_candidate_contact"):
        storage_backend.set_candidate_contact(
            role_id, result.candidate_id, phone=result.phone or None, email=result.email or None
        )
    # Same hasattr guard, same reason: only the DB backend (Batch 4,
    # production readiness) knows how to record where the original
    # resume file landed in object storage. resume_file_key is None
    # whenever the candidate came from pasted text, or object storage
    # isn't configured — either way, there's nothing to record.
    if resume_file_key and hasattr(storage_backend, "set_candidate_resume"):
        storage_backend.set_candidate_resume(
            role_id, result.candidate_id, file_key=resume_file_key, filename=resume_filename or ""
        )
    return result
