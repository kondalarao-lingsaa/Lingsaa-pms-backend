from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, Unicode, func

from app.db.base import Base
from app.models.roles import SCHEMA

EXPENSE_CATEGORIES = ["Travel", "Food & Stay", "Software & Licences", "Hardware", "Hosting & Cloud", "Subcontractor", "Training", "Other"]
# Draft -> Submitted -> Approved, or Submitted -> Rejected -> (edit) -> Submitted again.
EXPENSE_STATUSES = ["Draft", "Submitted", "Approved", "Rejected"]
EDITABLE_EXPENSE_STATUSES = ("Draft", "Rejected")
# Money can only be spent on projects that are allowed to run.
SPENDING_PROJECT_STATUSES = ("Approved", "Active", "On Hold")


class Expense(Base):
    """Money spent for a project other than people's time: travel, licences, hardware, subcontractors...

    Approved expenses are part of the project's actual cost next to the cost of approved hours."""

    __tablename__ = "expenses"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, nullable=False, index=True)
    project_id = Column(Integer, ForeignKey(f"{SCHEMA}.projects.id"), nullable=False, index=True)
    expense_key = Column(Unicode(30), nullable=False)
    milestone_id = Column(Integer, ForeignKey(f"{SCHEMA}.milestones.id"), nullable=True)
    task_id = Column(Integer, ForeignKey(f"{SCHEMA}.tasks.id"), nullable=True)
    category = Column(Unicode(50), nullable=False)
    description = Column(Unicode(500), nullable=False)
    vendor = Column(Unicode(200), nullable=True)
    expense_date = Column(Date, nullable=False, index=True)
    amount = Column(Numeric(14, 2), nullable=False)
    billable = Column(Boolean, nullable=False, server_default="0")  # to be charged on to the client
    status = Column(Unicode(20), nullable=False, server_default="Draft")
    spent_by = Column(Integer, nullable=True)
    spent_by_name = Column(Unicode(200), nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    reviewed_by = Column(Integer, nullable=True)
    reviewed_by_name = Column(Unicode(200), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    reject_reason = Column(Unicode(500), nullable=True)
    invoice_id = Column(Integer, nullable=True, index=True)  # set once a billable expense is charged on an invoice
    receipt_document_id = Column(Integer, nullable=True)  # the bill, stored in Documents (category Receipt)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    is_deleted = Column(Boolean, nullable=False, server_default="0")
