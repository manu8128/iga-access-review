"""
agents/audit.py
---------------
AuditAgent — pure PostgreSQL audit trail writer. No LLM calls.

Marks the Campaign as COMPLETED, writes one AuditLog entry per
entitlement decision, and adds a final campaign_complete summary entry.
All writes land in a single commit.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from agents.base import BaseAgent
from db.models import AuditLog, Campaign, CampaignStatus

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
            # 3. One AuditLog entry per entitlement decision                  #
            # ---------------------------------------------------------------- #
            for d in decisions:
                db.add(AuditLog(
                    campaign_id=campaign.id,
                    event="entitlement_decision",
                    detail=(
                        f"{d['user_name']} | {d['resource_name']} | "
                        f"{d['ai_decision']} | score={d['risk_score']}"
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

            db.add(AuditLog(
                campaign_id=campaign.id,
                event="campaign_complete",
                detail=(
                    f"Campaign {state['campaign_name']} completed. "
                    f"Total={total}, Revoke={revoke}, "
                    f"Approve={approve}, Escalate={escalate}"
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
