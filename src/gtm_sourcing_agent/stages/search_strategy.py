"""Stage 6: Search Strategy generation. Regenerable independently of
target companies / title intelligence. See prompts/search_strategy.md."""

import json

from .. import llm_client, storage
from ..models import TalentMap


def run(role_id: str, *, storage_backend=storage) -> TalentMap:
    talent_map = storage_backend.require_section(role_id, "talent_map")
    prompt = llm_client.render_prompt("search_strategy.md", talent_map_json=json.dumps(talent_map))
    result = llm_client.generate(prompt, TalentMap, stage="search_strategy")

    existing = storage_backend.load_role(role_id)["talent_map"]
    merged = TalentMap(
        target_companies=existing.get("target_companies", []),
        title_intelligence=existing.get("title_intelligence", {}),
        search_strategies=result.search_strategies,
    )
    storage_backend.merge_section(role_id, "talent_map", merged.model_dump())
    return merged
