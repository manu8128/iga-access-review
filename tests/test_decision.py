"""
tests/test_decision.py
----------------------
Unit tests for DecisionAgent.

All LLM calls and DB operations are mocked — no real API key or
PostgreSQL connection required.

Mocking strategy:
  agent._llm = MagicMock()         bypasses the BaseAgent lazy property
  agent._db  = MagicMock()         bypasses DB session creation
  Mock Campaign returned by db.query().filter().first()
"""
from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from agents.decision import DecisionAgent
from db.models import CampaignStatus
from orchestrator.state import CampaignState


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _fake_scored_entitlement(
    *,
    entitlement_id: str | None = None,
    risk_score: float = 15.0,
    risk_level: str = "low",
    resource_sensitivity: str = "low",
    resource_system: str = "GitHub",
    role: str = "Read",
    user_title: str = "Senior Analyst",
    flags: list[str] | None = None,
) -> dict:
    return {
        "entitlement_id": entitlement_id or str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "user_name": "Test User",
        "user_title": user_title,
        "user_department": "Engineering",
        "manager_email": "manager@acme.com",
        "resource_id": str(uuid.uuid4()),
        "resource_name": "Test Resource",
        "resource_system": resource_system,
        "resource_sensitivity": resource_sensitivity,
        "role": role,
        "granted_at": (datetime.utcnow()).isoformat(),
        "last_used": (datetime.utcnow()).isoformat(),
        "risk_score": risk_score,
        "risk_level": risk_level,
        "flags": flags or [],
    }


def _make_state(scored_entitlements: list[dict]) -> CampaignState:
    return {
        "campaign_id": f"test-decision-{uuid.uuid4().hex[:8]}",
        "campaign_name": "Decision Test",
        "status": "scoring",
        "entitlements": [],
        "scored_entitlements": scored_entitlements,
        "decisions": [],
        "pending_human_review": [],
        "notified": False,
        "audit_complete": False,
        "error": None,
        "created_at": datetime.utcnow().isoformat(),
    }


def _mock_agent(llm_response_content: str) -> DecisionAgent:
    """Build a DecisionAgent with mocked LLM and DB."""
    agent = DecisionAgent()

    # Mock LLM
    mock_llm = MagicMock()
    mock_llm.invoke.return_value.content = llm_response_content
    agent._llm = mock_llm

    # Mock DB session — Campaign lookup returns a fake Campaign
    mock_campaign = MagicMock()
    mock_campaign.id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    mock_campaign.status = CampaignStatus.SCORING
    agent._db = MagicMock()
    agent._db.query.return_value.filter.return_value.first.return_value = mock_campaign

    return agent


# --------------------------------------------------------------------------- #
# Tests                                                                        #
# --------------------------------------------------------------------------- #

def test_decision_approve() -> None:
    """LLM returns approve → decisions populated, pending_human_review empty."""
    agent = _mock_agent(
        '{"decision": "approve", "reasoning": "Access is appropriate", "confidence": 0.95}'
    )
    state = _make_state([_fake_scored_entitlement(risk_score=15.0, risk_level="low")])

    result = agent.run(state)

    assert result.get("status") == "deciding", (
        f"Expected status='deciding', got {result.get('status')} (error={result.get('error')})"
    )
    decisions = result["decisions"]
    assert len(decisions) == 1
    assert decisions[0]["ai_decision"] == "approve"
    assert decisions[0]["ai_reasoning"] == "Access is appropriate"
    assert decisions[0]["confidence"] == 0.95
    assert result["pending_human_review"] == []


def test_decision_revoke_goes_to_pending() -> None:
    """LLM returns revoke → decision in decisions AND in pending_human_review."""
    agent = _mock_agent(
        '{"decision": "revoke", "reasoning": "Stale admin access", "confidence": 0.88}'
    )
    state = _make_state([_fake_scored_entitlement(risk_score=80.0, risk_level="high")])

    result = agent.run(state)

    assert result.get("status") == "deciding"
    decisions = result["decisions"]
    assert len(decisions) == 1
    assert decisions[0]["ai_decision"] == "revoke"

    pending = result["pending_human_review"]
    assert len(pending) == 1
    assert pending[0]["human_decision"] is None
    assert pending[0]["human_reviewer"] is None
    # Pending dict must carry all original decision fields
    assert pending[0]["ai_decision"] == "revoke"
    assert pending[0]["ai_reasoning"] == "Stale admin access"


def test_decision_handles_bad_json() -> None:
    """LLM returns unparseable content → defaults to escalate, confidence=0.0."""
    agent = _mock_agent("NOT VALID JSON {{{")
    state = _make_state([_fake_scored_entitlement()])

    result = agent.run(state)

    assert result.get("status") == "deciding"
    decisions = result["decisions"]
    assert len(decisions) == 1
    assert decisions[0]["ai_decision"] == "escalate"
    assert decisions[0]["confidence"] == 0.0
    assert decisions[0]["ai_reasoning"] == "parse error"
    # Escalate does NOT go to pending_human_review
    assert result["pending_human_review"] == []


def test_decision_handles_invalid_decision_value() -> None:
    """LLM returns an unrecognised decision value → defaults to escalate."""
    agent = _mock_agent(
        '{"decision": "maybe", "reasoning": "Not sure about this one", "confidence": 0.5}'
    )
    state = _make_state([_fake_scored_entitlement()])

    result = agent.run(state)

    assert result.get("status") == "deciding"
    assert result["decisions"][0]["ai_decision"] == "escalate"
    # confidence carried through even on invalid decision
    assert result["decisions"][0]["confidence"] == 0.5
