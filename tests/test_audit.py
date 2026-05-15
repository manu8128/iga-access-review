"""
tests/test_audit.py
-------------------
Unit tests for AuditAgent.

DB session is mocked — no real PostgreSQL required.
AuditAgent has no LLM calls so no LLM mock is needed.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import MagicMock, call, patch

import pytest

from agents.audit import AuditAgent
from db.models import CampaignStatus
from orchestrator.state import CampaignState


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _fake_decision(ai_decision: str = "approve") -> dict:
    return {
        "entitlement_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "user_name": "Test User",
        "user_title": "Senior Analyst",
        "user_department": "Engineering",
        "manager_email": "manager@acme.com",
        "resource_id": str(uuid.uuid4()),
        "resource_name": "Test Resource",
        "resource_system": "GitHub",
        "resource_sensitivity": "low",
        "role": "Read",
        "granted_at": datetime.utcnow().isoformat(),
        "last_used": datetime.utcnow().isoformat(),
        "risk_score": 15.0,
        "risk_level": "low",
        "flags": [],
        "ai_decision": ai_decision,
        "ai_reasoning": "Access is appropriate.",
        "confidence": 0.9,
    }


def _make_state(decisions: list[dict]) -> CampaignState:
    return {
        "campaign_id": f"test-audit-{uuid.uuid4().hex[:8]}",
        "campaign_name": "Audit Test Campaign",
        "status": "notifying",
        "entitlements": [],
        "scored_entitlements": [],
        "decisions": decisions,
        "pending_human_review": [],
        "notified": True,
        "audit_complete": False,
        "error": None,
        "created_at": datetime.utcnow().isoformat(),
    }


def _mock_agent(decisions: list[dict]) -> tuple[AuditAgent, MagicMock]:
    """Build an AuditAgent with a mocked DB session.

    Returns (agent, mock_campaign) so tests can assert on campaign state.
    """
    agent = AuditAgent()

    mock_campaign = MagicMock()
    mock_campaign.id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    mock_campaign.status = CampaignStatus.NOTIFYING

    agent._db = MagicMock()
    agent._db.query.return_value.filter.return_value.first.return_value = mock_campaign

    return agent, mock_campaign


# --------------------------------------------------------------------------- #
# Tests                                                                        #
# --------------------------------------------------------------------------- #

def test_audit_marks_campaign_complete() -> None:
    """AuditAgent sets Campaign.status=COMPLETED and completed_at, returns completed."""
    decisions = [_fake_decision("approve")]
    agent, mock_campaign = _mock_agent(decisions)
    state = _make_state(decisions)

    result = agent.run(state)

    assert result["status"] == "completed", (
        f"Expected status='completed', got {result.get('status')} (error={result.get('error')})"
    )
    assert result["audit_complete"] is True

    # Campaign status must have been set to COMPLETED
    assert mock_campaign.status == CampaignStatus.COMPLETED, (
        f"Expected CampaignStatus.COMPLETED, got {mock_campaign.status}"
    )
    # completed_at must have been set
    assert mock_campaign.completed_at is not None


def test_audit_writes_one_log_per_decision() -> None:
    """AuditAgent calls db.add() for each decision + 1 campaign_complete entry."""
    decisions = [
        _fake_decision("approve"),
        _fake_decision("revoke"),
        _fake_decision("escalate"),
    ]
    agent, mock_campaign = _mock_agent(decisions)
    state = _make_state(decisions)

    result = agent.run(state)

    assert result["audit_complete"] is True

    # 3 per-decision entries + 1 campaign_complete = minimum 4 db.add() calls
    add_call_count = agent._db.add.call_count
    assert add_call_count >= 4, (
        f"Expected at least 4 db.add() calls (3 decisions + 1 summary), "
        f"got {add_call_count}"
    )

    # db.commit() must have been called exactly once
    agent._db.commit.assert_called_once()
