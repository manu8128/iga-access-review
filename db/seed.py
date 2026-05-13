from datetime import datetime, timedelta
import random
from db.session import SessionLocal
from db.models import (
    Base, Department, User, Resource, Entitlement,
    RiskLevel
)
from config.settings import settings
from sqlalchemy import create_engine

engine = create_engine(settings.database_url)
Base.metadata.create_all(bind=engine)

def seed():
    db = SessionLocal()
    try:
        # Departments
        depts = {
            "Finance": Department(name="Finance"),
            "Engineering": Department(name="Engineering"),
            "HR": Department(name="HR"),
        }
        for d in depts.values():
            db.add(d)
        db.flush()

        # Managers
        finance_mgr = User(name="Sarah Chen", email="s.chen@acme.com",
                           title="Finance Director", department_id=depts["Finance"].id)
        eng_mgr = User(name="Raj Patel", email="r.patel@acme.com",
                       title="VP Engineering", department_id=depts["Engineering"].id)
        hr_mgr = User(name="Lisa Park", email="l.park@acme.com",
                      title="HR Director", department_id=depts["HR"].id)
        for m in [finance_mgr, eng_mgr, hr_mgr]:
            db.add(m)
        db.flush()

        # Users
        users = [
            User(name="Alice Wong", email="a.wong@acme.com", title="Senior Analyst",
                 department_id=depts["Finance"].id, manager_id=finance_mgr.id),
            User(name="Bob Kumar", email="b.kumar@acme.com", title="Junior Analyst",
                 department_id=depts["Finance"].id, manager_id=finance_mgr.id),
            User(name="Carol Davis", email="c.davis@acme.com", title="Staff Engineer",
                 department_id=depts["Engineering"].id, manager_id=eng_mgr.id),
            User(name="Dan Smith", email="d.smith@acme.com", title="Junior Engineer",
                 department_id=depts["Engineering"].id, manager_id=eng_mgr.id),
            User(name="Eve Johnson", email="e.johnson@acme.com", title="HR Specialist",
                 department_id=depts["HR"].id, manager_id=hr_mgr.id),
            User(name="Frank Lee", email="f.lee@acme.com", title="DevOps Engineer",
                 department_id=depts["Engineering"].id, manager_id=eng_mgr.id),
        ]
        for u in users:
            db.add(u)
        db.flush()

        # Resources (mock systems)
        resources = [
            Resource(name="SAP Finance Admin", system="SAP",
                     sensitivity=RiskLevel.CRITICAL,
                     description="Full admin access to SAP finance module"),
            Resource(name="SAP Finance Read", system="SAP",
                     sensitivity=RiskLevel.MEDIUM,
                     description="Read-only access to SAP finance data"),
            Resource(name="AWS Production Admin", system="AWS",
                     sensitivity=RiskLevel.CRITICAL,
                     description="Admin access to production AWS account"),
            Resource(name="AWS Dev Access", system="AWS",
                     sensitivity=RiskLevel.LOW,
                     description="Developer access to dev/staging AWS"),
            Resource(name="GitHub Org Admin", system="GitHub",
                     sensitivity=RiskLevel.HIGH,
                     description="Organization admin on GitHub"),
            Resource(name="GitHub Repo Read", system="GitHub",
                     sensitivity=RiskLevel.LOW,
                     description="Read access to all repos"),
            Resource(name="HRIS Full Access", system="Workday",
                     sensitivity=RiskLevel.CRITICAL,
                     description="Full access to HR information system"),
            Resource(name="Payroll View", system="Workday",
                     sensitivity=RiskLevel.HIGH,
                     description="View payroll data"),
        ]
        for r in resources:
            db.add(r)
        db.flush()

        now = datetime.utcnow()

        # Entitlements — mix of active/stale/suspicious
        entitlement_data = [
            # Alice: finance user with legitimate access
            (users[0], resources[0], "Admin", now - timedelta(days=200), now - timedelta(days=2)),
            (users[0], resources[1], "Read", now - timedelta(days=200), now - timedelta(days=1)),
            # Bob: junior analyst with overly broad access (red flag)
            (users[1], resources[0], "Admin", now - timedelta(days=400), now - timedelta(days=180)),  # stale!
            (users[1], resources[6], "Full Access", now - timedelta(days=100), None),  # never used!
            # Carol: engineer with appropriate access
            (users[2], resources[3], "Developer", now - timedelta(days=150), now - timedelta(days=1)),
            (users[2], resources[5], "Read", now - timedelta(days=150), now - timedelta(days=3)),
            (users[2], resources[4], "Admin", now - timedelta(days=300), now - timedelta(days=30)),
            # Dan: junior engineer with prod access (suspicious)
            (users[3], resources[2], "Admin", now - timedelta(days=50), now - timedelta(days=200)),  # stale prod admin!
            (users[3], resources[3], "Developer", now - timedelta(days=50), now - timedelta(days=1)),
            # Eve: HR with expected access
            (users[4], resources[6], "Full Access", now - timedelta(days=365), now - timedelta(days=1)),
            (users[4], resources[7], "View", now - timedelta(days=365), now - timedelta(days=5)),
            # Frank: DevOps — broad access expected but SAP access is SoD violation
            (users[5], resources[2], "Admin", now - timedelta(days=100), now - timedelta(days=2)),
            (users[5], resources[0], "Admin", now - timedelta(days=200), now - timedelta(days=90)),  # SoD: DevOps + Finance Admin
        ]

        for user, resource, role, granted_at, last_used in entitlement_data:
            db.add(Entitlement(
                user_id=user.id,
                resource_id=resource.id,
                role=role,
                granted_at=granted_at,
                last_used=last_used,
                is_active=True,
            ))

        db.commit()
        print(f"Seeded: {len(depts)} departments, {len(users)+3} users, "
              f"{len(resources)} resources, {len(entitlement_data)} entitlements")
    finally:
        db.close()

if __name__ == "__main__":
    seed()