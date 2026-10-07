from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.rules import EMAIL_REGEX, MOBILE_REGEX, capitalize_first, clean, gstin, pan, person_name, title_text, utc_iso
from app.models.projects import PROJECT_PRIORITIES, PROJECT_STATUSES, PROJECT_TRANSITIONS, PROJECT_TYPES


class ProjectIn(BaseModel):
    project_name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    customer_id: Optional[int] = None
    customer_name: Optional[str] = Field(default=None, max_length=200)
    customer_contact_name: Optional[str] = Field(default=None, max_length=200)
    customer_mobile: Optional[str] = Field(default=None, max_length=15)
    customer_email: Optional[str] = Field(default=None, max_length=150)
    customer_gstin: Optional[str] = Field(default=None, max_length=20)
    customer_pan: Optional[str] = Field(default=None, max_length=12)
    project_type: Optional[str] = Field(default=None, max_length=100)
    category: Optional[str] = Field(default=None, max_length=100)
    business_domain: Optional[str] = Field(default=None, max_length=100)
    priority: str = "Medium"
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    budget: Optional[Decimal] = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    project_manager_id: Optional[int] = None
    project_manager_name: Optional[str] = Field(default=None, max_length=200)

    @field_validator("project_name")
    @classmethod
    def _name(cls, v):
        return title_text(v, "Project name", required=True)

    @field_validator("customer_name")
    @classmethod
    def _client(cls, v):
        return title_text(v, "Client name", min_len=2)

    @field_validator("customer_contact_name", "project_manager_name")
    @classmethod
    def _person(cls, v):
        return person_name(v)

    @field_validator("customer_mobile")
    @classmethod
    def _mobile(cls, v):
        v = clean(v)
        if v and not MOBILE_REGEX.match(v):
            raise ValueError("Enter a valid 10-digit mobile number starting with 6-9")
        return v

    @field_validator("customer_email")
    @classmethod
    def _email(cls, v):
        v = clean(v)
        if v and not EMAIL_REGEX.match(v):
            raise ValueError("Enter a valid email address (e.g. name@example.com)")
        return v.lower() if v else v

    @field_validator("customer_gstin")
    @classmethod
    def _gstin(cls, v):
        return gstin(v)

    @field_validator("customer_pan")
    @classmethod
    def _pan(cls, v):
        return pan(v)

    @field_validator("description")
    @classmethod
    def _description(cls, v):
        return capitalize_first(v)

    @field_validator("project_type")
    @classmethod
    def _known_type(cls, v):
        if v and v.strip() not in PROJECT_TYPES:
            raise ValueError("Please Select Project Type")
        return v.strip() if v else v

    @field_validator("project_type", "category", "business_domain")
    @classmethod
    def _lookup(cls, v):
        return clean(v)

    @field_validator("priority")
    @classmethod
    def _priority(cls, v):
        if v not in PROJECT_PRIORITIES:
            raise ValueError(f"Priority must be one of: {', '.join(PROJECT_PRIORITIES)}")
        return v

    @model_validator(mode="after")
    def _cross_field(self):
        # Required on every save. Client, contact person and mobile are optional only for Internal projects.
        if not self.project_type:
            raise ValueError("Please Select Project Type")
        if self.project_type != "Internal":
            if not self.customer_name:
                raise ValueError("Please Enter Client Name (only Internal projects can skip it)")
            if not self.customer_contact_name:
                raise ValueError("Please Enter Contact Person Name")
            if not self.customer_mobile:
                raise ValueError("Please Enter Mobile Number")
        if not self.start_date:
            raise ValueError("Please Select Start Date")
        if not self.project_manager_name:
            raise ValueError("Please Enter Project Manager")
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("End date cannot be before start date")
        # A GSTIN contains the PAN (characters 3 to 12), so the two must agree; a missing PAN is taken from it.
        if self.customer_gstin:
            if self.customer_pan and self.customer_pan != self.customer_gstin[2:12]:
                raise ValueError("PAN does not match the GSTIN (characters 3 to 12 of the GSTIN are the PAN)")
            self.customer_pan = self.customer_pan or self.customer_gstin[2:12]
        return self


# Filled in before a project can be sent for approval (Draft -> Pending Approval).
APPROVAL_REQUIRED = {"end_date": "End Date", "budget": "Budget"}


def missing_for_approval(project) -> list[str]:
    return [label for field, label in APPROVAL_REQUIRED.items() if getattr(project, field) in (None, "")]


class ReopenIn(BaseModel):
    """Reopening a Closed project (Admin or Director) always says why; it is kept in the approval history."""
    reason: str = Field(max_length=1000)

    @field_validator("reason")
    @classmethod
    def _reason(cls, v):
        v = (v or "").strip()
        if len(v) < 10:
            raise ValueError("Please Enter the Reason for reopening (at least 10 characters)")
        return capitalize_first(v)


class StatusChange(BaseModel):
    status: str
    # Approve: optional note. Send back to Draft by an approver: the reason (required there).
    remarks: Optional[str] = Field(None, max_length=1000)

    @field_validator("status")
    @classmethod
    def _known(cls, v):
        if v not in PROJECT_STATUSES:
            raise ValueError(f"Status must be one of: {', '.join(PROJECT_STATUSES)}")
        return v


def project_out(p) -> dict:
    return {
        "id": p.id,
        "project_code": p.project_code,
        "project_name": p.project_name,
        "description": p.description,
        "customer_id": p.customer_id,
        "customer_name": p.customer_name,
        "customer_contact_name": p.customer_contact_name,
        "customer_mobile": p.customer_mobile,
        "customer_email": p.customer_email,
        "customer_gstin": p.customer_gstin,
        "customer_pan": p.customer_pan,
        "project_type": p.project_type,
        "category": p.category,
        "business_domain": p.business_domain,
        "status": p.status,
        "next_statuses": PROJECT_TRANSITIONS.get(p.status, []),
        "priority": p.priority,
        "start_date": p.start_date.isoformat() if p.start_date else None,
        "end_date": p.end_date.isoformat() if p.end_date else None,
        "budget": float(p.budget) if p.budget is not None else None,
        "project_manager_id": p.project_manager_id,
        "project_manager_name": p.project_manager_name,
        # Who runs a project without a manager login (access.runs_project): its creator.
        "created_by": p.created_by,
        "submitted_by_name": p.submitted_by_name,
        "submitted_at": utc_iso(p.submitted_at),
        "approval_level": p.approval_level,
        "approval_levels": p.approval_levels,
        "approved_by_name": p.approved_by_name,
        "approved_at": utc_iso(p.approved_at),
        "approval_note": p.approval_note,
        "baseline": {
            "budget": float(p.baseline_budget) if p.baseline_budget is not None else None,
            "start_date": p.baseline_start_date.isoformat() if p.baseline_start_date else None,
            "end_date": p.baseline_end_date.isoformat() if p.baseline_end_date else None,
            "frozen_at": utc_iso(p.baseline_at),
        } if p.baseline_at else None,
        "created_at": utc_iso(p.created_at),
        "updated_at": utc_iso(p.updated_at),
    }
