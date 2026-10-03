from sqlalchemy import Boolean, Column, DateTime, Integer, Unicode, func

from app.db.base import Base
from app.models.roles import SCHEMA

# What happened, as shown by the bell icon and the Communication screens.
NOTIFICATION_KINDS = ["mention", "comment", "assigned", "status", "timesheet", "expense", "approval", "message", "reminder"]


class Notification(Base):
    """One message for one person: "Anita mentioned you on PRJ-1-T4", "PRJ-1-T4 was assigned to you", ...

    The recipient is the login user when known; team members typed in by name (no login yet) are matched by
    name, so their notifications appear once they sign in with a matching name."""

    __tablename__ = "notifications"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, nullable=False, index=True)
    recipient_user_id = Column(Integer, nullable=True, index=True)
    recipient_name = Column(Unicode(200), nullable=True)
    kind = Column(Unicode(30), nullable=False)
    title = Column(Unicode(300), nullable=False)
    body = Column(Unicode(1000), nullable=True)
    link = Column(Unicode(500), nullable=True)  # screen path inside the PMS, e.g. "tasks/taskDetails/?id=12"
    project_id = Column(Integer, nullable=True, index=True)
    task_id = Column(Integer, nullable=True, index=True)
    comment_id = Column(Integer, nullable=True)
    actor_id = Column(Integer, nullable=True)
    actor_name = Column(Unicode(200), nullable=True)
    is_read = Column(Boolean, nullable=False, server_default="0")
    created_at = Column(DateTime, nullable=False, server_default=func.now())
