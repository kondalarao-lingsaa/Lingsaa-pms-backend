from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, Unicode, func

from app.db.base import Base
from app.models.roles import SCHEMA

# Roles a person can play inside one project (not login roles - those live in Master).
MEMBER_ROLES = [
    "Project Manager",
    "Team Lead",
    "Developer",
    "Tester / QA",
    "Designer",
    "Business Analyst",
    "DevOps",
    "Consultant",
    "Other",
]


class ProjectMember(Base):
    """A person on a project's team: what they do there, how much of their time it takes and what an hour costs.

    `user_id` is the login user when known (Master users); `member_name` is always kept so typed-in people
    work today and the list can later be backed by Master/HRMS without changing tasks or history."""

    __tablename__ = "project_members"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, nullable=False, index=True)
    project_id = Column(Integer, ForeignKey(f"{SCHEMA}.projects.id"), nullable=False, index=True)
    user_id = Column(Integer, nullable=True, index=True)
    member_name = Column(Unicode(200), nullable=False)
    email = Column(Unicode(150), nullable=True)
    role = Column(Unicode(50), nullable=False)
    allocation_pct = Column(Integer, nullable=False, server_default="0")
    hourly_rate = Column(Numeric(10, 2), nullable=True)
    # What the client pays for an hour of this person (Time & Material invoices). Empty = billed at hourly_rate.
    bill_rate = Column(Numeric(10, 2), nullable=True)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    created_by = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    is_deleted = Column(Boolean, nullable=False, server_default="0")
