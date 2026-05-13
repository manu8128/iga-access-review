"""
agents/audit.py
---------------
AuditAgent — writes a compliance-grade audit trail for the campaign.

Phase 2 stub: logs and sets audit_complete=False.
Phase 5 will implement writing AuditLog records to PostgreSQL for
every entitlement decision made during the campaign, including
both AI decisions and any human overrides from the HITL checkpoint.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from agents.base import BaseAgent

if TYPE_CHECKING:
    from orchestrator.state import CampaignState


class AuditAgent(BaseAgent):
    """Persists compliance audit logs for the completed campaign."""

    def run(self, state: "CampaignState") -> dict:
        """Write audit log entries for all campaign decisions.

        Returns:
            Partial state with status="auditing" and audit_complete=False.
        """
        self.log.info(
            "audit stub running",
            campaign_id=state["campaign_id"],
            decision_count=len(state["decisions"]),
        )

        # TODO Phase 5: persist AuditLog rows to PostgreSQL for each
        # decision (ai + human override), then set audit_complete=True
        # and update Campaign.status to COMPLETED in the DB.
        return {
            "status": "auditing",
            "audit_complete": False,
        }
