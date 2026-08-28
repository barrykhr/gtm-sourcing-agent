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
    return result
