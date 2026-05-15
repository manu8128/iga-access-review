"""
tests/test_api.py
-----------------
Unit tests for the FastAPI endpoints in api/routes.py.

All graph calls (run_campaign, get_campaign_state, resume_campaign) are
mocked — no real graph execution, no database, no LLM.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _fake_state(
    status: str = "completed",
    pending: list[dict] | None = None,
) -> dict:
    """Build a minimal fake CampaignState dict for mocking."""
    return {
        "campaign_id": "test-campaign-id",
        "campaign_name": "Test Campaign",
        "status": status,
        "entitlements": [{"id": "e1"}, {"id": "e2"}],
        "scored_entitlements": [{"id": "e1"}, {"id": "e2"}],
        "decisions": [{"id": "e1"}, {"id": "e2"}],
        "pending_human_review": pending if pending is not None else [],
        "notified": True,
        "audit_complete": True,
        "error": None,
        "created_at": "2026-01-01T00:00:00+00:00",
    }


# --------------------------------------------------------------------------- #
# Health                                                                       #
# --------------------------------------------------------------------------- #

def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "iga-access-review"


# --------------------------------------------------------------------------- #
# POST /campaigns                                                              #
# --------------------------------------------------------------------------- #

def test_start_campaign_returns_202() -> None:
    with patch("api.routes.run_campaign") as mock_run:
        mock_run.return_value = None  # background task — return value ignored
        response = client.post(
            "/campaigns",
            json={"campaign_name": "Test Campaign"},
        )
    assert response.status_code == 202
    data = response.json()
    assert "campaign_id" in data
    assert data["campaign_name"] == "Test Campaign"
    assert data["status"] == "created"


# --------------------------------------------------------------------------- #
# GET /campaigns/{campaign_id}                                                 #
# --------------------------------------------------------------------------- #

def test_get_campaign_status_not_found() -> None:
    with patch("api.routes.get_campaign_state", return_value=None):
        response = client.get("/campaigns/nonexistent-id")
    assert response.status_code == 404


def test_get_campaign_status_found() -> None:
    fake = _fake_state(status="completed")
    with patch("api.routes.get_campaign_state", return_value=fake):
        response = client.get("/campaigns/test-campaign-id")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["entitlement_count"] == 2
    assert data["decision_count"] == 2
    assert data["pending_review_count"] == 0
    assert data["audit_complete"] is True
    assert data["error"] is None


# --------------------------------------------------------------------------- #
# GET /campaigns/{campaign_id}/review                                          #
# --------------------------------------------------------------------------- #

def test_get_pending_review() -> None:
    pending = [
        {"entitlement_id": "e1", "human_decision": None, "human_reviewer": None},
        {"entitlement_id": "e2", "human_decision": None, "human_reviewer": None},
    ]
    fake = _fake_state(status="deciding", pending=pending)
    with patch("api.routes.get_campaign_state", return_value=fake):
        response = client.get("/campaigns/test-campaign-id/review")
    assert response.status_code == 200
    data = response.json()
    assert data["pending_count"] == 2
    assert len(data["pending_human_review"]) == 2


# --------------------------------------------------------------------------- #
# POST /campaigns/{campaign_id}/resume                                         #
# --------------------------------------------------------------------------- #

def test_resume_campaign_not_found() -> None:
    with patch("api.routes.get_campaign_state", return_value=None):
        response = client.post(
            "/campaigns/bad-id/resume",
            json={"decisions": [
                {
                    "entitlement_id": "e1",
                    "human_decision": "approve",
                    "human_reviewer": "reviewer@acme.com",
                }
            ]},
        )
    assert response.status_code == 404


def test_resume_campaign_wrong_status() -> None:
    fake = _fake_state(status="completed")
    with patch("api.routes.get_campaign_state", return_value=fake):
        response = client.post(
            "/campaigns/test-campaign-id/resume",
            json={"decisions": [
                {
                    "entitlement_id": "e1",
                    "human_decision": "approve",
                    "human_reviewer": "reviewer@acme.com",
                }
            ]},
        )
    assert response.status_code == 409
    assert "not awaiting review" in response.json()["detail"]


def test_resume_campaign_invalid_decision() -> None:
    response = client.post(
        "/campaigns/any-id/resume",
        json={"decisions": [
            {
                "entitlement_id": "e1",
                "human_decision": "maybe",
                "human_reviewer": "reviewer@acme.com",
            }
        ]},
    )
    assert response.status_code == 422


def test_resume_campaign_success() -> None:
    fake = _fake_state(status="deciding")
    with patch("api.routes.get_campaign_state", return_value=fake), \
         patch("api.routes.resume_campaign") as mock_resume:
        mock_resume.return_value = None  # background task
        response = client.post(
            "/campaigns/test-campaign-id/resume",
            json={"decisions": [
                {
                    "entitlement_id": "e1",
                    "human_decision": "approve",
                    "human_reviewer": "reviewer@acme.com",
                }
            ]},
        )
    assert response.status_code == 202
    data = response.json()
    assert data["campaign_id"] == "test-campaign-id"
    assert data["decision_count"] == 1
    assert "resuming" in data["message"].lower()


# --------------------------------------------------------------------------- #
# GET /observability/status                                                    #
# --------------------------------------------------------------------------- #

def test_observability_status() -> None:
    response = client.get("/observability/status")
    assert response.status_code == 200
    data = response.json()
    assert "langsmith_tracing" in data
    assert "langsmith_project" in data
