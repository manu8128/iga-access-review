"""
agents/decision.py
------------------
DecisionAgent — LLM-driven APPROVE / REVOKE / ESCALATE per entitlement.

One LLM call per scored entitlement. Responses are parsed as JSON and
defaulted to ESCALATE on any parse failure or invalid value.

DB writes (single commit after all LLM calls):
  - One EntitlementReview row per entitlement
  - Campaign.status updated to DECIDING
  - AuditLog entry: decisions_complete
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage

from agents.base import BaseAgent
from db.models import (
    AuditLog,
    Campaign,
    CampaignStatus,
    EntitlementDecision,
    EntitlementReview,
    RiskLevel,
)

if TYPE_CHECKING:
    from orchestrator.state import CampaignState

# --------------------------------------------------------------------------- #
# Constants                                                                    #
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = """You are an access review decision agent for an enterprise IGA \
(Identity Governance and Administration) system. Your job is to \
review user entitlements and recommend a decision for each one.

Rules:
- APPROVE: access is appropriate, recently used, matches user role
- REVOKE: access is stale, excessive, mismatched, or violates policy
- ESCALATE: uncertain — needs human judgment

You must respond with valid JSON only. No explanation outside the JSON."""

VALID_DECISIONS: frozenset[str] = frozenset({"approve", "revoke", "escalate"})


def _parse_llm_response(content: str) -> tuple[str, str, float]:
    """Safely parse LLM JSON response into (decision, reasoning, confidence).

    Returns escalate defaults on any parse or validation failure.
    """
    try:
        parsed = json.loads(content)
        decision = str(parsed.get("decision", "escalate")).lower()
        if decision not in VALID_DECISIONS:
            decision = "escalate"
        reasoning = str(parsed.get("reasoning", ""))
        confidence = float(parsed.get("confidence", 0.0))
        return decision, reasoning, confidence
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        return "escalate", "parse error", 0.0


def _call_llm_with_retry(
    llm,
    messages: list,
    max_retries: int = 3,
    backoff_seconds: float = 1.0,
) -> tuple[str, str, float]:
    """Call LLM with retry on transient exceptions (network, timeout, rate limit).

    Attempts up to max_retries times. On each exception, waits
    backoff_seconds before retrying. Parse failures are handled by
    _parse_llm_response directly — those are not retried.

    Args:
        llm:             LangChain LLM instance
        messages:        List of SystemMessage + HumanMessage
        max_retries:     Maximum number of attempts (default 3)
        backoff_seconds: Wait time between retries (default 1.0s)

    Returns:
        Tuple of (decision, reasoning, confidence)
    """
    for attempt in range(max_retries):
        try:
            response = llm.invoke(messages)
            decision, reasoning, confidence = _parse_llm_response(
                response.content
            )
            # Return immediately on any valid parse result.
            # _parse_llm_response already handles bad JSON safely.
            return decision, reasoning, confidence
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(backoff_seconds)
                continue
            return "escalate", "llm call failed after retries", 0.0
    return "escalate", "max retries exhausted", 0.0


class DecisionAgent(BaseAgent):
    """Generates approve/revoke/escalate decisions via LLM for each entitlement."""

    def run(self, state: "CampaignState") -> dict:
        """Score all entitlements with LLM decisions and persist to DB.

        Args:
            state: CampaignState with populated scored_entitlements list.

        Returns:
            Partial state with decisions, pending_human_review, and status.
        """
        scored = state["scored_entitlements"]
        db = self.db

        self.log.info(
            "decision_agent starting",
            campaign_id=state["campaign_id"],
            entitlement_count=len(scored),
        )

        try:
            # ---------------------------------------------------------------- #
            # Look up Campaign record (created by HarvesterAgent)              #
            # ---------------------------------------------------------------- #
            campaign = (
                db.query(Campaign)
                .filter(Campaign.langgraph_thread_id == state["campaign_id"])
                .first()
            )

            decisions: list[dict] = []
            reviews: list[EntitlementReview] = []

            # ---------------------------------------------------------------- #
            # One LLM call per entitlement                                     #
            # ---------------------------------------------------------------- #
            for e in scored:
                payload = {
                    "user_name": e["user_name"],
                    "user_title": e["user_title"],
                    "user_department": e["user_department"],
                    "resource_name": e["resource_name"],
                    "resource_system": e["resource_system"],
                    "resource_sensitivity": e["resource_sensitivity"],
                    "role": e["role"],
                    "granted_at": e["granted_at"],
                    "last_used": e["last_used"],
                    "risk_score": e["risk_score"],
                    "risk_level": e["risk_level"],
                    "flags": e["flags"],
                }

                messages = [
                    SystemMessage(content=SYSTEM_PROMPT),
                    HumanMessage(content=json.dumps(payload)),
                ]
                decision, reasoning, confidence = _call_llm_with_retry(
                    self.llm, messages
                )

                self.log.info(
                    "decision made",
                    campaign_id=state["campaign_id"],
                    entitlement_id=e["entitlement_id"],
                    user_name=e["user_name"],
                    resource_name=e["resource_name"],
                    decision=decision,
                    confidence=confidence,
                )

                # Build decision dict (all scored keys + decision fields)
                decision_dict = {
                    **e,
                    "ai_decision": decision,
                    "ai_reasoning": reasoning,
                    "confidence": confidence,
                }
                decisions.append(decision_dict)

                # Prepare EntitlementReview DB row
                if campaign:
                    reviews.append(EntitlementReview(
                        campaign_id=campaign.id,
                        entitlement_id=uuid.UUID(e["entitlement_id"]),
                        risk_score=e["risk_score"],
                        risk_level=RiskLevel(e["risk_level"]),
                        ai_decision=EntitlementDecision(decision),
                        ai_reasoning=reasoning,
                    ))

            # ---------------------------------------------------------------- #
            # Build pending_human_review (revoke decisions only)               #
            # ---------------------------------------------------------------- #
            pending_human_review: list[dict] = [
                {**d, "human_decision": None, "human_reviewer": None}
                for d in decisions
                if d["ai_decision"] == "revoke"
            ]

            # ---------------------------------------------------------------- #
            # DB writes — single commit                                        #
            # ---------------------------------------------------------------- #
            if campaign:
                for review in reviews:
                    db.add(review)

                campaign.status = CampaignStatus.DECIDING

                approve_count = sum(1 for d in decisions if d["ai_decision"] == "approve")
                revoke_count = sum(1 for d in decisions if d["ai_decision"] == "revoke")
                escalate_count = sum(1 for d in decisions if d["ai_decision"] == "escalate")

                db.add(AuditLog(
                    campaign_id=campaign.id,
                    event="decisions_complete",
                    detail=(
                        f"approve={approve_count}, "
                        f"revoke={revoke_count}, "
                        f"escalate={escalate_count}"
                    ),
                    agent="decision",
                    timestamp=datetime.utcnow(),
                ))

                db.commit()

                self.log.info(
                    "decision_agent complete",
                    campaign_id=state["campaign_id"],
                    approve=approve_count,
                    revoke=revoke_count,
                    escalate=escalate_count,
                    pending_review=len(pending_human_review),
                )

            return {
                "status": "deciding",
                "decisions": decisions,
                "pending_human_review": pending_human_review,
            }

        except Exception as e:
            db.rollback()
            self.log.error(
                "decision_agent failed",
                campaign_id=state["campaign_id"],
                error=str(e),
            )
            return {"status": "failed", "error": str(e)}

        finally:
            db.close()
