"""
tests/test_graph.py
-------------------
Integration test for the Phase 2 orchestrator skeleton.

Verifies that the LangGraph StateGraph compiles, all stub nodes execute
in the correct order, and the final state reflects each node's output.

No real database connection or LLM API key is required — stub agents
never access self.db or self.llm, so no external services are needed.
"""
from __future__ import annotations

from orchestrator.graph import run_campaign


def test_campaign_runs_end_to_end() -> None:
    """Full pipeline smoke test using all stub agents.

    Stubs return empty lists so the conditional edge routes
    harvester → risk_scorer → decision → notifier → audit
    (human_review is skipped because decisions == []).

    Status transitions verify each node executed in order:
      created → harvesting → scoring → deciding → notifying → auditing
    """
    result = run_campaign("test-001", "Test Campaign")

    # ------------------------------------------------------------------ #
    # Identity                                                             #
    # ------------------------------------------------------------------ #
    assert result["campaign_id"] == "test-001"
    assert result["campaign_name"] == "Test Campaign"

    # ------------------------------------------------------------------ #
    # Final status — last stub (AuditAgent) sets "auditing".              #
    # TODO Phase 6: update assertion to "completed" once AuditAgent       #
    # writes the final DB record and transitions to COMPLETED.            #
    # ------------------------------------------------------------------ #
    assert result["status"] == "auditing"  # TODO Phase 6: update to "completed"

    # ------------------------------------------------------------------ #
    # Stub outputs — each agent returned its expected empty/false values  #
    # ------------------------------------------------------------------ #
    assert result["entitlements"] == []          # HarvesterAgent stub
    assert result["scored_entitlements"] == []   # RiskScorerAgent stub
    assert result["decisions"] == []             # DecisionAgent stub
    assert result["pending_human_review"] == []  # no revokes → human_review skipped
    assert result["notified"] is False           # NotifierAgent stub
    assert result["audit_complete"] is False     # AuditAgent stub

    # ------------------------------------------------------------------ #
    # Error field must be clear                                           #
    # ------------------------------------------------------------------ #
    assert result["error"] is None

    # ------------------------------------------------------------------ #
    # Timestamp must be present and non-empty                             #
    # ------------------------------------------------------------------ #
    assert result["created_at"]
    assert isinstance(result["created_at"], str)
