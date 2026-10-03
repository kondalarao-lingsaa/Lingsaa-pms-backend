from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, Unicode, func

from app.db.base import Base
from app.models.roles import SCHEMA

INVOICE_TYPES = ["Milestone", "Time & Material"]
# Draft -> Issued -> Paid; Draft or Issued -> Cancelled (frees the milestone / hours to be billed again).
INVOICE_STATUSES = ["Draft", "Issued", "Paid", "Cancelled"]


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, nullable=False, index=True)
    project_id = Column(Integer, ForeignKey(f"{SCHEMA}.projects.id"), nullable=False, index=True)
    invoice_no = Column(Unicode(30), nullable=False)
    invoice_type = Column(Unicode(30), nullable=False)
    milestone_id = Column(Integer, ForeignKey(f"{SCHEMA}.milestones.id"), nullable=True, index=True)
    period_from = Column(Date, nullable=True)
    period_to = Column(Date, nullable=True)
    customer_name = Column(Unicode(200), nullable=True)
    customer_gstin = Column(Unicode(15), nullable=True)
    subtotal = Column(Numeric(14, 2), nullable=False, server_default="0")
    tax_pct = Column(Numeric(5, 2), nullable=False, server_default="18")
    tax_amount = Column(Numeric(14, 2), nullable=False, server_default="0")
    total = Column(Numeric(14, 2), nullable=False, server_default="0")
    status = Column(Unicode(20), nullable=False, server_default="Draft")
    issue_date = Column(Date, nullable=True)
    due_date = Column(Date, nullable=True)
    paid_date = Column(Date, nullable=True)
    notes = Column(Unicode(1000), nullable=True)
    created_by = Column(Integer, nullable=True)
    created_by_name = Column(Unicode(200), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    is_deleted = Column(Boolean, nullable=False, server_default="0")


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_id = Column(Integer, ForeignKey(f"{SCHEMA}.invoices.id"), nullable=False, index=True)
    description = Column(Unicode(500), nullable=False)
    quantity = Column(Numeric(10, 2), nullable=False)
    unit = Column(Unicode(20), nullable=True)
    rate = Column(Numeric(12, 2), nullable=False)
    amount = Column(Numeric(14, 2), nullable=False)


class InvoiceCounter(Base):
    """Per-company sequence behind invoice numbers like INV-2026-0001."""

    __tablename__ = "invoice_counters"
    __table_args__ = {"schema": SCHEMA}

    client_id = Column(Integer, primary_key=True, autoincrement=False)
    year = Column(Integer, primary_key=True, autoincrement=False)
    last_no = Column(Integer, nullable=False, server_default="0")
