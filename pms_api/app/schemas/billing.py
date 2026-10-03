from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.billing import INVOICE_TYPES
from app.schemas.rules import capitalize_first, utc_iso


class InvoiceCreateIn(BaseModel):
    project_id: int
    invoice_type: str
    milestone_id: Optional[int] = None
    period_from: Optional[date] = None
    period_to: Optional[date] = None
    tax_pct: Decimal = Field(default=Decimal("18"), ge=0, le=28, max_digits=5, decimal_places=2)
    payment_terms_days: int = Field(default=30, ge=0, le=180)
    notes: Optional[str] = Field(default=None, max_length=1000)
    include_expenses: bool = True  # Time & Material: add approved billable expenses of the period

    @field_validator("invoice_type")
    @classmethod
    def _type(cls, v):
        if v not in INVOICE_TYPES:
            raise ValueError("Please Select Invoice Type")
        return v

    @field_validator("notes")
    @classmethod
    def _notes(cls, v):
        return capitalize_first(v)

    @model_validator(mode="after")
    def _by_type(self):
        if self.invoice_type == "Milestone" and not self.milestone_id:
            raise ValueError("Please Select Milestone")
        if self.invoice_type == "Time & Material":
            if not self.period_from or not self.period_to:
                raise ValueError("Please Select the billing period (From and To dates)")
            if self.period_to < self.period_from:
                raise ValueError("Period To cannot be before Period From")
            if self.period_to > date.today():
                raise ValueError("Period To cannot be in the future")
        return self


class InvoiceStatusIn(BaseModel):
    action: str  # issue | pay | cancel
    paid_date: Optional[date] = None

    @field_validator("action")
    @classmethod
    def _action(cls, v):
        if v not in ("issue", "pay", "cancel"):
            raise ValueError("Unknown invoice action")
        return v


def _num(v):
    return float(v) if v is not None else None


def invoice_out(inv, *, lines=None, project=None, milestone_name=None) -> dict:
    return {
        "id": inv.id,
        "invoice_no": inv.invoice_no,
        "invoice_type": inv.invoice_type,
        "project_id": inv.project_id,
        "project_code": project.project_code if project else None,
        "project_name": project.project_name if project else None,
        "milestone_id": inv.milestone_id,
        "milestone_name": milestone_name,
        "period_from": inv.period_from.isoformat() if inv.period_from else None,
        "period_to": inv.period_to.isoformat() if inv.period_to else None,
        "customer_name": inv.customer_name,
        "customer_gstin": inv.customer_gstin,
        "subtotal": _num(inv.subtotal),
        "tax_pct": _num(inv.tax_pct),
        "tax_amount": _num(inv.tax_amount),
        "total": _num(inv.total),
        "status": inv.status,
        "issue_date": inv.issue_date.isoformat() if inv.issue_date else None,
        "due_date": inv.due_date.isoformat() if inv.due_date else None,
        "paid_date": inv.paid_date.isoformat() if inv.paid_date else None,
        "is_overdue": bool(inv.status == "Issued" and inv.due_date and inv.due_date < date.today()),
        "notes": inv.notes,
        "created_by_name": inv.created_by_name,
        "created_at": utc_iso(inv.created_at),
        "lines": [
            {"id": l.id, "description": l.description, "quantity": _num(l.quantity), "unit": l.unit, "rate": _num(l.rate), "amount": _num(l.amount)}
            for l in (lines or [])
        ],
    }
