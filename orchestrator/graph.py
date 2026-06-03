"""
orchestrator/graph.py
---------------------
LangGraph StateGraph for the IGA access review campaign pipeline.

Node execution order:
  harvester → risk_scorer → decision → [conditional] → human_review → notifier → audit
                                                      ↘ (no revokes) → notifier → audit

The human_review node uses LangGraph interrupt() to pause execution
pending human input. State is persisted to PostgreSQL via PostgresSaver
so campaigns can be resumed after server restarts.

Checkpointer: PostgresSaver (Phase 5) — state survives restarts.
              Replaced MemorySaver from Phase 2.
"""
from __future__ import annotations

import psycopg
import structlog
from datetime import datetime, timezone
from psycopg.rows import dict_row

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agents.audit import AuditAgent
from agents.decision import DecisionAgent
from agents.harvester import HarvesterAgent
from agents.notifier import NotifierAgent
from agents.risk_scorer import RiskScorerAgent
from config.settings import settings
from orchestrator.state import CampaignState

log = structlog.get_logger(__name__)


# --------------------------------------------------------------------------- #
# Checkpointer helpers                                                         #
# --------------------------------------------------------------------------- #


def _build_postgres_conn_string() -> str:
    """Build a psycopg-compatible connection string from settings."""
    return (
        f"host={settings.postgres_host} "
        f"port={settings.postgres_port} "
        f"dbname={settings.postgres_db} "
        f"user={settings.postgres_user} "
        f"password={settings.postgres_password}"
    )


# --------------------------------------------------------------------------- #
# Node functions                                                               #
# --------------------------------------------------------------------------- #


def harvester_node(state: CampaignState) -> dict:
    """Run the HarvesterAgent to collect entitlements."""
    return HarvesterAgent().run(state)


def risk_scorer_node(state: CampaignState) -> dict:
    """Run the RiskScorerAgent to score each entitlement."""
    return RiskScorerAgent().run(state)


def decision_node(state: CampaignState) -> dict:
    """Run the DecisionAgent to generate approve/revoke/escalate decisions."""
    return DecisionAgent().run(state)


def human_review_node(state: CampaignState) -> dict:
    """Pause graph for human review of REVOKE decisions.

    interrupt() serialises full state to PostgreSQL checkpointer.
    Graph resumes when resume_campaign() is called with human decisions.
    On resume, state["pending_human_review"] contains human_decision
    and human_reviewer filled in by the reviewer.
    """
    pending = state["pending_human_review"]

    log.info(
        "human_review_node: pausing for human review",
        campaign_id=state["campaign_id"],
        pending_count=len(pending),
    )

    # Update Campaign status to AWAITING_HUMAN in DB
    from db.session import SessionLocal
    from db.models import Campaign, CampaignStatus, AuditLog
    db = SessionLocal()
    try:
        campaign = (
            db.query(Campaign)
            .filter(Campaign.langgraph_thread_id == state["campaign_id"])
            .first()
        )
        if campaign:
            campaign.status = CampaignStatus.AWAITING_HUMAN
            db.add(AuditLog(
                campaign_id=campaign.id,
                event="awaiting_human_review",
                detail=f"{len(pending)} revoke decisions pending human approval",
                agent="human_review",
                timestamp=datetime.utcnow(),
            ))
            db.commit()
    finally:
        db.close()

    # Pause graph — state is persisted to PostgreSQL checkpointer
    interrupt({"pending_human_review": pending})

    # Resumes here after resume_campaign() is called
    log.info(
        "human_review_node: resumed after human review",
        campaign_id=state["campaign_id"],
    )
    return {}


def notifier_node(state: CampaignState) -> dict:
    """Run the NotifierAgent to dispatch decision notifications."""
    return NotifierAgent().run(state)


def audit_node(state: CampaignState) -> dict:
    """Run the AuditAgent to persist the compliance audit trail."""
    return AuditAgent().run(state)


# --------------------------------------------------------------------------- #
# Conditional routing                                                          #
# --------------------------------------------------------------------------- #


def route_after_decision(state: CampaignState) -> str:
    """Route to human_review if any decision is 'revoke'; else skip to notifier."""
    if any(d.get("ai_decision") == "revoke" for d in state["decisions"]):
        log.info(
            "route_after_decision → human_review",
            campaign_id=state["campaign_id"],
            revoke_count=sum(
                1 for d in state["decisions"] if d.get("ai_decision") == "revoke"
            ),
        )
        return "human_review"

    log.info(
        "route_after_decision → notifier (no revokes)",
        campaign_id=state["campaign_id"],
    )
    return "notifier"


# --------------------------------------------------------------------------- #
# Graph assembly                                                               #
# --------------------------------------------------------------------------- #

_builder = StateGraph(CampaignState)

