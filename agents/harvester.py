"""
agents/harvester.py
-------------------
HarvesterAgent — collects all active entitlements for a campaign.

Performs a single 4-table JOIN (Entitlement → User → Resource → Department,
plus an outer-join to the manager User alias) and writes two AuditLog
entries to the database before returning.

DB write sequence:
  1. Create Campaign record (status=HARVESTING, flushed for id)
  2. AuditLog: harvest_started
  3. Execute join query for all is_active entitlements
  4. AuditLog: harvest_complete  (with count)
  5. Commit
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy.orm import aliased

from agents.base import BaseAgent
from db.models import AuditLog, Campaign, CampaignStatus, Department, Entitlement, Resource, User

if TYPE_CHECKING:
    from orchestrator.state import CampaignState


class HarvesterAgent(BaseAgent):
    """Fetches all active user-resource entitlements and persists a Campaign record."""

    def run(self, state: "CampaignState") -> dict:
        """Harvest entitlements for the campaign.

        Opens the lazy self.db session, creates the Campaign row,
        runs a single multi-join query, writes audit logs, commits,
        and returns the entitlement list.

        Returns:
            Partial state with status="harvesting" and the entitlements list,
            or status="failed" and error message on any exception.
        """
        db = self.db
        self.log.info(
            "harvester starting",
            campaign_id=state["campaign_id"],
            campaign_name=state["campaign_name"],
        )

        try:
            # ---------------------------------------------------------------- #
            # 1. Create Campaign record                                         #
            # ---------------------------------------------------------------- #
            campaign = Campaign(
                name=state["campaign_name"],
                status=CampaignStatus.HARVESTING,
                langgraph_thread_id=state["campaign_id"],
                created_at=datetime.utcnow(),
            )
            db.add(campaign)
            db.flush()  # materialise campaign.id without committing

            # ---------------------------------------------------------------- #
            # 2. AuditLog — harvest_started                                     #
            # ---------------------------------------------------------------- #
            db.add(AuditLog(
                campaign_id=campaign.id,
                event="harvest_started",
                detail=f"Campaign {state['campaign_name']} harvest initiated",
                agent="harvester",
                timestamp=datetime.utcnow(),
            ))

            # ---------------------------------------------------------------- #
            # 3. Query: single JOIN across 4 tables                             #
            # Explicit joins chosen over joinedload because:                   #
            #   - joinedload is designed for relationship collections, not      #
            #     multi-table column assembly                                   #
            #   - a single SQL statement is more efficient than N+1 queries    #
            #   - outerjoin on Manager handles nullable manager_id cleanly     #
            # ---------------------------------------------------------------- #
            Manager = aliased(User)

            rows = (
                db.query(Entitlement, User, Resource, Department, Manager)
                .join(User, Entitlement.user_id == User.id)
                .join(Resource, Entitlement.resource_id == Resource.id)
                .join(Department, User.department_id == Department.id)
                .outerjoin(Manager, User.manager_id == Manager.id)
                .filter(Entitlement.is_active == True)  # noqa: E712
                .all()
            )

            # ---------------------------------------------------------------- #
            # 4. Build entitlement dicts (exact key contract from state.py)    #
            # ---------------------------------------------------------------- #
            entitlements: list[dict] = []
            for entitlement, user, resource, department, manager in rows:
                entitlements.append({
                    "entitlement_id": str(entitlement.id),
                    "user_id": str(entitlement.user_id),
                    "user_name": user.name,
                    "user_title": user.title,
                    "user_department": department.name,
                    "manager_email": manager.email if manager else None,
                    "resource_id": str(entitlement.resource_id),
                    "resource_name": resource.name,
                    "resource_system": resource.system,
                    "resource_sensitivity": resource.sensitivity.value,
                    "role": entitlement.role,
                    "granted_at": entitlement.granted_at.isoformat(),
                    "last_used": (
                        entitlement.last_used.isoformat()
                        if entitlement.last_used else None
                    ),
                })

            count = len(entitlements)
            self.log.info(
                "harvester query complete",
                campaign_id=state["campaign_id"],
                entitlement_count=count,
            )

            # ---------------------------------------------------------------- #
            # 5. AuditLog — harvest_complete                                    #
            # ---------------------------------------------------------------- #
            db.add(AuditLog(
                campaign_id=campaign.id,
                event="harvest_complete",
                detail=f"Harvested {count} active entitlements",
                agent="harvester",
                timestamp=datetime.utcnow(),
            ))

            db.commit()

            return {
                "status": "harvesting",
                "entitlements": entitlements,
            }

        except Exception as e:
            db.rollback()
            self.log.error(
                "harvester failed",
                campaign_id=state["campaign_id"],
                error=str(e),
            )
            return {"status": "failed", "error": str(e)}

        finally:
            db.close()
