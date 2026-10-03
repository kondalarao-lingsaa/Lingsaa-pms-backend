from sqlalchemy import Boolean, Column, DateTime, Integer, Unicode, UniqueConstraint, func

from app.db.base import Base
from app.models.roles import SCHEMA


class UserRole(Base):
    """The PMS role of one login user in one company (Settings > Users & Roles).

    The login itself comes from Master; this row only says what the person may do in the PMS. A Client user is
    tied to one customer name and sees only that customer's projects, through the client portal."""

    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("client_id", "user_id", name="uq_user_roles_client_user"), {"schema": SCHEMA})

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, nullable=False)
    user_name = Column(Unicode(200), nullable=False)
    email = Column(Unicode(150), nullable=True)
    role = Column(Unicode(40), nullable=False)
    customer_name = Column(Unicode(200), nullable=True)
    is_active = Column(Boolean, nullable=False, server_default="1")
    # The PMS's own login (app/api/routes/auth.py): a salted hash, never the password itself.
    password_hash = Column(Unicode(200), nullable=True)
    last_login_at = Column(DateTime, nullable=True)
    created_by = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class RolePermission(Base):
    """A company's own setting for one role on one module (Settings > Roles & Permissions).

    Without a row the recommended default (app/core/roles.py ROLE_MATRIX) applies; "actions" is the full list
    for that role and module, comma-separated (empty = no access)."""

    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("client_id", "role", "module_group", name="uq_role_permissions"), {"schema": SCHEMA})

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, nullable=False, index=True)
    role = Column(Unicode(40), nullable=False)
    module_group = Column(Unicode(40), nullable=False)
    actions = Column(Unicode(100), nullable=False, server_default="")
    updated_by = Column(Integer, nullable=True)
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class ApprovalLog(Base):
    """One decision on something that needs approval (project, change request, expense, timesheet, milestone).

    Kept as history: who decided, at which level, and why. "Auto" rows record approvals the rules gave
    without a person (for example a project under the PM's budget limit)."""

    __tablename__ = "approval_log"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, nullable=False, index=True)
    project_id = Column(Integer, nullable=True, index=True)
    entity_type = Column(Unicode(30), nullable=False)
    entity_id = Column(Integer, nullable=False)
    level = Column(Integer, nullable=False, server_default="1")
    decision = Column(Unicode(20), nullable=False)  # Submitted | Approved | Rejected | Auto-approved
    decided_by = Column(Integer, nullable=True)
    decided_by_name = Column(Unicode(200), nullable=True)
    decided_role = Column(Unicode(40), nullable=True)
    remarks = Column(Unicode(1000), nullable=True)
    decided_at = Column(DateTime, nullable=False, server_default=func.now())


class ClientMessage(Base):
    """A message between the client (portal) and the project team, kept per project."""

    __tablename__ = "client_messages"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, nullable=False, index=True)
    project_id = Column(Integer, nullable=False, index=True)
    author_user_id = Column(Integer, nullable=True)
    author_name = Column(Unicode(200), nullable=False)
    from_client = Column(Boolean, nullable=False, server_default="0")
    body = Column(Unicode(2000), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
