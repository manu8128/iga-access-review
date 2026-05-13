from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float, Boolean,
    DateTime, ForeignKey, Text, Enum as SAEnum
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship
import uuid
import enum

Base = declarative_base()

class RiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class EntitlementDecision(str, enum.Enum):
    APPROVE = "approve"
    REVOKE = "revoke"
    ESCALATE = "escalate"
    PENDING = "pending"

class CampaignStatus(str, enum.Enum):
    CREATED = "created"
    HARVESTING = "harvesting"
    SCORING = "scoring"
    DECIDING = "deciding"
    AWAITING_HUMAN = "awaiting_human"
    NOTIFYING = "notifying"
    AUDITING = "auditing"
    COMPLETED = "completed"
    FAILED = "failed"

class Department(Base):
    __tablename__ = "departments"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False, unique=True)
    users = relationship("User", back_populates="department")

class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    email = Column(String(200), nullable=False, unique=True)
    title = Column(String(200))
    department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id"))
    manager_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    department = relationship("Department", back_populates="users")
    manager = relationship("User", remote_side=[id])
    entitlements = relationship("Entitlement", back_populates="user")

class Resource(Base):
    __tablename__ = "resources"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    system = Column(String(100), nullable=False)   # e.g. "SAP", "AWS", "GitHub"
    sensitivity = Column(SAEnum(RiskLevel), default=RiskLevel.LOW)
    description = Column(Text)
    entitlements = relationship("Entitlement", back_populates="resource")

class Entitlement(Base):
    __tablename__ = "entitlements"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    resource_id = Column(UUID(as_uuid=True), ForeignKey("resources.id"), nullable=False)
    role = Column(String(200), nullable=False)       # e.g. "Admin", "Read-Only"
    granted_at = Column(DateTime, nullable=False)
    last_used = Column(DateTime, nullable=True)      # null = never used
    is_active = Column(Boolean, default=True)

    user = relationship("User", back_populates="entitlements")
    resource = relationship("Resource", back_populates="entitlements")

class Campaign(Base):
    __tablename__ = "campaigns"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    status = Column(SAEnum(CampaignStatus), default=CampaignStatus.CREATED)
    langgraph_thread_id = Column(String(200), unique=True)  # for HITL resume
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    reviews = relationship("EntitlementReview", back_populates="campaign")

class EntitlementReview(Base):
    __tablename__ = "entitlement_reviews"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=False)
    entitlement_id = Column(UUID(as_uuid=True), ForeignKey("entitlements.id"), nullable=False)
    risk_score = Column(Float, nullable=True)         # 0-100
    risk_level = Column(SAEnum(RiskLevel), nullable=True)
    ai_decision = Column(SAEnum(EntitlementDecision), default=EntitlementDecision.PENDING)
    ai_reasoning = Column(Text, nullable=True)
    human_decision = Column(SAEnum(EntitlementDecision), nullable=True)
    human_reviewer = Column(String(200), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)

    campaign = relationship("Campaign", back_populates="reviews")

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=False)
    event = Column(String(200), nullable=False)
    detail = Column(Text, nullable=True)
    agent = Column(String(100), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)