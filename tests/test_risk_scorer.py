"""
tests/test_risk_scorer.py
-------------------------
Unit tests for RiskScorerAgent.

No database connection required — all tests construct fake entitlement
dicts directly and pass them through the scorer.

Score reference table (sensitivity base + staleness + SoD + mismatch, cap 100):
  critical=40  high=30  medium=15  low=5
  never_used=+30  >=180d=+25  >=90d=+15  >=30d=+5  <30d=+0
  sod_violation=+20  role_mismatch=+15

Risk level thresholds (>=):
  >=81 → critical | >=61 → high | >=31 → medium | >=0 → low
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from agents.risk_scorer import RiskScorerAgent
from orchestrator.state import CampaignState


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _iso(days_ago: int) -> str:
    """Return ISO timestamp string for N days in the past."""
    return (datetime.utcnow() - timedelta(days=days_ago)).isoformat()


def _entitlement(
    *,
    user_id: str | None = None,
    resource_sensitivity: str = "low",
    resource_system: str = "GitHub",
    role: str = "Read",
    user_title: str = "Senior Analyst",
    last_used: str | None = _iso(1),
) -> dict:
    """Build a minimal entitlement dict for scorer tests."""
    return {
        "entitlement_id": str(uuid.uuid4()),
        "user_id": user_id or str(uuid.uuid4()),
        "user_name": "Test User",
        "user_title": user_title,
        "user_department": "Engineering",
        "manager_email": "manager@acme.com",
        "resource_id": str(uuid.uuid4()),
        "resource_name": "Test Resource",
        "resource_system": resource_system,
        "resource_sensitivity": resource_sensitivity,
        "role": role,
        "granted_at": _iso(365),
        "last_used": last_used,
    }


def _run(entitlements: list[dict]) -> dict:
    """Run RiskScorerAgent with the given entitlement list."""
    state: CampaignState = {
        "campaign_id": f"test-scorer-{uuid.uuid4().hex[:8]}",
        "campaign_name": "Scorer Test",
        "status": "harvesting",
        "entitlements": entitlements,
        "scored_entitlements": [],
        "decisions": [],
        "pending_human_review": [],
        "notified": False,
        "audit_complete": False,
        "error": None,
        "created_at": datetime.utcnow().isoformat(),
    }
    return RiskScorerAgent().run(state)


# --------------------------------------------------------------------------- #
# Tests                                                                        #
# --------------------------------------------------------------------------- #

def test_risk_scorer_scores_all_entitlements() -> None:
    """Scorer produces one scored dict per input entitlement."""
    entitlements = [
        _entitlement(resource_sensitivity="critical", last_used=None),
        _entitlement(resource_sensitivity="low", last_used=_iso(1)),
    ]

    result = _run(entitlements)

    assert result["status"] == "scoring"
    scored = result["scored_entitlements"]
    assert len(scored) == 2

    for item in scored:
        assert "risk_score" in item
        assert "risk_level" in item
        assert "flags" in item
        assert isinstance(item["risk_score"], float)
        assert item["risk_level"] in {"low", "medium", "high", "critical"}
        assert isinstance(item["flags"], list)


def test_critical_resource_never_used_scores_high() -> None:
    """Critical sensitivity (40) + never used (30) = 70 → high.

    No SoD (single entitlement), no role mismatch (Read ≠ Admin).
    """
    e = _entitlement(
        resource_sensitivity="critical",
        last_used=None,        # never used → +30
        role="Read",           # not Admin → no mismatch
        user_title="Senior Analyst",
    )

    result = _run([e])
    scored = result["scored_entitlements"][0]

    assert scored["risk_score"] == 70.0, (
        f"Expected 70 (40+30), got {scored['risk_score']}"
    )
    assert scored["risk_level"] == "high"
    assert scored["flags"] == []


def test_sod_violation_detected() -> None:
    """User with SAP (Finance) + AWS (IT) entitlements → both flagged +20."""
    shared_user_id = str(uuid.uuid4())

    sap_e = _entitlement(
        user_id=shared_user_id,
        resource_system="SAP",        # Finance
        resource_sensitivity="low",   # base=5
        last_used=_iso(1),            # used recently → +0
    )
    aws_e = _entitlement(
        user_id=shared_user_id,
        resource_system="AWS",        # IT/DevOps
        resource_sensitivity="low",   # base=5
        last_used=_iso(1),            # used recently → +0
    )

    result = _run([sap_e, aws_e])
    scored = result["scored_entitlements"]

    for item in scored:
        assert "sod_violation" in item["flags"], (
            f"Expected sod_violation flag on {item['resource_system']} entitlement"
        )
        # base(5) + sod(20) = 25 → low (just below 31 threshold)
        assert item["risk_score"] == 25.0, (
            f"Expected 25 (5+20), got {item['risk_score']}"
        )


def test_role_mismatch_detected() -> None:
    """Admin role + Junior title → role_mismatch flag and +15 added."""
    e = _entitlement(
        resource_sensitivity="low",   # base=5
        last_used=_iso(1),            # +0
        role="Admin",
        user_title="Junior Analyst",
    )

    result = _run([e])
    scored = result["scored_entitlements"][0]

    assert "role_mismatch" in scored["flags"]
    # base(5) + mismatch(15) = 20 → low
    assert scored["risk_score"] == 20.0, (
        f"Expected 20 (5+15), got {scored['risk_score']}"
    )


def test_score_capped_at_100() -> None:
    """Scores that would exceed 100 are capped at exactly 100.

    critical(40) + never_used(30) + SoD(20) + role_mismatch(15) = 105 → capped 100.
    Two entitlements share the same user_id to trigger the SoD rule.
    """
    shared_user_id = str(uuid.uuid4())

    # This entitlement accumulates all four penalties
    high_risk = _entitlement(
        user_id=shared_user_id,
        resource_sensitivity="critical",   # +40
        resource_system="SAP",             # Finance side of SoD
        last_used=None,                    # never used → +30
        role="Admin",
        user_title="Junior Engineer",      # role_mismatch → +15
    )
    # Second entitlement for same user to complete the SoD pair
    it_side = _entitlement(
        user_id=shared_user_id,
        resource_system="AWS",             # IT side → triggers SoD for both
        resource_sensitivity="low",
        last_used=_iso(1),
    )

    result = _run([high_risk, it_side])
    scored = {s["resource_system"]: s for s in result["scored_entitlements"]}

    # SAP entitlement: 40+30+20+15 = 105 → capped at 100
    sap_scored = scored["SAP"]
    assert sap_scored["risk_score"] == 100.0, (
        f"Expected 100 (capped from 105), got {sap_scored['risk_score']}"
    )
    assert sap_scored["risk_level"] == "critical"
    assert "sod_violation" in sap_scored["flags"]
    assert "role_mismatch" in sap_scored["flags"]


def test_risk_scorer_handles_empty_entitlements() -> None:
    """Empty entitlements list returns empty scored list without error."""
    result = _run([])

    assert result["status"] == "scoring"
    assert result["scored_entitlements"] == []
    assert "error" not in result or result.get("error") is None


def test_risk_level_boundaries() -> None:
    """Verify that exact boundary scores map to the correct risk level.

    Boundary scores per spec (>= comparison):
      81 → critical | 61 → high | 31 → medium | 0 → low
    """
    from agents.risk_scorer import _risk_level

    assert _risk_level(81)  == "critical"
    assert _risk_level(80)  == "high"
    assert _risk_level(61)  == "high"
    assert _risk_level(60)  == "medium"
    assert _risk_level(31)  == "medium"
    assert _risk_level(30)  == "low"
    assert _risk_level(0)   == "low"
    assert _risk_level(100) == "critical"
