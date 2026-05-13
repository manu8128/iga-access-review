"""
agents/notifier.py
------------------
NotifierAgent — sends notifications to managers and reviewers.

Phase 2 stub: logs and sets notified=False.
Phase 5 will implement actual notification dispatch (email/Slack)
after the HITL checkpoint resolves human decisions.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from agents.base import BaseAgent

if TYPE_CHECKING:
    from orchestrator.state import CampaignState


class NotifierAgent(BaseAgent):
    """Dispatches notifications about campaign decisions."""

    def run(self, state: "CampaignState") -> dict:
        """Send notifications for all decisions in the campaign.

        Returns:
            Partial state with status="notifying" and notified=False.
        """
        self.log.info(
            "notifier stub running",
            campaign_id=state["campaign_id"],
            decision_count=len(state["decisions"]),
        )

        # TODO Phase 5: send emails/Slack messages for revoke decisions,
        # notify managers of ESCALATE decisions, confirm APPROVE to users.
        return {
            "status": "notifying",
            "notified": False,
        }
