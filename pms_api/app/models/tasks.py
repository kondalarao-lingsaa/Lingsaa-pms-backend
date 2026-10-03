from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, Numeric, Unicode, UniqueConstraint, func

from app.db.base import Base
from app.models.roles import SCHEMA

TASK_STATUSES = ["To Do", "In Progress", "Testing", "Done"]
TASK_PRIORITIES = ["Low", "Medium", "High", "Critical"]
TASK_TYPES = ["Epic", "Story", "Task", "Subtask", "Bug"]


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("client_id", "task_key", name="uq_tasks_client_key"),
        {"schema": SCHEMA},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, nullable=False, index=True)
    project_id = Column(Integer, ForeignKey(f"{SCHEMA}.projects.id"), nullable=False, index=True)
    task_key = Column(Unicode(30), nullable=False)
    task_type = Column(Unicode(20), nullable=False, server_default="Task")
    title = Column(Unicode(300), nullable=False)
    description = Column(Unicode(4000), nullable=True)
    parent_task_id = Column(Integer, ForeignKey(f"{SCHEMA}.tasks.id"), nullable=True, index=True)
    epic_id = Column(Integer, ForeignKey(f"{SCHEMA}.tasks.id"), nullable=True, index=True)
    milestone_id = Column(Integer, ForeignKey(f"{SCHEMA}.milestones.id"), nullable=True, index=True)
    sprint_id = Column(Integer, ForeignKey(f"{SCHEMA}.sprints.id"), nullable=True, index=True)
    assignee_id = Column(Integer, nullable=True)
    assignee_name = Column(Unicode(200), nullable=True)
    reporter_id = Column(Integer, nullable=True)
    reporter_name = Column(Unicode(200), nullable=True)
    priority = Column(Unicode(20), nullable=False, server_default="Medium")
    status = Column(Unicode(30), nullable=False, server_default="To Do")
    start_date = Column(Date, nullable=True)
    due_date = Column(Date, nullable=True)
    estimated_hours = Column(Numeric(8, 2), nullable=True)
    actual_hours = Column(Numeric(8, 2), nullable=True)
    board_order = Column(Float, nullable=False, server_default="0")
    created_by = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    is_deleted = Column(Boolean, nullable=False, server_default="0")


class TaskLabel(Base):
    __tablename__ = "task_labels"
    __table_args__ = (UniqueConstraint("task_id", "label", name="uq_task_label"), {"schema": SCHEMA})

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey(f"{SCHEMA}.tasks.id"), nullable=False, index=True)
    label = Column(Unicode(50), nullable=False)


class TaskWatcher(Base):
    __tablename__ = "task_watchers"
    __table_args__ = (UniqueConstraint("task_id", "user_id", name="uq_task_watcher"), {"schema": SCHEMA})

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey(f"{SCHEMA}.tasks.id"), nullable=False, index=True)
    user_id = Column(Integer, nullable=False)
    user_name = Column(Unicode(200), nullable=True)


class TaskDependency(Base):
    __tablename__ = "task_dependencies"
    __table_args__ = (UniqueConstraint("task_id", "depends_on_id", name="uq_task_dependency"), {"schema": SCHEMA})

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey(f"{SCHEMA}.tasks.id"), nullable=False, index=True)
    depends_on_id = Column(Integer, ForeignKey(f"{SCHEMA}.tasks.id"), nullable=False)
    dependency_type = Column(Unicode(20), nullable=False, server_default="blocks")


class TaskComment(Base):
    __tablename__ = "task_comments"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey(f"{SCHEMA}.tasks.id"), nullable=False, index=True)
    body = Column(Unicode(4000), nullable=False)
    author_id = Column(Integer, nullable=True)
    author_name = Column(Unicode(200), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    is_deleted = Column(Boolean, nullable=False, server_default="0")


class TaskAttachment(Base):
    __tablename__ = "task_attachments"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey(f"{SCHEMA}.tasks.id"), nullable=False, index=True)
    file_name = Column(Unicode(500), nullable=False)
    file_url = Column(Unicode(2000), nullable=False)
    uploaded_by = Column(Integer, nullable=True)
    uploaded_at = Column(DateTime, nullable=False, server_default=func.now())


class TaskActivity(Base):
    """Who did what to a task and when: the task's history tab."""

    __tablename__ = "task_activity"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey(f"{SCHEMA}.tasks.id"), nullable=False, index=True)
    action = Column(Unicode(50), nullable=False)
    detail = Column(Unicode(1000), nullable=True)
    actor_id = Column(Integer, nullable=True)
    actor_name = Column(Unicode(200), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class TaskCounter(Base):
    """Per-project sequence behind task keys like PRJ-2026-0001-T12."""

    __tablename__ = "task_counters"
    __table_args__ = {"schema": SCHEMA}

    project_id = Column(Integer, primary_key=True, autoincrement=False)
    last_no = Column(Integer, nullable=False, server_default="0")
