"""
agents/risk_scorer.py
---------------------
RiskScorerAgent — scores each entitlement for risk.

Phase 2 stub: logs and returns empty scored_entitlements list.
Phase 4 will implement LLM-assisted scoring using factors such as:
  - Days since last_used (staleness)
  - Role sensitivity vs. user title (over-privilege)
  - Separation of Duties violations (cross-system admin access)
  - Resource sensitivity level (CRITICAL/HIGH resources weighted higher)
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from agents.base import BaseAgent

if TYPE_CHECKING:
    from orchestrator.state import CampaignState


class RiskScorerAgent(BaseAgent):
    """Assigns a risk_score (0-100) and risk_level to each entitlement."""

    def run(self, state: "CampaignState") -> dict:
        """Score all harvested entitlements.

        Returns:
            Partial state with status="scoring" and scored_entitlements=[].
        """
        self.log.info(
            "risk_scorer stub running",
            campaign_id=state["campaign_id"],
            entitlement_count=len(state["entitlements"]),
        )

        # TODO Phase 4: iterate state["entitlements"], compute risk_score
        # and risk_level, append flags list, return scored dicts.
        return {
            "status": "scoring",
            "scored_entitlements": [],
        }
