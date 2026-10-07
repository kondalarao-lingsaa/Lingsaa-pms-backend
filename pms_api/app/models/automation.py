from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, Unicode, UniqueConstraint, func

from app.db.base import Base
from app.models.roles import SCHEMA

RECURRING_FREQUENCIES = ["Daily", "Weekly", "Monthly"]


class AutomationRule(Base):
    """One company's setting for one automation job (Settings > Automation). No row = the job's defaults
    (app/repositories/automation.py JOBS); a row is written the first time the scheduler sees the company.

    last_run_on is how the scheduler knows the job already ran today: it is claimed with one UPDATE, so two
    servers (or workers) never run the same job twice."""

    __tablename__ = "automation_rules"
    __table_args__ = {"schema": SCHEMA}

    client_id = Column(Integer, primary_key=True, autoincrement=False)
    job_key = Column(Unicode(40), primary_key=True)
    enabled = Column(Boolean, nullable=False, server_default="1")
    run_time = Column(Unicode(5), nullable=True)  # "09:00", local server time; empty for jobs started by an event
    weekday = Column(Integer, nullable=True)  # weekly jobs: Monday = 0
    month_day = Column(Integer, nullable=True)  # monthly jobs: 1-28
    params = Column(Unicode(1000), nullable=True)  # JSON: the job's own numbers (days before a reminder, ...)
    last_run_on = Column(Date, nullable=True)
    last_run_at = Column(DateTime, nullable=True)
    last_status = Column(Unicode(20), nullable=True)
    last_summary = Column(Unicode(1000), nullable=True)
    updated_by = Column(Integer, nullable=True)
    updated_by_name = Column(Unicode(200), nullable=True)
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class AutomationRun(Base):
    """One run of a job: when, what started it, what it did. Shown as the run history in Settings > Automation."""

    __tablename__ = "automation_runs"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, nullable=False, index=True)
    job_key = Column(Unicode(40), nullable=False)
    trigger = Column(Unicode(20), nullable=False)  # Schedule | Manual | Event
    status = Column(Unicode(20), nullable=False)  # Success | Nothing to do | Failed
    items = Column(Integer, nullable=False, server_default="0")
    summary = Column(Unicode(2000), nullable=True)
    started_by_name = Column(Unicode(200), nullable=True)
    started_at = Column(DateTime, nullable=False, server_default=func.now())
    finished_at = Column(DateTime, nullable=True)


class AutomationSent(Base):
    """"Already done" marks, so a one-time alert (budget crossed 80%, task escalated) is not repeated every day."""

    __tablename__ = "automation_sent"
    __table_args__ = (UniqueConstraint("client_id", "job_key", "ref_key", name="uq_automation_sent"), {"schema": SCHEMA})

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, nullable=False)
    job_key = Column(Unicode(40), nullable=False)
    ref_key = Column(Unicode(120), nullable=False)
    sent_at = Column(DateTime, nullable=False, server_default=func.now())


class RecurringTask(Base):
    """A task that is created again and again (weekly client call, monthly GST filing).

    The daily "recurring_tasks" job creates the task on each due day of an Active project and moves next_run_on
    to the following occurrence."""

    __tablename__ = "recurring_tasks"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, nullable=False, index=True)
    project_id = Column(Integer, ForeignKey(f"{SCHEMA}.projects.id"), nullable=False, index=True)
    title = Column(Unicode(250), nullable=False)
    description = Column(Unicode(4000), nullable=True)
    priority = Column(Unicode(20), nullable=False, server_default="Medium")
    assignee_id = Column(Integer, nullable=True)
    assignee_name = Column(Unicode(200), nullable=True)
    estimated_hours = Column(Numeric(8, 2), nullable=True)
    frequency = Column(Unicode(20), nullable=False)  # Daily | Weekly | Monthly
    every = Column(Integer, nullable=False, server_default="1")  # every N days / weeks / months
    weekday = Column(Integer, nullable=True)  # Weekly: Monday = 0
    month_day = Column(Integer, nullable=True)  # Monthly: 1-31 (short months use their last day)
    working_days_only = Column(Boolean, nullable=False, server_default="1")  # Daily: skip weekends and holidays
    due_in_days = Column(Integer, nullable=False, server_default="0")  # due date = day created + this many days
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    next_run_on = Column(Date, nullable=True)  # empty = finished
    is_active = Column(Boolean, nullable=False, server_default="1")
    created_count = Column(Integer, nullable=False, server_default="0")
    last_task_id = Column(Integer, nullable=True)
    last_created_on = Column(Date, nullable=True)
    last_note = Column(Unicode(500), nullable=True)  # why the last occurrence was skipped, if it was
    created_by = Column(Integer, nullable=True)
    created_by_name = Column(Unicode(200), nullable=True)
    updated_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    is_deleted = Column(Boolean, nullable=False, server_default="0")
