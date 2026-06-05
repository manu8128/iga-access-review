"""
agents/notifier.py
------------------
NotifierAgent — LLM-driven manager notification email drafting.

Groups decisions by manager_email and makes one LLM call per manager
to draft a professional access review summary email. Emails are logged
but NOT sent — actual dispatch will be wired in Phase 5.

Uses effective_decision (human override if present, otherwise ai_decision)
so manager emails reflect the final outcome after HITL review.

Resilient: parse failure for any one manager is logged and skipped;
the campaign is not aborted.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage

from agents.base import BaseAgent

if TYPE_CHECKING:
    from orchestrator.state import CampaignState

# --------------------------------------------------------------------------- #
# Constants                                                                    #
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = """You are an access review notification agent. Draft a professional \
email to a manager summarising their team's access review decisions. \
Be concise, factual, and action-oriented. Use effective_decision as \
the final decision for each entitlement — this reflects any human \
review overrides. Where ai_overridden is true, note that the \
AI recommendation was reviewed and overridden by a human reviewer. \
List any remaining revoke decisions prominently. \
Respond with valid JSON only."""

# Keys included in the per-decision payload sent to the LLM
_DECISION_KEYS = (
    "user_name",
    "resource_name",
    "role",
    "ai_decision",
    "ai_reasoning",
    "risk_level",
)


class NotifierAgent(BaseAgent):
    """Drafts access review summary emails for each manager via LLM."""

    def run(self, state: "CampaignState") -> dict:
        """Draft notification emails for all managers with decisions.

        One LLM call per unique manager_email. Emails are logged, not sent.

        Args:
            state: CampaignState with populated decisions list.

        Returns:
            Partial state with status="notifying" and notified=True.
        """
        self.log.info(
            "notifier_agent starting",
            campaign_id=state["campaign_id"],
            decision_count=len(state["decisions"]),
        )

        try:
            # ---------------------------------------------------------------- #
            # Build human decision lookup from pending_human_review            #
            # ---------------------------------------------------------------- #
            human_review_map: dict[str, dict] = {
                p["entitlement_id"]: p
                for p in state.get("pending_human_review", [])
                if p.get("human_decision") is not None
            }

            # ---------------------------------------------------------------- #
            # Group decisions by manager_email (skip None emails)              #
            # ---------------------------------------------------------------- #
            groups: dict[str, list[dict]] = defaultdict(list)
            for d in state["decisions"]:
                if d.get("manager_email"):
                    groups[d["manager_email"]].append(d)

            self.log.info(
                "notifier: managers to notify",
                campaign_id=state["campaign_id"],
                manager_count=len(groups),
            )

            # ---------------------------------------------------------------- #
            # One LLM call per manager                                         #
            # ---------------------------------------------------------------- #
            for manager_email, manager_decisions in groups.items():
                compact_decisions: list[dict] = []
                for d in manager_decisions:
                    human_info = human_review_map.get(d.get("entitlement_id", ""))
                    effective = (
                        human_info["human_decision"]
                        if human_info else d["ai_decision"]
                    )
                    was_overridden = (
                        human_info is not None
                        and human_info["human_decision"] != d["ai_decision"]
                    )
                    entry = {k: d[k] for k in _DECISION_KEYS if k in d}
                    entry["effective_decision"] = effective
                    entry["human_reviewed"] = human_info is not None
                    entry["ai_overridden"] = was_overridden
                    compact_decisions.append(entry)

                payload = {
                    "manager_email": manager_email,
                    "decisions": compact_decisions,
                }

                try:
                    response = self.llm.invoke([
                        SystemMessage(content=SYSTEM_PROMPT),
                        HumanMessage(content=json.dumps(payload)),
                    ])

                    parsed = json.loads(response.content)
                    subject = str(parsed.get("subject", "Access Review Summary"))
                    body = str(parsed.get("body", ""))

                    self.log.info(
                        "email drafted",
                        campaign_id=state["campaign_id"],
                        manager=manager_email,
                        subject=subject,
                        decision_count=len(manager_decisions),
                    )

                except (json.JSONDecodeError, ValueError, TypeError, AttributeError) as parse_err:
                    self.log.error(
                        "notifier: failed to draft email for manager",
                        campaign_id=state["campaign_id"],
                        manager=manager_email,
                        error=str(parse_err),
                    )
                    # Continue to next manager — do not abort the campaign

            return {
                "status": "notifying",
                "notified": True,
            }

        except Exception as e:
            self.log.error(
                "notifier_agent failed",
                campaign_id=state["campaign_id"],
                error=str(e),
            )
            return {"status": "failed", "error": str(e), "notified": False}
