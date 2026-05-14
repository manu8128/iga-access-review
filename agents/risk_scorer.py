"""
agents/risk_scorer.py
---------------------
RiskScorerAgent — scores each entitlement using pure rule-based logic.

No LLM calls. Scoring is deterministic and reproducible.

Scoring rules (additive, capped at 100):
  Base score   — driven by resource sensitivity
  Staleness    — driven by days since last_used
  SoD          — user holds both a Finance AND an IT/DevOps resource
  Role mismatch — Admin role assigned to a Junior or Intern title

Risk level thresholds (using >= comparison):
  score >= 81 → critical
  score >= 61 → high
  score >= 31 → medium
  score >= 0  → low
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from agents.base import BaseAgent

if TYPE_CHECKING:
    from orchestrator.state import CampaignState

# --------------------------------------------------------------------------- #
# Scoring tables                                                               #
# --------------------------------------------------------------------------- #

SENSITIVITY_SCORES: dict[str, int] = {
    "critical": 40,
    "high": 30,
    "medium": 15,
    "low": 5,
}

# Checked in order — first matching threshold wins (score >= threshold)
RISK_THRESHOLDS: list[tuple[int, str]] = [
    (81, "critical"),
    (61, "high"),
    (31, "medium"),
    (0,  "low"),
]

# Systems that represent Finance access (SoD left-side)
FINANCE_SYSTEMS: frozenset[str] = frozenset({"SAP"})

# Systems that represent IT / DevOps access (SoD right-side)
IT_SYSTEMS: frozenset[str] = frozenset({"AWS", "GitHub"})


def _risk_level(score: float) -> str:
    """Map a numeric score to a risk level string using >= comparison."""
    return next(level for threshold, level in RISK_THRESHOLDS if score >= threshold)


def _days_since(iso_timestamp: str) -> int:
    """Return days elapsed since an ISO-format timestamp string."""
    last_used_dt = datetime.fromisoformat(iso_timestamp)
    # Handle both naive and aware datetimes from the DB
    now = datetime.now(tz=last_used_dt.tzinfo) if last_used_dt.tzinfo else datetime.utcnow()
    return (now - last_used_dt).days


class RiskScorerAgent(BaseAgent):
    """Assigns risk_score, risk_level, and flags to each entitlement."""

    def run(self, state: "CampaignState") -> dict:
        """Score all harvested entitlements using rule-based logic.

        Args:
            state: CampaignState with a populated entitlements list.

        Returns:
            Partial state with status="scoring" and scored_entitlements list,
            or status="failed" and error message on any exception.
        """
        entitlements: list[dict] = state["entitlements"]

        self.log.info(
            "risk_scorer starting",
            campaign_id=state["campaign_id"],
            entitlement_count=len(entitlements),
        )

        if not entitlements:
            return {
                "status": "scoring",
                "scored_entitlements": [],
            }

        try:
            # ---------------------------------------------------------------- #
            # Pre-compute SoD lookup: user_id → set of resource systems        #
            # Must look across ALL entitlements per user, not just the current  #
            # row, to correctly detect cross-system violations.                 #
            # ---------------------------------------------------------------- #
            user_systems: dict[str, set[str]] = {}
            for e in entitlements:
                uid = e["user_id"]
                if uid not in user_systems:
                    user_systems[uid] = set()
                user_systems[uid].add(e["resource_system"])

            scored_entitlements: list[dict] = []

            for e in entitlements:
                score: float = 0.0
                flags: list[str] = []

                # -------------------------------------------------------------- #
                # Base score from resource sensitivity                            #
                # -------------------------------------------------------------- #
                score += SENSITIVITY_SCORES.get(e["resource_sensitivity"], 0)

                # -------------------------------------------------------------- #
                # Staleness score from last_used                                  #
                # -------------------------------------------------------------- #
                if e["last_used"] is None:
                    score += 30  # never used
                else:
                    days = _days_since(e["last_used"])
                    if days >= 180:
                        score += 25
                    elif days >= 90:
                        score += 15
                    elif days >= 30:
                        score += 5
                    # else: used within 30 days → +0

                # -------------------------------------------------------------- #
                # SoD violation: Finance AND IT/DevOps resources for same user   #
                # -------------------------------------------------------------- #
                user_sys = user_systems.get(e["user_id"], set())
                has_finance = bool(user_sys & FINANCE_SYSTEMS)
                has_it = bool(user_sys & IT_SYSTEMS)
                if has_finance and has_it:
                    score += 20
                    flags.append("sod_violation")

                # -------------------------------------------------------------- #
                # Role mismatch: Admin role on a Junior / Intern title           #
                # -------------------------------------------------------------- #
                role: str = e.get("role", "")
                title: str = e.get("user_title", "")
                if "Admin" in role and ("Junior" in title or "Intern" in title):
                    score += 15
                    flags.append("role_mismatch")

                # -------------------------------------------------------------- #
                # Cap score and derive risk level                                 #
                # -------------------------------------------------------------- #
                score = min(score, 100.0)
                level = _risk_level(score)

                # Log critical-scored entitlements individually
                if level == "critical":
                    self.log.warning(
                        "critical entitlement detected",
                        campaign_id=state["campaign_id"],
                        entitlement_id=e["entitlement_id"],
                        user_name=e["user_name"],
                        resource_name=e["resource_name"],
                        risk_score=score,
                        flags=flags,
                    )

                scored_entitlements.append({
                    **e,
                    "risk_score": score,
                    "risk_level": level,
                    "flags": flags,
                })

            self.log.info(
                "risk_scorer complete",
                campaign_id=state["campaign_id"],
                scored_count=len(scored_entitlements),
                critical_count=sum(
                    1 for s in scored_entitlements if s["risk_level"] == "critical"
                ),
                high_count=sum(
                    1 for s in scored_entitlements if s["risk_level"] == "high"
                ),
            )

            return {
                "status": "scoring",
                "scored_entitlements": scored_entitlements,
            }

        except Exception as e:
            self.log.error(
                "risk_scorer failed",
                campaign_id=state["campaign_id"],
                error=str(e),
            )
            return {"status": "failed", "error": str(e)}
