"""Per-role workspace persistence. This is the only module that touches
the filesystem for role data (Architecture §4) — swapping JSON files for a
database later is a change here, not a pipeline-wide rewrite.

Each role is one file: workspace/<role_id>.json, holding one top-level key
per pipeline stage plus a `candidates` map keyed by candidate_id. Stage
functions read the current file, merge their new section in, and write
the whole file back — so a recruiter's hand-edits to an earlier section
are never clobbered by a later stage run (Architecture §1.3).
"""

import json
from pathlib import Path
from typing import Any

WORKSPACE_DIR = Path(__file__).resolve().parents[2] / "workspace"

STAGE_KEYS = (
    "job_description",
    "calibration",
    "icp",
    "talent_map",
    "screening",
    "outreach",
    "funnel",
)


def _role_path(role_id: str) -> Path:
    if not role_id or any(c in role_id for c in "/\\"):
        raise ValueError(f"invalid role_id: {role_id!r}")
    return WORKSPACE_DIR / f"{role_id}.json"


def load_role(role_id: str) -> dict[str, Any]:
    """Return the role's current workspace state, or an empty skeleton if
    this role hasn't been sourced before."""
    path = _role_path(role_id)
    if not path.exists():
        return {"role_id": role_id, "candidates": {}, "prioritizations": {}}
    return json.loads(path.read_text())


def save_role(role_id: str, state: dict[str, Any]) -> None:
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    path = _role_path(role_id)
    path.write_text(json.dumps(state, indent=2, default=str))


def require_section(role_id: str, key: str) -> Any:
    """Read a section that a later stage depends on, raising a clear error
    if the upstream checkpoint hasn't run yet (Architecture §1.3) instead
    of letting a stage proceed against missing/None data."""
    state = load_role(role_id)
    value = state.get(key)
    if not value:
        raise ValueError(
            f"role '{role_id}' has no '{key}' yet — run that stage first "
            f"(see README.md pipeline order)"
        )
    return value


def merge_section(role_id: str, key: str, value: Any) -> dict[str, Any]:
    """Read-modify-write a single top-level section. Used by every stage
    so stages never need to hold the whole workspace state in memory
    across a call, and never race each other on unrelated sections."""
    state = load_role(role_id)
    state[key] = value
    save_role(role_id, state)
    return state


def merge_candidate(role_id: str, candidate_id: str, value: dict[str, Any]) -> dict[str, Any]:
    state = load_role(role_id)
    state.setdefault("candidates", {})[candidate_id] = value
    save_role(role_id, state)
    return state


def merge_prioritization(role_id: str, candidate_id: str, value: dict[str, Any]) -> dict[str, Any]:
    state = load_role(role_id)
    state.setdefault("prioritizations", {})[candidate_id] = value
    save_role(role_id, state)
    return state
