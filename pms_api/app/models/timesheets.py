from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, Unicode, func

from app.db.base import Base
from app.models.roles import SCHEMA

# Draft -> Submitted -> Approved, or Submitted -> Rejected -> (edit) -> Submitted again.
ENTRY_STATUSES = ["Draft", "Submitted", "Approved", "Rejected"]
EDITABLE_STATUSES = ("Draft", "Rejected")


class TimeEntry(Base):
    """Hours one team member spent on one task on one day.

    The member's hourly rate is copied onto the entry when it is approved, so later rate changes do not
    rewrite what past work cost."""

    __tablename__ = "time_entries"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, nullable=False, index=True)
    project_id = Column(Integer, ForeignKey(f"{SCHEMA}.projects.id"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey(f"{SCHEMA}.tasks.id"), nullable=False, index=True)
    member_id = Column(Integer, ForeignKey(f"{SCHEMA}.project_members.id"), nullable=False, index=True)
    user_id = Column(Integer, nullable=True, index=True)
    member_name = Column(Unicode(200), nullable=False)
    work_date = Column(Date, nullable=False, index=True)
    hours = Column(Numeric(5, 2), nullable=False)
    note = Column(Unicode(500), nullable=True)
    status = Column(Unicode(20), nullable=False, server_default="Draft")
    hourly_rate = Column(Numeric(10, 2), nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    reviewed_by = Column(Integer, nullable=True)
    reviewed_by_name = Column(Unicode(200), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    reject_reason = Column(Unicode(500), nullable=True)
    invoice_id = Column(Integer, nullable=True, index=True)  # set once the hours are billed (Time & Material)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    is_deleted = Column(Boolean, nullable=False, server_default="0")
