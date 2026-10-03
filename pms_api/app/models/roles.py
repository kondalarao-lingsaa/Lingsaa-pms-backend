from sqlalchemy import Column, DateTime, ForeignKey, Integer, Unicode, UniqueConstraint, func

from app.db.base import Base

SCHEMA = "projectmanagement"


class DefaultRole(Base):
    """Recommended PMS role templates (same for every client). Read-only reference data."""

    __tablename__ = "default_roles"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    role_key = Column(Unicode(50), nullable=False, unique=True)
    title = Column(Unicode(100), nullable=False)
    responsibility = Column(Unicode(255), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class DefaultRolePermission(Base):
    """Default action a role template has on a module group (e.g. projectManager / tasks / edit)."""

    __tablename__ = "default_role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "module_group", "action", name="uq_default_role_permission"),
        {"schema": SCHEMA},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    role_id = Column(Integer, ForeignKey(f"{SCHEMA}.default_roles.id"), nullable=False)
    module_group = Column(Unicode(50), nullable=False)
    action = Column(Unicode(20), nullable=False)
