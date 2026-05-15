"""
tests/test_notifier.py
----------------------
Unit tests for NotifierAgent.

All LLM calls are mocked — no real API key or DB required.
NotifierAgent has no DB writes so no DB mock is needed.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import MagicMock, call

import pytest

from agents.notifier import NotifierAgent
from orchestrator.state import CampaignState


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _fake_decision(
    *,
    manager_email: str | None = "manager@acme.com",
    ai_decision: str = "approve",
    user_name: str = "Test User",
) -> dict:
    return {
        "entitlement_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "user_name": user_name,
        "user_title": "Senior Analyst",
        "user_department": "Engineering",
        "manager_email": manager_email,
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
        "campaign_id": f"test-notifier-{uuid.uuid4().hex[:8]}",
        "campaign_name": "Notifier Test",
        "status": "deciding",
        "entitlements": [],
        "scored_entitlements": [],
        "decisions": decisions,
        "pending_human_review": [],
        "notified": False,
        "audit_complete": False,
        "error": None,
        "created_at": datetime.utcnow().isoformat(),
    }


def _mock_agent(llm_responses: list[str] | str) -> NotifierAgent:
    """Build a NotifierAgent with a mocked LLM.

    llm_responses: single string (all calls return same) or list for side_effect.
    """
    agent = NotifierAgent()
    mock_llm = MagicMock()

    if isinstance(llm_responses, list):
        mock_llm.invoke.side_effect = [
            MagicMock(content=r) for r in llm_responses
        ]
    else:
        mock_llm.invoke.return_value.content = llm_responses

    agent._llm = mock_llm
    return agent


_VALID_EMAIL_JSON = '{"subject": "Access Review Summary", "body": "Please review..."}'


# --------------------------------------------------------------------------- #
# Tests                                                                        #
# --------------------------------------------------------------------------- #

def test_notifier_groups_by_manager() -> None:
    """LLM is called once per unique manager, not once per decision."""
    decisions = [
        _fake_decision(manager_email="manager_a@acme.com", user_name="Alice"),
        _fake_decision(manager_email="manager_a@acme.com", user_name="Bob"),
        _fake_decision(manager_email="manager_b@acme.com", user_name="Carol"),
    ]
    agent = _mock_agent(_VALID_EMAIL_JSON)
    state = _make_state(decisions)

    result = agent.run(state)

    assert result["notified"] is True
    assert result["status"] == "notifying"
    # 3 decisions across 2 managers → exactly 2 LLM calls
    assert agent._llm.invoke.call_count == 2, (
        f"Expected 2 LLM calls (one per manager), got {agent._llm.invoke.call_count}"
    )


def test_notifier_skips_null_manager() -> None:
    """Decisions with manager_email=None are silently skipped; LLM never called."""
    decisions = [
        _fake_decision(manager_email=None),
    ]
    agent = _mock_agent(_VALID_EMAIL_JSON)
    state = _make_state(decisions)

    result = agent.run(state)

    assert result["notified"] is True
    assert result["status"] == "notifying"
    agent._llm.invoke.assert_not_called()


def test_notifier_continues_on_parse_error() -> None:
    """Parse failure for one manager is logged; campaign is not aborted."""
    decisions = [
        _fake_decision(manager_email="manager_a@acme.com"),
        _fake_decision(manager_email="manager_b@acme.com"),
    ]
    # First manager gets valid JSON, second gets unparseable garbage
    agent = _mock_agent([
        _VALID_EMAIL_JSON,
        "THIS IS NOT JSON {{{{",
    ])
    state = _make_state(decisions)

    # Must not raise
    result = agent.run(state)

    assert result["notified"] is True, (
        "notified should be True even when one manager email fails to parse"
    )
    assert result.get("error") is None
    # Both managers were attempted
    assert agent._llm.invoke.call_count == 2
