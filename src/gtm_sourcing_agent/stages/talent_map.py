"""Stage 4-5: Talent Market Mapping + Title Intelligence. Populates
target_companies and title_intelligence on the TalentMap; search
strategies are added separately by stages/search_strategy.py so the two
can be regenerated independently. See prompts/talent_map.md."""

import json

from .. import llm_client, storage
from ..models import TalentMap


def run(role_id: str, *, storage_backend=storage) -> TalentMap:
    icp = storage_backend.require_section(role_id, "icp")
    prompt = llm_client.render_prompt("talent_map.md", icp_json=json.dumps(icp))
    result = llm_client.generate(prompt, TalentMap, stage="talent_map")

    existing = storage_backend.load_role(role_id).get("talent_map") or {}
    result.search_strategies = existing.get("search_strategies", []) or result.search_strategies
    storage_backend.merge_section(role_id, "talent_map", result.model_dump())
    return result
