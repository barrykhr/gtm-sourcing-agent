"""Phase 3: chat orchestrator. Tests never touch the real Anthropic API or
its SDK response objects — see orchestrator.py's module docstring for why.
TOOL_IMPLS are plain functions tested directly (proving the tool logic and
job-scoping is correct); run_chat_turn is tested with _run_tool_loop
mocked to a fixed (messages, final_text, tool_calls) tuple, simulating
what the model would have decided, to prove the *plumbing* around a
decision is correct without claiming anything about decision quality."""

import json

import anthropic
import httpx
import pytest

from gtm_sourcing_agent import db, db_storage, orchestrator


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    return tmp_path


# ── TOOL_IMPLS: the actual logic behind each tool, LLM-independent ──────


def test_list_candidates_tool_reflects_stored_state(isolated_db):
    db_storage.merge_section("job-a", "icp", {"must_have": ["SaaS"]})
    db_storage.merge_candidate("job-a", "cand-1", {"name": "Jane", "current_title": "AE", "current_company": "Acme"})
    db_storage.merge_prioritization("job-a", "cand-1", {"candidate_id": "cand-1", "tier": "A"})

    result = json.loads(orchestrator.TOOL_IMPLS["list_candidates"]("job-a", db_storage))
    assert result == [{"candidate_id": "cand-1", "name": "Jane", "current_title": "AE", "current_company": "Acme", "tier": "A"}]


def test_get_candidate_tool_returns_error_json_for_unknown_id(isolated_db):
    result = json.loads(orchestrator.TOOL_IMPLS["get_candidate"]("job-a", db_storage, "nope"))
    assert "error" in result


def test_prioritize_candidate_tool_never_lets_a_bad_call_crash_silently(isolated_db):
    db_storage.merge_section("job-a", "icp", {"must_have": ["SaaS"]})
    db_storage.merge_candidate("job-a", "cand-1", {"name": "Jane"})  # so "candidates" isn't empty
    with pytest.raises(ValueError, match="not found"):
        orchestrator.TOOL_IMPLS["prioritize_candidate"]("job-a", db_storage, "cand-missing")


def test_propose_hiring_profile_edit_is_read_only(isolated_db):
    db_storage.merge_section("job-a", "icp", {"must_have": ["SaaS", "Enterprise"]})

    result = json.loads(
        orchestrator.TOOL_IMPLS["propose_hiring_profile_edit"](
            "job-a", db_storage, "must_have", "remove", "SaaS"
        )
    )

    assert result["proposal"]["field"] == "must_have"
    assert result["proposal"]["action"] == "remove"
    # the ICP must be completely unchanged - this tool only proposes
    assert db_storage.load_role("job-a")["icp"]["must_have"] == ["SaaS", "Enterprise"]


def test_propose_hiring_profile_edit_flags_impact_when_candidates_evaluated(isolated_db):
    db_storage.merge_section("job-a", "icp", {"must_have": ["SaaS"]})
    db_storage.merge_candidate("job-a", "cand-1", {"name": "Jane"})
    db_storage.merge_prioritization("job-a", "cand-1", {"candidate_id": "cand-1", "tier": "B"})

    result = json.loads(
        orchestrator.TOOL_IMPLS["propose_hiring_profile_edit"]("job-a", db_storage, "must_have", "remove", "SaaS")
    )
    assert "1 candidate" in result["proposal"]["impact"]


def test_propose_hiring_profile_edit_rejects_removing_something_not_present(isolated_db):
    db_storage.merge_section("job-a", "icp", {"must_have": ["SaaS"]})
    result = json.loads(
        orchestrator.TOOL_IMPLS["propose_hiring_profile_edit"]("job-a", db_storage, "must_have", "remove", "Fabric")
    )
    assert "error" in result


def test_propose_hiring_profile_edit_rejects_unknown_field(isolated_db):
    db_storage.merge_section("job-a", "icp", {"must_have": ["SaaS"]})
    result = json.loads(
        orchestrator.TOOL_IMPLS["propose_hiring_profile_edit"]("job-a", db_storage, "salary", "remove", "x")
    )
    assert "error" in result


# ── apply_hiring_profile_edit: the deterministic mutation ────────────────


def test_apply_hiring_profile_edit_actually_mutates(isolated_db):
    db_storage.merge_section("job-a", "icp", {"must_have": ["SaaS", "Fabric"]})
    result = orchestrator.apply_hiring_profile_edit("job-a", "must_have", "remove", "Fabric")
    assert result["must_have"] == ["SaaS"]
    assert db_storage.load_role("job-a")["icp"]["must_have"] == ["SaaS"]


def test_apply_hiring_profile_edit_add_is_idempotent(isolated_db):
    db_storage.merge_section("job-a", "icp", {"must_have": ["SaaS"]})
    orchestrator.apply_hiring_profile_edit("job-a", "must_have", "add", "SaaS")
    assert db_storage.load_role("job-a")["icp"]["must_have"] == ["SaaS"]  # not duplicated


