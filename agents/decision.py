"""
agents/decision.py
------------------
DecisionAgent — makes APPROVE / REVOKE / ESCALATE recommendations.

Phase 2 stub: logs and returns empty decisions list.
Phase 4 will implement LLM-driven decision making using scored_entitlements,
producing ai_decision, ai_reasoning, and a confidence score per entitlement.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from agents.base import BaseAgent

if TYPE_CHECKING:
    from orchestrator.state import CampaignState


class DecisionAgent(BaseAgent):
    """Recommends approve/revoke/escalate for each scored entitlement."""

    def run(self, state: "CampaignState") -> dict:
        """Generate AI decisions for all scored entitlements.

        Returns:
            Partial state with status="deciding" and decisions=[].
        """
        self.log.info(
            "decision stub running",
            campaign_id=state["campaign_id"],
            scored_count=len(state["scored_entitlements"]),
        )

        # TODO Phase 4: iterate state["scored_entitlements"], call LLM,
        # produce ai_decision + ai_reasoning + confidence per entitlement.
        return {
            "status": "deciding",
            "decisions": [],
        }
