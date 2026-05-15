"""
tests/test_graph.py
-------------------
Integration tests for the LangGraph orchestration pipeline.

test_campaign_runs_end_to_end  (@pytest.mark.stub)
  Smoke test for the graph skeleton. Uses flexible assertions so it
  passes whether stub or real agents are active. Marked @stub so it
  can be run in isolation: pytest -m stub

test_graph_with_real_harvester_and_scorer
  Full pipeline test against live PostgreSQL + live LLM.
  Requires Docker services running with seed data loaded and a valid
  ANTHROPIC_API_KEY (or OPENAI_API_KEY) in .env.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from orchestrator.graph import run_campaign


@pytest.mark.stub
def test_campaign_runs_end_to_end() -> None:
    """Full pipeline smoke test — flexible assertions for stub or real agents.

    Uses a unique campaign_id each run to avoid UNIQUE constraint
    conflicts on langgraph_thread_id.

    With a real LLM (e.g. llama3.1:8b), revoke decisions correctly trigger
    the HITL checkpoint via interrupt(). The graph pauses with
    status="deciding" rather than reaching "completed". Both outcomes are
    valid — this test accepts either.
    """
    campaign_id = f"test-stub-{uuid.uuid4().hex[:8]}"
    result = run_campaign(campaign_id, "Test Campaign")

    assert result["campaign_id"] == campaign_id
    assert result["campaign_name"] == "Test Campaign"
    assert isinstance(result["entitlements"], list)
    assert isinstance(result["scored_entitlements"], list)
    assert isinstance(result["decisions"], list)
    assert isinstance(result["pending_human_review"], list)
    assert result["error"] is None
    # With a real LLM revoke decisions trigger the HITL checkpoint;
    # both "completed" (no revokes) and "deciding" (revokes present) are valid.
    assert result["status"] in {"completed", "deciding"}


def test_graph_with_real_harvester_and_scorer() -> None:
    """End-to-end pipeline test with all real agents (Phase 4 complete).

    REQUIRES:
      - Docker PostgreSQL running with seed data loaded
          docker-compose up -d && python -m db.seed
      - Valid API key in .env (ANTHROPIC_API_KEY or OPENAI_API_KEY)

    Verifies the full data pipeline:
      - Harvester queries DB → 13 active entitlements
      - RiskScorer scores all entitlements deterministically
      - DecisionAgent makes LLM-driven approve/revoke/escalate decisions
      - NotifierAgent drafts manager emails via LLM
      - AuditAgent writes audit trail and marks Campaign COMPLETED
    """
    campaign_id = f"test-phase4-{uuid.uuid4().hex[:8]}"
    result = run_campaign(campaign_id, "Phase 4 Integration Test")

    assert result["error"] is None, (
        f"Pipeline failed with error: {result.get('error')}"
    )

    # ------------------------------------------------------------------ #
    # Harvester output                                                     #
    # ------------------------------------------------------------------ #
    entitlements = result["entitlements"]
    assert len(entitlements) > 0, "Expected real entitlements from DB, got none"

    # ------------------------------------------------------------------ #
    # RiskScorer output                                                    #
    # ------------------------------------------------------------------ #
    scored = result["scored_entitlements"]
    assert len(scored) == len(entitlements), (
        f"scored_entitlements count ({len(scored)}) != "
        f"entitlements count ({len(entitlements)})"
    )

    for item in scored:
        assert 0 <= item["risk_score"] <= 100, (
            f"risk_score out of range: {item['risk_score']} for {item['resource_name']}"
        )
        assert item["risk_level"] in {"low", "medium", "high", "critical"}, (
            f"Invalid risk_level: {item['risk_level']!r}"
        )
        assert isinstance(item["flags"], list)

    # Verify at least 3 high/critical from seed red-flags
    high_or_critical = [s for s in scored if s["risk_level"] in {"high", "critical"}]
    assert len(high_or_critical) >= 3, (
        f"Expected at least 3 high/critical entitlements from seed data, "
        f"got {len(high_or_critical)}"
    )

    # ------------------------------------------------------------------ #
    # DecisionAgent output (Phase 4)                                      #
    # ------------------------------------------------------------------ #
    decisions = result["decisions"]
    assert len(decisions) > 0, "Expected LLM decisions, got none"
    assert len(decisions) == len(scored), (
        f"decisions count ({len(decisions)}) != scored count ({len(scored)})"
    )

    assert all(
        d["ai_decision"] in {"approve", "revoke", "escalate"}
        for d in decisions
    ), "All decisions must be approve/revoke/escalate"

    assert all(
        "ai_reasoning" in d and isinstance(d["ai_reasoning"], str)
        for d in decisions
    ), "All decisions must have ai_reasoning string"

    assert all(
        0.0 <= d["confidence"] <= 1.0
        for d in decisions
    ), "All confidence scores must be in [0.0, 1.0]"

    # ------------------------------------------------------------------ #
    # AuditAgent / HITL outcome (Phase 4)                                 #
    # ------------------------------------------------------------------ #
    revoke_count = sum(1 for d in decisions if d["ai_decision"] == "revoke")
    if revoke_count == 0:
        assert result["status"] == "completed"
        assert result["audit_complete"] is True
        assert result["notified"] is True
    else:
        assert result["status"] == "deciding"
        assert len(result["pending_human_review"]) == revoke_count
        assert all(d["human_decision"] is None for d in result["pending_human_review"])
        assert all(d["human_reviewer"] is None for d in result["pending_human_review"])
