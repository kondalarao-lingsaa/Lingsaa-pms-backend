from datetime import date
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.models.expenses import EXPENSE_CATEGORIES
from app.schemas.rules import capitalize_first, capitalize_words, utc_iso


class ExpenseIn(BaseModel):
    project_id: int
    category: str
    description: str = Field(min_length=1, max_length=500)
    vendor: Optional[str] = Field(default=None, max_length=200)
    expense_date: date
    amount: Decimal = Field(gt=0, le=Decimal("999999999"), max_digits=14, decimal_places=2)
    billable: bool = False
    milestone_id: Optional[int] = None
    task_id: Optional[int] = None
    submit: bool = False  # save and send for approval in one step

    @field_validator("category")
    @classmethod
    def _category(cls, v):
        if v not in EXPENSE_CATEGORIES:
            raise ValueError(f"Category must be one of: {', '.join(EXPENSE_CATEGORIES)}")
        return v

    @field_validator("description")
    @classmethod
    def _description(cls, v):
        v = capitalize_first(v)
        if not v or len(v) < 3:
            raise ValueError("Description must be at least 3 characters")
        return v

    @field_validator("vendor")
    @classmethod
    def _vendor(cls, v):
        return capitalize_words(v)

    @field_validator("expense_date")
    @classmethod
    def _not_future(cls, v):
        if v > date.today():
            raise ValueError("Expense date cannot be in the future")
        return v


class ExpenseIdsIn(BaseModel):
    ids: List[int] = Field(min_length=1, max_length=200)


class ExpenseRejectIn(ExpenseIdsIn):
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def _reason(cls, v):
        v = capitalize_first(v)
        if not v or len(v) < 5:
            raise ValueError("Please give a reason of at least 5 characters, so the person knows what to fix")
        return v


def expense_out(e, project=None, milestone_name=None, task_key=None, invoice_no=None, receipt=None) -> dict:
    return {
        "id": e.id, "expense_key": e.expense_key, "project_id": e.project_id,
        "project_code": project.project_code if project else None, "project_name": project.project_name if project else None,
        "milestone_id": e.milestone_id, "milestone_name": milestone_name, "task_id": e.task_id, "task_key": task_key,
        "category": e.category, "description": e.description, "vendor": e.vendor, "expense_date": e.expense_date.isoformat(),
        "amount": float(e.amount), "billable": bool(e.billable), "status": e.status,
        "spent_by": e.spent_by, "spent_by_name": e.spent_by_name, "submitted_at": utc_iso(e.submitted_at),
        "reviewed_by_name": e.reviewed_by_name, "reviewed_at": utc_iso(e.reviewed_at), "reject_reason": e.reject_reason,
        "created_at": utc_iso(e.created_at), "invoice_id": e.invoice_id, "invoice_no": invoice_no,
        "receipt_document_id": e.receipt_document_id, "receipt_file_name": receipt,
    }
