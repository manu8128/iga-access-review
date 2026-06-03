"""
orchestrator/state.py
---------------------
CampaignState TypedDict — the single source of truth passed between
every node in the LangGraph StateGraph.

Three list fields use Annotated[list[dict], operator.add] so that
LangGraph merges partial state updates by appending rather than replacing.
pending_human_review uses plain list[dict] (last-write-wins) because it
is written once by DecisionAgent and then updated in place by
resume_campaign() — an append reducer would double the list on
graph.update_state() calls.
All other fields use last-write-wins (default LangGraph behaviour).
"""
from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class CampaignState(TypedDict):
    """Shared state object threaded through the full campaign pipeline."""

    campaign_id: str
    campaign_name: str

    # Lifecycle status — maps to CampaignStatus enum values (strings)
    status: str

    # Harvester output: raw entitlement records from the database.
    # Each dict keys: entitlement_id, user_id, user_name, user_title,
    # user_department, manager_email, resource_id, resource_name,
    # resource_system, resource_sensitivity, role, granted_at, last_used
    entitlements: Annotated[list[dict], operator.add]

    # RiskScorer output: entitlement + risk_score (float 0-100),
    # risk_level (str: low/medium/high/critical), flags (list[str])
    scored_entitlements: Annotated[list[dict], operator.add]

    # Decision output: scored_entitlement + ai_decision (str),
    # ai_reasoning (str), confidence (float 0-1)
    decisions: Annotated[list[dict], operator.add]

    # Human review queue: decision dicts where ai_decision == "revoke".
    # Each dict carries all decision keys plus:
    #   human_decision: str | None  (None until reviewed)
    #   human_reviewer: str | None  (None until reviewed)
    # Uses last-write-wins (no reducer) because this field is written
    # once by DecisionAgent and updated in place by resume_campaign().
    # An append reducer would double the list on graph.update_state() calls.
    pending_human_review: list[dict]

    # Notifier output flag
    notified: bool

    # Audit agent output flag
    audit_complete: bool

    # Set by any agent on failure; None on success
    error: str | None

    # ISO-format timestamp when campaign was initiated
    created_at: str
