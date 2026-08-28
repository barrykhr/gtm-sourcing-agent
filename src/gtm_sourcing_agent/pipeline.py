"""Documents and exposes the pipeline stage order (README's diagram) so
the CLI and any future caller has one place to check "what's the next
stage" / "what does this stage depend on" rather than re-deriving it.

This module does not force stages to run in order — the recruiter can
re-run any stage whose upstream dependency already exists in the
workspace file (Architecture §1.3, §3). It only documents dependencies
and gives a convenience `status()` view.
"""

from typing import Callable

from . import storage
from .stages import calibration, icp, intake, search_strategy, talent_map

# stage_name -> (module, "is this stage's output present?" check against
# the loaded workspace state)
ROLE_LEVEL_STAGES: dict[str, tuple[object, Callable[[dict], bool]]] = {
    "intake": (intake, lambda s: bool(s.get("job_description"))),
    "calibration": (calibration, lambda s: bool(s.get("calibration"))),
    "icp": (icp, lambda s: bool(s.get("icp"))),
    "talent_map": (talent_map, lambda s: bool((s.get("talent_map") or {}).get("target_companies"))),
    "search_strategy": (
        search_strategy,
        lambda s: bool((s.get("talent_map") or {}).get("search_strategies")),
    ),
}

# per-candidate stages are invoked directly via stages.candidate_analysis /
# stages.prioritization / stages.screening / stages.outreach — they take a
# candidate_id and aren't part of the linear role-level chain above.


def status(role_id: str, *, storage_backend=storage) -> dict[str, bool]:
    """Which role-level stages have output on disk for this role."""
    state = storage_backend.load_role(role_id)
    return {name: is_done(state) for name, (_, is_done) in ROLE_LEVEL_STAGES.items()}


def next_stage(role_id: str, *, storage_backend=storage) -> str | None:
    """The first role-level stage in order that hasn't produced output
    yet, or None if the linear chain is complete."""
    state = storage_backend.load_role(role_id)
    for name, (_, is_done) in ROLE_LEVEL_STAGES.items():
        if not is_done(state):
            return name
    return None
