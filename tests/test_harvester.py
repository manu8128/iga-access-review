"""
tests/test_harvester.py
-----------------------
Integration tests for HarvesterAgent.

REQUIRES: Docker PostgreSQL running with seed data loaded.
  docker-compose up -d
  python db/seed.py   (if not already seeded)

These tests write real Campaign and AuditLog rows to the database.
Each test generates a unique campaign_id via uuid4 to avoid UNIQUE
constraint collisions on langgraph_thread_id across test runs.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from agents.harvester import HarvesterAgent
from db.models import AuditLog, Campaign, CampaignStatus
from db.session import SessionLocal
from orchestrator.state import CampaignState

# Required keys in every entitlement dict (matches state.py contract)
REQUIRED_ENTITLEMENT_KEYS = {
    "entitlement_id",
    "user_id",
    "user_name",
    "user_title",
    "user_department",
    "manager_email",
    "resource_id",
    "resource_name",
    "resource_system",
    "resource_sensitivity",
    "role",
    "granted_at",
    "last_used",
}


def _make_state(campaign_id: str, campaign_name: str) -> CampaignState:
    """Build a minimal CampaignState suitable for HarvesterAgent.run()."""
    return {
        "campaign_id": campaign_id,
        "campaign_name": campaign_name,
        "status": "created",
        "entitlements": [],
        "scored_entitlements": [],
        "decisions": [],
        "pending_human_review": [],
        "notified": False,
        "audit_complete": False,
        "error": None,
        "created_at": datetime.utcnow().isoformat(),
    }


# --------------------------------------------------------------------------- #
# Tests                                                                        #
# --------------------------------------------------------------------------- #

def test_harvester_returns_all_active_entitlements() -> None:
    """Harvester returns all 13 active entitlements from seed data.

    Verifies count, required key presence, and correct status field.
    """
    campaign_id = f"test-harvest-{uuid.uuid4().hex[:8]}"
    state = _make_state(campaign_id, "Harvest Test")

    result = HarvesterAgent().run(state)

    assert result.get("status") == "harvesting", (
        f"Expected status='harvesting', got: {result.get('status')} "
        f"(error={result.get('error')})"
    )
    assert "error" not in result or result.get("error") is None

    items = result["entitlements"]
    assert isinstance(items, list)
    assert len(items) == 13, (
        f"Expected 13 active entitlements from seed data, got {len(items)}"
    )

    for item in items:
        missing = REQUIRED_ENTITLEMENT_KEYS - item.keys()
        assert not missing, (
            f"Entitlement dict missing keys: {missing}\nGot: {list(item.keys())}"
        )

        # Spot-check types
        assert isinstance(item["entitlement_id"], str)
        assert isinstance(item["user_id"], str)
        assert isinstance(item["user_name"], str)
        assert isinstance(item["resource_sensitivity"], str)
        assert item["resource_sensitivity"] in {"low", "medium", "high", "critical"}
        assert isinstance(item["granted_at"], str)
        # last_used is either an ISO string or None
        assert item["last_used"] is None or isinstance(item["last_used"], str)


def test_harvester_creates_campaign_record() -> None:
    """Harvester creates a Campaign row with correct status and thread ID."""
    campaign_id = f"test-harvest-{uuid.uuid4().hex[:8]}"
    state = _make_state(campaign_id, "DB Record Test")

    result = HarvesterAgent().run(state)
    assert result.get("status") == "harvesting", (
        f"Harvest failed: {result.get('error')}"
    )

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
        assert campaign.name == "DB Record Test"
        assert campaign.status == CampaignStatus.HARVESTING
    finally:
        db.close()


def test_harvester_creates_audit_logs() -> None:
    """Harvester writes exactly 2 audit log entries: started and complete."""
    campaign_id = f"test-harvest-{uuid.uuid4().hex[:8]}"
    state = _make_state(campaign_id, "Audit Log Test")

    result = HarvesterAgent().run(state)
    assert result.get("status") == "harvesting", (
        f"Harvest failed: {result.get('error')}"
    )

    db = SessionLocal()
    try:
        # Retrieve campaign to get its UUID primary key
        campaign = (
            db.query(Campaign)
            .filter(Campaign.langgraph_thread_id == campaign_id)
            .first()
        )
        assert campaign is not None

        logs = (
            db.query(AuditLog)
            .filter(AuditLog.campaign_id == campaign.id)
            .order_by(AuditLog.timestamp)
            .all()
        )
        events = [log.event for log in logs]

        assert len(logs) == 2, (
            f"Expected 2 audit log entries, got {len(logs)}: {events}"
        )
        assert events[0] == "harvest_started"
        assert events[1] == "harvest_complete"

        # Verify the complete entry detail mentions the entitlement count
        assert "13" in logs[1].detail, (
            f"harvest_complete detail should mention count 13, got: {logs[1].detail!r}"
        )

        # All logs attributed to the harvester agent
        for log in logs:
            assert log.agent == "harvester"
    finally:
        db.close()
