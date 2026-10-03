from sqlalchemy import Column, Date, DateTime, Integer, Numeric, Unicode, UniqueConstraint, func

from app.db.base import Base
from app.models.roles import SCHEMA

DEFAULT_HOURS_PER_DAY = 8
DEFAULT_WORKING_DAYS = "0,1,2,3,4"  # Monday = 0 ... Sunday = 6


class CompanySettings(Base):
    """One row per company: its working calendar. Capacity, Utilization, Sprint capacity and Reports read it."""

    __tablename__ = "company_settings"
    __table_args__ = {"schema": SCHEMA}

    client_id = Column(Integer, primary_key=True, autoincrement=False)
    hours_per_day = Column(Numeric(4, 2), nullable=False, server_default=str(DEFAULT_HOURS_PER_DAY))
    working_days = Column(Unicode(20), nullable=False, server_default=DEFAULT_WORKING_DAYS)
    # Industry preset (app/core/industries.py) and the team roles this company uses, "|"-separated.
    industry = Column(Unicode(60), nullable=True)
    member_roles = Column(Unicode(1000), nullable=True)
    # Approval limits (Settings > Approval Rules). Empty = the defaults in app/repositories/approvals.py.
    pm_approval_limit = Column(Numeric(18, 2), nullable=True)
    high_approval_limit = Column(Numeric(18, 2), nullable=True)
    expense_approval_limit = Column(Numeric(18, 2), nullable=True)
    updated_by = Column(Integer, nullable=True)
    updated_by_name = Column(Unicode(200), nullable=True)
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class Holiday(Base):
    """A day off for the whole company; it does not count as a working day anywhere."""

    __tablename__ = "holidays"
    __table_args__ = (UniqueConstraint("client_id", "holiday_date", name="uq_holidays_client_date"), {"schema": SCHEMA})

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, nullable=False, index=True)
    holiday_date = Column(Date, nullable=False)
    name = Column(Unicode(100), nullable=False)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
