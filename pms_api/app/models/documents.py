from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, Unicode, func

from app.db.base import Base
from app.models.roles import SCHEMA

DOCUMENT_CATEGORIES = ["Contract", "Requirement", "Design", "Technical", "Report", "Deliverable", "Invoice", "Meeting Notes", "Receipt", "Other"]


class Document(Base):
    """A file stored for a project, optionally attached to a task, a milestone or one of its deliverables.

    Uploading a new version adds a row with the same `group_key` and version + 1; only the newest has
    is_latest = True, so the history of a document is kept."""

    __tablename__ = "documents"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, nullable=False, index=True)
    project_id = Column(Integer, ForeignKey(f"{SCHEMA}.projects.id"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey(f"{SCHEMA}.tasks.id"), nullable=True, index=True)
    milestone_id = Column(Integer, ForeignKey(f"{SCHEMA}.milestones.id"), nullable=True, index=True)
    deliverable_id = Column(Integer, ForeignKey(f"{SCHEMA}.deliverables.id"), nullable=True, index=True)
    group_key = Column(Unicode(36), nullable=False, index=True)
    version = Column(Integer, nullable=False, server_default="1")
    is_latest = Column(Boolean, nullable=False, server_default="1")
    # Shared with the client: shown (latest version only) in the client portal.
    client_visible = Column(Boolean, nullable=True)
    title = Column(Unicode(200), nullable=False)
    category = Column(Unicode(30), nullable=False)
    notes = Column(Unicode(1000), nullable=True)
    file_name = Column(Unicode(255), nullable=False)
    extension = Column(Unicode(10), nullable=False)
    content_type = Column(Unicode(100), nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    stored_path = Column(Unicode(500), nullable=False)
    uploaded_by = Column(Integer, nullable=True)
    uploaded_by_name = Column(Unicode(200), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    is_deleted = Column(Boolean, nullable=False, server_default="0")
