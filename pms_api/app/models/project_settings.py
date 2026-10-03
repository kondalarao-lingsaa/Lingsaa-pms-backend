from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, Unicode, func

from app.db.base import Base
from app.models.roles import SCHEMA

DEFAULTS = {
    "default_task_priority": "Medium",
    "default_estimate_hours": None,
    "task_labels": [],
    "timesheet_lock_days": None,
    "budget_alert_pct": 80,
    "receipt_required_above": None,
    "default_tax_pct": 18,
    "default_payment_terms": 30,
}


class ProjectSettings(Base):
    """Rules for one project. No row = the defaults above."""

    __tablename__ = "project_settings"
    __table_args__ = {"schema": SCHEMA}

    project_id = Column(Integer, ForeignKey(f"{SCHEMA}.projects.id"), primary_key=True, autoincrement=False)
    client_id = Column(Integer, nullable=False, index=True)
    default_task_priority = Column(Unicode(20), nullable=False, server_default="Medium")
    default_estimate_hours = Column(Numeric(8, 2), nullable=True)
    task_labels = Column(Unicode(1000), nullable=True)  # comma separated suggestions
    timesheet_lock_days = Column(Integer, nullable=True)  # hours older than this many days cannot be logged
    budget_alert_pct = Column(Integer, nullable=False, server_default="80")
    receipt_required_above = Column(Numeric(14, 2), nullable=True)
    default_tax_pct = Column(Numeric(5, 2), nullable=False, server_default="18")
    default_payment_terms = Column(Integer, nullable=False, server_default="30")
    updated_by = Column(Integer, nullable=True)
    updated_by_name = Column(Unicode(200), nullable=True)
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
