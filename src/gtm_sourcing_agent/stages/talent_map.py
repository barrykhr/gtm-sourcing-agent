"""Stage 4-5: Talent Market Mapping + Title Intelligence. Populates
target_companies and title_intelligence on the TalentMap; search
strategies are added separately by stages/search_strategy.py so the two
can be regenerated independently. See prompts/talent_map.md."""

import json

from .. import llm_client, storage
from ..models import TalentMap

MIN_TARGET_COMPANIES = 15  # the prompt asks for >=5 per tier across 3 tiers


def run(role_id: str, *, storage_backend=storage) -> TalentMap:
    icp = storage_backend.require_section(role_id, "icp")
    prompt = llm_client.render_prompt("talent_map.md", icp_json=json.dumps(icp))
    result = llm_client.generate(prompt, TalentMap, stage="talent_map")

    if len(result.target_companies) < MIN_TARGET_COMPANIES:
        # One retry, with the shortfall spelled out — a real safety net
        # for thin coverage, not a way to pad the list with invented
        # companies. If the retry still comes up short, we keep it and
        # let the count speak for itself.
        total = len(result.target_companies)
        retry_prompt = prompt + (
            f"\n\nYour previous attempt returned only {total} target companies total — this role needs "
            f"at least {MIN_TARGET_COMPANIES} (5+ per tier). Cover more real companies across all three "
            f"tiers and try again."
        )
        retried = llm_client.generate(retry_prompt, TalentMap, stage="talent_map")
        if len(retried.target_companies) > total:
            result = retried

    existing = storage_backend.load_role(role_id).get("talent_map") or {}
    result.search_strategies = existing.get("search_strategies", []) or result.search_strategies
    storage_backend.merge_section(role_id, "talent_map", result.model_dump())
    return result
