"""
orchestrator/graph.py
---------------------
LangGraph StateGraph for the IGA access review campaign pipeline.

Node execution order:
  harvester → risk_scorer → decision → [conditional] → human_review → notifier → audit
                                                      ↘ (no revokes) → notifier → audit

The human_review node uses LangGraph interrupt() to pause execution
pending human input. In Phase 2 this is a stub — real resume logic
is implemented in Phase 5 using a PostgreSQL checkpointer.

Checkpointer: MemorySaver (in-process, for Phase 2).
              Will be swapped to AsyncPostgresSaver in Phase 5.
"""
from __future__ import annotations

import structlog
from datetime import datetime, timezone

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agents.audit import AuditAgent
from agents.decision import DecisionAgent
from agents.harvester import HarvesterAgent
from agents.notifier import NotifierAgent
from agents.risk_scorer import RiskScorerAgent
from orchestrator.state import CampaignState

log = structlog.get_logger(__name__)

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
    """Pause the graph for human review of REVOKE decisions.

    TODO Phase 5: Full HITL implementation.
      - This interrupt() suspends graph execution and serialises state to the
        PostgreSQL checkpointer (thread_id = campaign_id).
      - The FastAPI endpoint POST /campaigns/{id}/resume will re-invoke the
        graph with the human reviewer's decisions merged into state.
      - On resume, this node receives the updated pending_human_review list
        (with human_decision and human_reviewer filled in) and returns control
        to the notifier node.
    """
    log.info(
        "human_review_node: pausing for human review",
        campaign_id=state["campaign_id"],
        pending_count=len(state["pending_human_review"]),
    )

    # Pause execution — LangGraph serialises state and waits for resume.
    interrupt({"pending_human_review": state["pending_human_review"]})

    # Control returns here after graph.invoke() is called again with
    # human decisions populated in state["pending_human_review"].
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

# Compile with MemorySaver checkpointer (Phase 2).
# TODO Phase 5: replace with AsyncPostgresSaver for persistent HITL state.
_checkpointer = MemorySaver()
graph = _builder.compile(checkpointer=_checkpointer)


# --------------------------------------------------------------------------- #
# Public entry point                                                           #
# --------------------------------------------------------------------------- #


def run_campaign(campaign_id: str, campaign_name: str) -> CampaignState:
    """Build initial state and invoke the campaign graph.

    Args:
        campaign_id:   Unique identifier for this campaign run.
        campaign_name: Human-readable campaign name.

    Returns:
        Final CampaignState after all nodes have executed.
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
