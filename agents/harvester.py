"""
agents/harvester.py
-------------------
HarvesterAgent — collects all active entitlements for a campaign.

Phase 2 stub: logs and returns empty entitlements list.
Phase 3 will implement real DB queries joining User, Resource, and
Entitlement tables, returning fully-populated dicts matching the
scored_entitlements key contract defined in orchestrator/state.py.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from agents.base import BaseAgent

if TYPE_CHECKING:
    from orchestrator.state import CampaignState


class HarvesterAgent(BaseAgent):
    """Fetches all active user-resource entitlements from the database."""

    def run(self, state: "CampaignState") -> dict:
        """Harvest entitlements for the campaign.

        Returns:
            Partial state with status="harvesting" and entitlements=[].
        """
        self.log.info("harvester stub running", campaign_id=state["campaign_id"])

        # TODO Phase 3: query Entitlement join User join Resource
        # and return fully-populated dicts.
        return {
            "status": "harvesting",
            "entitlements": [],
        }
