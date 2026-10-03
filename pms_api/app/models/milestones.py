from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, Unicode, func

from app.db.base import Base
from app.models.roles import SCHEMA

# Planned -> In Progress -> Ready for Review -> Accepted, or Ready for Review -> Changes Requested -> In Progress.
MILESTONE_STATUSES = ["Planned", "In Progress", "Ready for Review", "Accepted", "Changes Requested"]
MILESTONE_TRANSITIONS = {
    "Planned": ["In Progress"],
    "In Progress": ["Ready for Review", "Planned"],
    "Ready for Review": ["Accepted", "Changes Requested"],
    "Changes Requested": ["In Progress"],
    "Accepted": [],
}


class Milestone(Base):
    """A checkpoint of a project: what must be delivered by when, and what the client pays when it is accepted."""

    __tablename__ = "milestones"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, nullable=False, index=True)
    project_id = Column(Integer, ForeignKey(f"{SCHEMA}.projects.id"), nullable=False, index=True)
    name = Column(Unicode(200), nullable=False)
    description = Column(Unicode(2000), nullable=True)
    due_date = Column(Date, nullable=True)
    amount = Column(Numeric(14, 2), nullable=True)
    status = Column(Unicode(30), nullable=False, server_default="Planned")
    feedback = Column(Unicode(1000), nullable=True)
    accepted_at = Column(DateTime, nullable=True)
    accepted_by_name = Column(Unicode(200), nullable=True)
    # Due date in the approved plan (set when the project is approved); empty for milestones added later.
    baseline_due_date = Column(Date, nullable=True)
    created_by = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    is_deleted = Column(Boolean, nullable=False, server_default="0")


class Deliverable(Base):
    """Something concrete handed over for a milestone (a document, a build, a report)."""

    __tablename__ = "deliverables"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    milestone_id = Column(Integer, ForeignKey(f"{SCHEMA}.milestones.id"), nullable=False, index=True)
    name = Column(Unicode(200), nullable=False)
    is_done = Column(Boolean, nullable=False, server_default="0")
    done_at = Column(DateTime, nullable=True)
    done_by_name = Column(Unicode(200), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    is_deleted = Column(Boolean, nullable=False, server_default="0")
