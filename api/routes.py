"""
api/routes.py
-------------
FastAPI route definitions for the IGA Access Review API.

Endpoints:
  GET  /health                          — liveness check
  POST /campaigns                       — start a new campaign (202)
  GET  /campaigns/{campaign_id}         — poll campaign status
  GET  /campaigns/{campaign_id}/review  — list pending human-review items
  POST /campaigns/{campaign_id}/resume  — submit human decisions and resume (202)
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from orchestrator.graph import get_campaign_state, resume_campaign, run_campaign

router = APIRouter()


# --------------------------------------------------------------------------- #
# Request / Response models                                                    #
# --------------------------------------------------------------------------- #


class StartCampaignRequest(BaseModel):
    campaign_name: str


class CampaignResponse(BaseModel):
    campaign_id: str
    campaign_name: str
    status: str
    message: str


class CampaignStatusResponse(BaseModel):
    campaign_id: str
    status: str
    entitlement_count: int
    decision_count: int
    pending_review_count: int
    audit_complete: bool
    error: str | None


class PendingReviewResponse(BaseModel):
    campaign_id: str
    pending_count: int
    pending_human_review: list[dict]


class HumanDecisionItem(BaseModel):
    entitlement_id: str
    human_decision: str   # "approve" | "revoke" | "escalate"
    human_reviewer: str   # reviewer email or name


class ResumeRequest(BaseModel):
    decisions: list[HumanDecisionItem]


# --------------------------------------------------------------------------- #
# Routes                                                                       #
# --------------------------------------------------------------------------- #


@router.get("/health")
async def health() -> dict:
    """Liveness check."""
    return {"status": "ok", "service": "iga-access-review"}


@router.post("/campaigns", status_code=202)
async def start_campaign(
    request: StartCampaignRequest,
    background_tasks: BackgroundTasks,
) -> CampaignResponse:
    """Start a new access review campaign.

    Returns 202 immediately with the campaign_id.
    The graph runs in a background thread — poll GET /campaigns/{id} for status.
    """
    campaign_id = str(uuid.uuid4())
    background_tasks.add_task(run_campaign, campaign_id, request.campaign_name)
    return CampaignResponse(
        campaign_id=campaign_id,
        campaign_name=request.campaign_name,
        status="created",
        message=f"Campaign started. Poll GET /campaigns/{campaign_id} for status.",
    )


@router.get("/campaigns/{campaign_id}")
async def get_campaign_status(campaign_id: str) -> CampaignStatusResponse:
    """Poll the current status of a campaign."""
    state = get_campaign_state(campaign_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return CampaignStatusResponse(
        campaign_id=campaign_id,
        status=state.get("status", "unknown"),
        entitlement_count=len(state.get("entitlements", [])),
        decision_count=len(state.get("decisions", [])),
        pending_review_count=len(state.get("pending_human_review", [])),
        audit_complete=state.get("audit_complete", False),
        error=state.get("error"),
    )


@router.get("/campaigns/{campaign_id}/review")
async def get_pending_review(campaign_id: str) -> PendingReviewResponse:
    """Retrieve the list of entitlement decisions pending human review."""
    state = get_campaign_state(campaign_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    pending = state.get("pending_human_review", [])
    return PendingReviewResponse(
        campaign_id=campaign_id,
        pending_count=len(pending),
        pending_human_review=pending,
    )


@router.post("/campaigns/{campaign_id}/resume", status_code=202)
async def resume_campaign_endpoint(
    campaign_id: str,
    request: ResumeRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    """Submit human decisions and resume a paused campaign.

    Returns 202 immediately. The graph resumes in a background thread.
    Poll GET /campaigns/{id} until status == "completed".
    """
    valid_decisions = {"approve", "revoke", "escalate"}
    for d in request.decisions:
        if d.human_decision not in valid_decisions:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid human_decision: {d.human_decision!r}. "
                       f"Must be one of: {sorted(valid_decisions)}",
            )

    state = get_campaign_state(campaign_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if state.get("status") != "deciding":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Campaign is not awaiting review. "
                f"Current status: {state.get('status')!r}"
            ),
        )

    human_decisions = [d.model_dump() for d in request.decisions]
    background_tasks.add_task(resume_campaign, campaign_id, human_decisions)

    return {
        "campaign_id": campaign_id,
        "message": "Human decisions submitted. Campaign resuming.",
        "decision_count": len(request.decisions),
    }
