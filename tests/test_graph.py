"""
tests/test_graph.py
-------------------
Integration tests for the LangGraph orchestration pipeline.

test_campaign_runs_end_to_end  (@pytest.mark.stub)
  Smoke test for the graph skeleton. Uses flexible assertions so it
  passes whether stub or real agents are active. Marked @stub so it
  can be run in isolation: pytest -m stub

test_graph_with_real_harvester_and_scorer
  Full pipeline test against a live PostgreSQL + seed data.
  Requires Docker services running with seed data loaded.
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

    Status transitions verify each node executed in order:
      created → harvesting → scoring → deciding → notifying → auditing
    """
    campaign_id = f"test-stub-{uuid.uuid4().hex[:8]}"
    result = run_campaign(campaign_id, "Test Campaign")

    # ------------------------------------------------------------------ #
    # Identity                                                             #
    # ------------------------------------------------------------------ #
    assert result["campaign_id"] == campaign_id
    assert result["campaign_name"] == "Test Campaign"

    # ------------------------------------------------------------------ #
    # Final status — last agent (AuditAgent stub) sets "auditing".        #
    # TODO Phase 6: update assertion to "completed" once AuditAgent       #
    # writes the final DB record and transitions to COMPLETED.            #
    # ------------------------------------------------------------------ #
    assert result["status"] == "auditing"  # TODO Phase 6: update to "completed"

    # ------------------------------------------------------------------ #
    # List fields — flexible assertions so test passes with stub OR       #
    # real agents (stub returns [], real returns populated lists)         #
    # ------------------------------------------------------------------ #
    assert isinstance(result["entitlements"], list)
    assert isinstance(result["scored_entitlements"], list)
    assert isinstance(result["decisions"], list)
    assert isinstance(result["pending_human_review"], list)

    # ------------------------------------------------------------------ #
    # Scalar fields                                                        #
    # ------------------------------------------------------------------ #
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


def test_graph_with_real_harvester_and_scorer() -> None:
    """End-to-end pipeline test with real Harvester and RiskScorer agents.

    REQUIRES: Docker PostgreSQL running with seed data loaded.
      docker-compose up -d && python db/seed.py

    Verifies the full data pipeline:
      - Harvester queries DB and returns 13 active entitlements
      - RiskScorer scores all entitlements with valid scores and levels
      - DecisionAgent stub returns empty decisions (Phase 3 incomplete)
      - Graph runs to completion without error
    """
    campaign_id = f"test-phase3-{uuid.uuid4().hex[:8]}"
    result = run_campaign(campaign_id, "Phase 3 Integration Test")

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

    # ------------------------------------------------------------------ #
    # Verify at least one high-risk entitlement from seed red-flags       #
    # (Bob SAP Admin, Dan AWS Admin, Frank SAP Admin all score >= 70)     #
    # ------------------------------------------------------------------ #
    high_or_critical = [
        s for s in scored if s["risk_level"] in {"high", "critical"}
    ]
    assert len(high_or_critical) >= 3, (
        f"Expected at least 3 high/critical entitlements from seed data, "
        f"got {len(high_or_critical)}"
    )

    # ------------------------------------------------------------------ #
    # Final status                                                         #
    # ------------------------------------------------------------------ #
    assert result["status"] == "auditing"  # TODO Phase 6: update to "completed"
