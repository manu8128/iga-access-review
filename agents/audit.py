"""
agents/audit.py
---------------
AuditAgent — pure PostgreSQL audit trail writer. No LLM calls.

Marks the Campaign as COMPLETED, updates EntitlementReview rows with any
human decisions from pending_human_review, writes one AuditLog entry per
entitlement decision, and adds a final campaign_complete summary entry.
All writes land in a single commit.
"""
from __future__ import annotations

import uuid as uuid_module
from datetime import datetime
from typing import TYPE_CHECKING

from agents.base import BaseAgent
from db.models import (
    AuditLog,
    Campaign,
    CampaignStatus,
    EntitlementDecision,
    EntitlementReview,
)

if TYPE_CHECKING:
    from orchestrator.state import CampaignState


class AuditAgent(BaseAgent):
    """Persists the compliance audit trail and marks the campaign complete."""

    def run(self, state: "CampaignState") -> dict:
        """Write all audit records and transition Campaign to COMPLETED.

        Args:
            state: CampaignState with populated decisions list.

        Returns:
            Partial state with status="completed" and audit_complete=True.
        """
        decisions: list[dict] = state["decisions"]
        db = self.db

        self.log.info(
            "audit_agent starting",
            campaign_id=state["campaign_id"],
            decision_count=len(decisions),
        )

        try:
            # ---------------------------------------------------------------- #
            # 1. Look up the Campaign record                                   #
            # ---------------------------------------------------------------- #
            campaign = (
                db.query(Campaign)
                .filter(Campaign.langgraph_thread_id == state["campaign_id"])
                .first()
            )

            # ---------------------------------------------------------------- #
            # 2. Mark Campaign COMPLETED                                       #
            # ---------------------------------------------------------------- #
            campaign.status = CampaignStatus.COMPLETED
            campaign.completed_at = datetime.utcnow()

            # ---------------------------------------------------------------- #
            # 2.5. Update EntitlementReview rows with human decisions          #
            # ---------------------------------------------------------------- #
            # Build lookup: entitlement_id → human review data (reviewed only)
            human_review_map: dict[str, dict] = {
                p["entitlement_id"]: p
                for p in state.get("pending_human_review", [])
                if p.get("human_decision") is not None
            }

            if human_review_map:
                for entitlement_id_str, review_data in human_review_map.items():
                    review_row = (
                        db.query(EntitlementReview)
                        .filter(
                            EntitlementReview.campaign_id == campaign.id,
                            EntitlementReview.entitlement_id == uuid_module.UUID(
                                entitlement_id_str
                            ),
                        )
                        .first()
                    )
                    if review_row:
                        review_row.human_decision = EntitlementDecision(
                            review_data["human_decision"]
                        )
                        review_row.human_reviewer = review_data.get("human_reviewer")
                        review_row.reviewed_at = datetime.utcnow()

            # ---------------------------------------------------------------- #
            # 3. One AuditLog entry per entitlement decision                  #
            # ---------------------------------------------------------------- #
            for d in decisions:
                human_info = human_review_map.get(d["entitlement_id"])
                human_suffix = (
                    f" | human={human_info['human_decision']}"
                    f" by {human_info['human_reviewer']}"
                    if human_info else ""
                )
                db.add(AuditLog(
                    campaign_id=campaign.id,
                    event="entitlement_decision",
                    detail=(
                        f"{d['user_name']} | {d['resource_name']} | "
                        f"ai={d['ai_decision']} | score={d['risk_score']}"
                        f"{human_suffix}"
                    ),
                    agent="audit",
                    timestamp=datetime.utcnow(),
                ))

            # ---------------------------------------------------------------- #
            # 4. Final campaign_complete summary entry                         #
            # ---------------------------------------------------------------- #
            total = len(decisions)
            approve = sum(1 for d in decisions if d["ai_decision"] == "approve")
            revoke = sum(1 for d in decisions if d["ai_decision"] == "revoke")
            escalate = sum(1 for d in decisions if d["ai_decision"] == "escalate")

            overrides = sum(
                1 for p in state.get("pending_human_review", [])
                if p.get("human_decision") is not None
                and p["human_decision"] != p["ai_decision"]
            )

            db.add(AuditLog(
                campaign_id=campaign.id,
                event="campaign_complete",
                detail=(
                    f"Campaign {state['campaign_name']} completed. "
                    f"Total={total}, Revoke={revoke}, "
                    f"Approve={approve}, Escalate={escalate}, "
                    f"HumanOverrides={overrides}"
                ),
                agent="audit",
                timestamp=datetime.utcnow(),
            ))

            # ---------------------------------------------------------------- #
            # 5. Single commit                                                 #
            # ---------------------------------------------------------------- #
            db.commit()

            self.log.info(
                "campaign complete",
                campaign_id=state["campaign_id"],
                total=total,
                approve=approve,
                revoke=revoke,
                escalate=escalate,
                human_overrides=overrides,
            )

            return {
                "status": "completed",
                "audit_complete": True,
            }

        except Exception as e:
            db.rollback()
            self.log.error(
                "audit_agent failed",
                campaign_id=state["campaign_id"],
                error=str(e),
            )
            return {"status": "failed", "error": str(e), "audit_complete": False}

        finally:
            db.close()
