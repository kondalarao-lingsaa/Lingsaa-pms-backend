from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, Unicode, func

from app.db.base import Base
from app.models.roles import SCHEMA

RISK_CATEGORIES = ["Technical", "Schedule", "Cost", "Resource", "Scope", "Quality", "Security", "External"]
# Open <-> Monitoring -> Mitigated -> Closed; any open risk can "occur", which raises an Issue.
RISK_STATUSES = ["Open", "Monitoring", "Mitigated", "Occurred", "Closed"]
RISK_TRANSITIONS = {
    "Open": ["Monitoring", "Mitigated", "Closed"],
    "Monitoring": ["Open", "Mitigated", "Closed"],
    "Mitigated": ["Open", "Closed"],
    "Occurred": ["Closed"],
    "Closed": ["Open"],
}

ISSUE_SEVERITIES = ["Low", "Medium", "High", "Critical"]
ISSUE_STATUSES = ["Open", "In Progress", "Resolved", "Closed"]
ISSUE_TRANSITIONS = {
    "Open": ["In Progress", "Resolved"],
    "In Progress": ["Open", "Resolved"],
    "Resolved": ["In Progress", "Closed"],
    "Closed": [],
}

CHANGE_TYPES = ["Scope", "Schedule", "Cost"]
CHANGE_STATUSES = ["Submitted", "Approved", "Rejected"]


def risk_level(score: int) -> str:
    """Score = probability x impact (1-25): 15+ High, 8+ Medium, else Low."""
    return "High" if score >= 15 else "Medium" if score >= 8 else "Low"


class Risk(Base):
    __tablename__ = "risks"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, nullable=False, index=True)
    project_id = Column(Integer, ForeignKey(f"{SCHEMA}.projects.id"), nullable=False, index=True)
    risk_key = Column(Unicode(40), nullable=False)
    title = Column(Unicode(200), nullable=False)
    description = Column(Unicode(2000), nullable=True)
    category = Column(Unicode(30), nullable=False)
    probability = Column(Integer, nullable=False)
    impact = Column(Integer, nullable=False)
    status = Column(Unicode(20), nullable=False, server_default="Open")
    owner_member_id = Column(Integer, ForeignKey(f"{SCHEMA}.project_members.id"), nullable=True)
    owner_name = Column(Unicode(200), nullable=True)
    mitigation = Column(Unicode(2000), nullable=True)
    contingency = Column(Unicode(2000), nullable=True)
    review_date = Column(Date, nullable=True)
    milestone_id = Column(Integer, ForeignKey(f"{SCHEMA}.milestones.id"), nullable=True)
    raised_by_name = Column(Unicode(200), nullable=True)
    closed_at = Column(DateTime, nullable=True)
    created_by = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    is_deleted = Column(Boolean, nullable=False, server_default="0")


class Issue(Base):
    __tablename__ = "issues"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, nullable=False, index=True)
    project_id = Column(Integer, ForeignKey(f"{SCHEMA}.projects.id"), nullable=False, index=True)
    issue_key = Column(Unicode(40), nullable=False)
    title = Column(Unicode(200), nullable=False)
    description = Column(Unicode(2000), nullable=True)
    severity = Column(Unicode(20), nullable=False, server_default="Medium")
    status = Column(Unicode(20), nullable=False, server_default="Open")
    owner_member_id = Column(Integer, ForeignKey(f"{SCHEMA}.project_members.id"), nullable=True)
    owner_name = Column(Unicode(200), nullable=True)
    due_date = Column(Date, nullable=True)
    risk_id = Column(Integer, ForeignKey(f"{SCHEMA}.risks.id"), nullable=True, index=True)
    task_id = Column(Integer, ForeignKey(f"{SCHEMA}.tasks.id"), nullable=True)
    resolution = Column(Unicode(2000), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    raised_by_name = Column(Unicode(200), nullable=True)
    created_by = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    is_deleted = Column(Boolean, nullable=False, server_default="0")


class ChangeRequest(Base):
    """A requested change to scope, schedule or cost. Approving it applies its impact to the project."""

    __tablename__ = "change_requests"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, nullable=False, index=True)
    project_id = Column(Integer, ForeignKey(f"{SCHEMA}.projects.id"), nullable=False, index=True)
    cr_key = Column(Unicode(40), nullable=False)
    title = Column(Unicode(200), nullable=False)
    reason = Column(Unicode(2000), nullable=False)
    change_type = Column(Unicode(20), nullable=False)
    cost_impact = Column(Numeric(14, 2), nullable=True)
    days_impact = Column(Integer, nullable=True)
    milestone_id = Column(Integer, ForeignKey(f"{SCHEMA}.milestones.id"), nullable=True)
    status = Column(Unicode(20), nullable=False, server_default="Submitted")
    decision_note = Column(Unicode(1000), nullable=True)
    decided_by = Column(Integer, nullable=True)
    decided_by_name = Column(Unicode(200), nullable=True)
    decided_at = Column(DateTime, nullable=True)
    applied_summary = Column(Unicode(500), nullable=True)
    raised_by = Column(Integer, nullable=True)
    raised_by_name = Column(Unicode(200), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    is_deleted = Column(Boolean, nullable=False, server_default="0")


class RecordCounter(Base):
    """Per-project sequence for risk / issue / change-request keys (…-R1, …-I1, …-CR1)."""

    __tablename__ = "record_counters"
    __table_args__ = {"schema": SCHEMA}

    project_id = Column(Integer, primary_key=True, autoincrement=False)
    kind = Column(Unicode(4), primary_key=True)
    last_no = Column(Integer, nullable=False, server_default="0")
