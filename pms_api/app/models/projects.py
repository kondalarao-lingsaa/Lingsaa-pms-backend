from sqlalchemy import Boolean, Column, Date, DateTime, Integer, Numeric, Unicode, UniqueConstraint, func

from app.db.base import Base
from app.models.roles import SCHEMA

PROJECT_STATUSES = ["Draft", "Pending Approval", "Approved", "Active", "On Hold", "Closed"]
PROJECT_PRIORITIES = ["Low", "Medium", "High", "Critical"]

# Allowed status moves. Status only changes through the status endpoint, never by editing a project.
PROJECT_TRANSITIONS = {
    "Draft": ["Pending Approval"],
    "Pending Approval": ["Approved", "Draft"],
    "Approved": ["Active"],
    "Active": ["On Hold", "Closed"],
    "On Hold": ["Active", "Closed"],
    "Closed": [],
}


PROJECT_TYPES = ["Fixed Price", "Time & Material", "Retainer", "Internal"]


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("client_id", "project_code", name="uq_projects_client_code"),
        {"schema": SCHEMA},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, nullable=False, index=True)
    project_code = Column(Unicode(20), nullable=False)
    project_name = Column(Unicode(200), nullable=False)
    description = Column(Unicode(2000), nullable=True)
    customer_id = Column(Integer, nullable=True)
    customer_name = Column(Unicode(200), nullable=True)
    customer_contact_name = Column(Unicode(200), nullable=True)
    customer_mobile = Column(Unicode(15), nullable=True)
    customer_email = Column(Unicode(150), nullable=True)
    customer_gstin = Column(Unicode(15), nullable=True)
    customer_pan = Column(Unicode(10), nullable=True)
    project_type = Column(Unicode(100), nullable=True)
    category = Column(Unicode(100), nullable=True)
    business_domain = Column(Unicode(100), nullable=True)
    status = Column(Unicode(30), nullable=False, server_default="Draft")
    priority = Column(Unicode(20), nullable=False, server_default="Medium")
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    budget = Column(Numeric(18, 2), nullable=True)
    project_manager_id = Column(Integer, nullable=True)
    project_manager_name = Column(Unicode(200), nullable=True)
    # Approval (app/repositories/approvals.py): who sent it, which level it waits for, and who approved it.
    submitted_by = Column(Integer, nullable=True)
    submitted_by_name = Column(Unicode(200), nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    approval_level = Column(Integer, nullable=True)
    approval_levels = Column(Integer, nullable=True)
    approved_by = Column(Integer, nullable=True)
    approved_by_name = Column(Unicode(200), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    approval_note = Column(Unicode(1000), nullable=True)
    # Baseline: the plan as approved (frozen at approval), to compare the live plan against.
    baseline_budget = Column(Numeric(18, 2), nullable=True)
    baseline_start_date = Column(Date, nullable=True)
    baseline_end_date = Column(Date, nullable=True)
    baseline_at = Column(DateTime, nullable=True)
    created_by = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    is_deleted = Column(Boolean, nullable=False, server_default="0")


class ProjectCounter(Base):
    """Per-client, per-year sequence behind PRJ-YYYY-XXXX codes."""

    __tablename__ = "project_counters"
    __table_args__ = {"schema": SCHEMA}

    client_id = Column(Integer, primary_key=True)
    year = Column(Integer, primary_key=True)
    last_no = Column(Integer, nullable=False, server_default="0")
