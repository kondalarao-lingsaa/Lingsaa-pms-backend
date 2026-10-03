from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, Unicode, func

from app.db.base import Base
from app.models.roles import SCHEMA

# Planned -> Active -> Completed. Only one Active sprint per project at a time.
SPRINT_STATUSES = ["Planned", "Active", "Completed"]
MAX_SPRINT_DAYS = 28


class Sprint(Base):
    """A fixed time-box (1-4 weeks) the team commits a set of tasks to.

    committed_hours / completed_hours are frozen when the sprint is completed, so velocity history
    does not change when tasks are edited later."""

    __tablename__ = "sprints"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, nullable=False, index=True)
    project_id = Column(Integer, ForeignKey(f"{SCHEMA}.projects.id"), nullable=False, index=True)
    sprint_key = Column(Unicode(40), nullable=False)
    name = Column(Unicode(120), nullable=False)
    goal = Column(Unicode(1000), nullable=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    status = Column(Unicode(20), nullable=False, server_default="Planned")
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    committed_hours = Column(Numeric(10, 2), nullable=True)
    completed_hours = Column(Numeric(10, 2), nullable=True)
    committed_tasks = Column(Integer, nullable=True)
    completed_tasks = Column(Integer, nullable=True)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    is_deleted = Column(Boolean, nullable=False, server_default="0")