# ── run_chat_turn: plumbing around a (simulated) model decision ─────────


def test_run_chat_turn_passes_through_reply_with_no_tool_calls(isolated_db, monkeypatch):
    def fake_loop(model, system, tools, messages):
        messages.append({"role": "assistant", "content": [{"type": "text", "text": "Hi, how can I help?"}]})
        return messages, "Hi, how can I help?", []

    monkeypatch.setattr(orchestrator, "_run_tool_loop", fake_loop)

    result = orchestrator.run_chat_turn("job-a", "hello", [])
    assert result["reply"] == "Hi, how can I help?"
    assert result["pending_proposal"] is None
    assert result["history"][-1]["content"][0]["text"] == "Hi, how can I help?"


def test_run_chat_turn_surfaces_a_pending_proposal(isolated_db, monkeypatch):
    db_storage.merge_section("job-a", "icp", {"must_have": ["SaaS", "Fabric"]})

    def fake_loop(model, system, tools, messages):
        # simulate the model deciding to call propose_hiring_profile_edit,
        # by actually invoking the real tool logic through the tools list
        # the same way build_tools_for_job wired it - proves the closures
        # are correctly bound to job_a's storage, not just that the test
        # fabricated a plausible-looking result.
        tool = next(t for t in tools if t.name == "propose_hiring_profile_edit")
        result_str = tool(field="must_have", action="remove", value="Fabric")
        messages.append({"role": "assistant", "content": [
            {"type": "text", "text": "Here's what that change would do:"},
            {"type": "tool_use", "id": "tu_1", "name": "propose_hiring_profile_edit",
             "input": {"field": "must_have", "action": "remove", "value": "Fabric"}},
        ]})
        return messages, "Here's what that change would do:", [
            {"name": "propose_hiring_profile_edit", "input": {}, "id": "tu_1", "result": result_str}
        ]

    monkeypatch.setattr(orchestrator, "_run_tool_loop", fake_loop)

    result = orchestrator.run_chat_turn("job-a", "remove Fabric as a mandatory requirement", [])

    assert result["pending_proposal"]["field"] == "must_have"
    assert result["pending_proposal"]["value"] == "Fabric"
    assert result["pending_proposal"]["role_id"] == "job-a"
    # and, again, the ICP must still be untouched - only the confirm step applies it
    assert db_storage.load_role("job-a")["icp"]["must_have"] == ["SaaS", "Fabric"]


def test_run_chat_turn_no_pending_proposal_when_tool_call_was_something_else(isolated_db, monkeypatch):
    db_storage.merge_section("job-a", "icp", {"must_have": ["SaaS"]})

    def fake_loop(model, system, tools, messages):
        result_str = orchestrator.TOOL_IMPLS["list_candidates"]("job-a", db_storage)
        return messages, "No candidates yet.", [
            {"name": "list_candidates", "input": {}, "id": "tu_1", "result": result_str}
        ]

    monkeypatch.setattr(orchestrator, "_run_tool_loop", fake_loop)
    result = orchestrator.run_chat_turn("job-a", "who have we got so far?", [])
    assert result["pending_proposal"] is None


def test_run_chat_turn_ignores_error_proposals(isolated_db, monkeypatch):
    db_storage.merge_section("job-a", "icp", {"must_have": ["SaaS"]})

    def fake_loop(model, system, tools, messages):
        result_str = orchestrator.TOOL_IMPLS["propose_hiring_profile_edit"](
            "job-a", db_storage, "must_have", "remove", "NotThere"
        )
        return messages, "That's not currently a requirement.", [
            {"name": "propose_hiring_profile_edit", "input": {}, "id": "tu_1", "result": result_str}
        ]

    monkeypatch.setattr(orchestrator, "_run_tool_loop", fake_loop)
    result = orchestrator.run_chat_turn("job-a", "remove NotThere", [])
    assert result["pending_proposal"] is None


# ── _run_tool_loop: Anthropic SDK errors must map to friendly RuntimeError,
# not propagate raw (they aren't ValueError/RuntimeError, so api.py's
# _run_stage wouldn't catch them — this was a real bug: the copilot's own
# model call had no error handling, unlike every other stage's
# llm_client.generate(), so any Anthropic API failure surfaced as an
# opaque 500 instead of a clear message). ──────────────────────────────


def test_run_tool_loop_maps_authentication_error_to_runtime_error(monkeypatch):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")

    class _ExplodingRunner:
        def __iter__(self):
            return self

        def __next__(self):
            raise anthropic.APIConnectionError(request=request)

    class _FakeMessages:
        def tool_runner(self, **kwargs):
            return _ExplodingRunner()

    class _FakeBeta:
        messages = _FakeMessages()

    class _FakeClient:
        beta = _FakeBeta()

    monkeypatch.setattr(orchestrator, "_get_client", lambda: _FakeClient())

    with pytest.raises(RuntimeError, match="Network error calling the Anthropic API"):
        orchestrator._run_tool_loop("claude-sonnet-5", "system", [], [])
