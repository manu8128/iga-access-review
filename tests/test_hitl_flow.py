"""
tests/test_hitl_flow.py
-----------------------
Full interrupt → human review → resume integration test.

REQUIRES:
  - Docker PostgreSQL running with seed data loaded:
      docker-compose up -d && python -m db.seed
  - Valid LLM config in .env (e.g. LLM_PROVIDER=ollama, LLM_MODEL=llama3.1:8b)
  - Ollama running locally (or another provider with a real API key)

This test is skipped automatically if the LLM produces no revoke decisions
(HITL is only triggered when at least one revoke exists).
"""
from __future__ import annotations

import uuid

import pytest

from db.models import Campaign, CampaignStatus
from db.session import SessionLocal
from orchestrator.graph import get_campaign_state, resume_campaign, run_campaign


def test_full_hitl_flow() -> None:
    """Test complete interrupt → human review → resume flow.

    Steps:
    1. Start campaign — graph runs until human_review interrupt
    2. Verify state is persisted in PostgreSQL checkpointer
    3. Submit human decisions via resume_campaign()
    4. Verify graph completes: notifier + audit run
    5. Verify Campaign status is COMPLETED in DB
    """
    campaign_id = f"test-hitl-{uuid.uuid4().hex[:8]}"

    # ------------------------------------------------------------------ #
    # Step 1: Run until interrupt (or completion if no revokes)           #
    # ------------------------------------------------------------------ #
    result = run_campaign(campaign_id, "HITL Flow Test")

    # If no revoke decisions were generated, the HITL path is not triggered.
    # Skip rather than fail — this is LLM-non-deterministic.
    if result.get("status") == "completed":
        pytest.skip("No revoke decisions produced — HITL not triggered")

    # ------------------------------------------------------------------ #
    # Step 2: Verify paused state                                         #
    # ------------------------------------------------------------------ #
    assert result["status"] == "deciding", (
        f"Expected status='deciding' after HITL interrupt, got {result['status']!r}"
    )
    pending = result["pending_human_review"]
    assert len(pending) > 0, "Expected pending_human_review items after interrupt"

    # ------------------------------------------------------------------ #
    # Step 3: Verify state is retrievable from PostgreSQL checkpointer    #
    # ------------------------------------------------------------------ #
    persisted = get_campaign_state(campaign_id)
    assert persisted is not None, (
        "get_campaign_state() returned None — state not persisted to PostgreSQL"
    )
    assert persisted["campaign_id"] == campaign_id

    # ------------------------------------------------------------------ #
    # Step 4: Submit human decisions — approve all revoked entitlements   #
    # ------------------------------------------------------------------ #
    human_decisions = [
        {
            "entitlement_id": p["entitlement_id"],
            "human_decision": "approve",
            "human_reviewer": "test_reviewer@acme.com",
        }
        for p in pending
    ]

    final = resume_campaign(campaign_id, human_decisions)

    # ------------------------------------------------------------------ #
    # Step 5: Verify graph completed after resume                         #
    # ------------------------------------------------------------------ #
    assert final["status"] == "completed", (
        f"Expected status='completed' after resume, got {final['status']!r}"
    )
    assert final["audit_complete"] is True, "AuditAgent did not complete"
    assert final["notified"] is True, "NotifierAgent did not complete"

    # ------------------------------------------------------------------ #
    # Step 6: Verify DB state reflects completion                         #
    # ------------------------------------------------------------------ #
    db = SessionLocal()
    try:
        campaign = (
            db.query(Campaign)
            .filter(Campaign.langgraph_thread_id == campaign_id)
            .first()
        )
        assert campaign is not None, (
            f"Campaign with langgraph_thread_id={campaign_id!r} not found in DB"
        )
        assert campaign.status == CampaignStatus.COMPLETED, (
            f"Expected campaign.status=COMPLETED, got {campaign.status!r}"
        )
        assert campaign.completed_at is not None, (
            "campaign.completed_at is None — AuditAgent did not set it"
        )
    finally:
        db.close()