# Register nodes
_builder.add_node("harvester", harvester_node)
_builder.add_node("risk_scorer", risk_scorer_node)
_builder.add_node("decision", decision_node)
_builder.add_node("human_review", human_review_node)
_builder.add_node("notifier", notifier_node)
_builder.add_node("audit", audit_node)

# Linear edges
_builder.add_edge(START, "harvester")
_builder.add_edge("harvester", "risk_scorer")
_builder.add_edge("risk_scorer", "decision")

# Conditional edge: decision → human_review OR notifier
_builder.add_conditional_edges(
    "decision",
    route_after_decision,
    {"human_review": "human_review", "notifier": "notifier"},
)

# human_review always continues to notifier after resume
_builder.add_edge("human_review", "notifier")
_builder.add_edge("notifier", "audit")
_builder.add_edge("audit", END)

# Phase 5: PostgresSaver — state persists across server restarts.
# Required for the HITL resume flow (interrupt → human review → resume).
# autocommit=True is required for CREATE INDEX CONCURRENTLY in setup().
# prepare_threshold=0 and row_factory=dict_row match PostgresSaver expectations.
_conn = psycopg.connect(
    _build_postgres_conn_string(),
    autocommit=True,
    prepare_threshold=0,
    row_factory=dict_row,
)
_checkpointer = PostgresSaver(_conn)
_checkpointer.setup()   # creates LangGraph checkpoint tables if not exist
graph = _builder.compile(checkpointer=_checkpointer)


# --------------------------------------------------------------------------- #
# Public entry points                                                          #
# --------------------------------------------------------------------------- #


def run_campaign(campaign_id: str, campaign_name: str) -> CampaignState:
    """Build initial state and invoke the campaign graph.

    Args:
        campaign_id:   Unique identifier for this campaign run.
        campaign_name: Human-readable campaign name.

    Returns:
        Final CampaignState after all nodes have executed (or paused at HITL).
    """
    initial_state: CampaignState = {
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
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
    }

    config = {"configurable": {"thread_id": campaign_id}}

    log.info(
        "run_campaign: starting",
        campaign_id=campaign_id,
        campaign_name=campaign_name,
    )

    result: CampaignState = graph.invoke(initial_state, config=config)

    log.info(
        "run_campaign: complete",
        campaign_id=campaign_id,
        final_status=result.get("status"),
    )

    return result


def get_campaign_state(campaign_id: str) -> CampaignState | None:
    """Retrieve the current persisted state for a campaign thread.

    Returns None if no state exists for the given campaign_id.
    Used by FastAPI to check campaign status without re-running.
    """
    config = {"configurable": {"thread_id": campaign_id}}
    state = graph.get_state(config)
    if state and state.values:
        return state.values
    return None


def resume_campaign(campaign_id: str, human_decisions: list[dict]) -> CampaignState:
    """Resume a paused campaign after human review.

    The graph is paused at human_review_node via interrupt().
    This function merges human decisions into pending_human_review
    and re-invokes the graph from the checkpoint.

    Args:
        campaign_id:      The campaign's langgraph_thread_id
        human_decisions:  List of dicts with keys:
                          entitlement_id, human_decision, human_reviewer

    Returns:
        Final CampaignState after completion.
    """
    config = {"configurable": {"thread_id": campaign_id}}

    # Get current state from checkpointer
    current = graph.get_state(config)
    if not current or not current.values:
        raise ValueError(f"No paused campaign found for id: {campaign_id}")

    # Merge human decisions into pending_human_review
    state = current.values
    updated_pending = _merge_human_decisions(
        state["pending_human_review"],
        human_decisions,
    )

    # Update state in checkpointer with human decisions
    graph.update_state(
        config,
        {"pending_human_review": updated_pending},
        as_node="human_review",
    )

    # Re-invoke graph — it resumes from human_review_node
    result: CampaignState = graph.invoke(None, config=config)
    return result


def _merge_human_decisions(
    pending: list[dict],
    human_decisions: list[dict],
) -> list[dict]:
    """Merge human reviewer decisions into pending_human_review list.

    Matches on entitlement_id. Any pending item not in human_decisions
    keeps human_decision=None (will be treated as escalate by notifier).
    Deduplicates by entitlement_id before merging to guard against
    any double-append edge cases.
    """
    # Deduplicate pending by entitlement_id — guards against
    # any residual doubling from previous append reducer behaviour
    seen: set[str] = set()
    deduped_pending: list[dict] = []
    for item in pending:
        eid = item["entitlement_id"]
        if eid not in seen:
            seen.add(eid)
            deduped_pending.append(item)

    decision_map = {d["entitlement_id"]: d for d in human_decisions}
    updated: list[dict] = []
    for item in deduped_pending:
        eid = item["entitlement_id"]
        if eid in decision_map:
            updated.append({
                **item,
                "human_decision": decision_map[eid]["human_decision"],
                "human_reviewer": decision_map[eid]["human_reviewer"],
            })
        else:
            updated.append(item)
    return updated
