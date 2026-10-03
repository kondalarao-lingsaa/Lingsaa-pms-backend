from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, Unicode, func

from app.db.base import Base
from app.models.roles import SCHEMA


class ProjectTemplate(Base):
    """A reusable project plan: milestones and tasks with dates written as "day N from the start"."""

    __tablename__ = "project_templates"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, nullable=False, index=True)
    name = Column(Unicode(120), nullable=False)
    description = Column(Unicode(1000), nullable=True)
    project_type = Column(Unicode(100), nullable=True)
    duration_days = Column(Integer, nullable=False)
    source_project_code = Column(Unicode(30), nullable=True)  # when saved from a project
    times_used = Column(Integer, nullable=False, server_default="0")
    created_by = Column(Integer, nullable=True)
    created_by_name = Column(Unicode(200), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    is_deleted = Column(Boolean, nullable=False, server_default="0")


class TemplateMilestone(Base):
    __tablename__ = "template_milestones"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    template_id = Column(Integer, ForeignKey(f"{SCHEMA}.project_templates.id"), nullable=False, index=True)
    sort_order = Column(Integer, nullable=False, server_default="0")
    name = Column(Unicode(200), nullable=False)
    description = Column(Unicode(2000), nullable=True)
    due_offset = Column(Integer, nullable=True)  # days after the project start
    amount = Column(Numeric(14, 2), nullable=True)


class TemplateTask(Base):
    __tablename__ = "template_tasks"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    template_id = Column(Integer, ForeignKey(f"{SCHEMA}.project_templates.id"), nullable=False, index=True)
    sort_order = Column(Integer, nullable=False, server_default="0")
    title = Column(Unicode(300), nullable=False)
    description = Column(Unicode(4000), nullable=True)
    task_type = Column(Unicode(20), nullable=False, server_default="Task")
    priority = Column(Unicode(20), nullable=False, server_default="Medium")
    estimated_hours = Column(Numeric(8, 2), nullable=True)
    start_offset = Column(Integer, nullable=True)  # days after the project start
    duration_days = Column(Integer, nullable=True)
    milestone_index = Column(Integer, nullable=True)  # position in the template's milestone list
    parent_index = Column(Integer, nullable=True)  # position of the parent task (subtasks)
