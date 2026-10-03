from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.risks import (
    CHANGE_TYPES,
    ISSUE_SEVERITIES,
    ISSUE_STATUSES,
    ISSUE_TRANSITIONS,
    RISK_CATEGORIES,
    RISK_STATUSES,
    RISK_TRANSITIONS,
    risk_level,
)
from app.schemas.rules import capitalize_first, title_text, utc_iso


def _text(v, max_len=2000):
    v = capitalize_first(" ".join(v.split())) if v else None
    return v[:max_len] if v else v


class RiskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    category: str
    probability: int = Field(ge=1, le=5)
    impact: int = Field(ge=1, le=5)
    owner_member_id: Optional[int] = None
    mitigation: Optional[str] = Field(default=None, max_length=2000)
    contingency: Optional[str] = Field(default=None, max_length=2000)
    review_date: Optional[date] = None
    milestone_id: Optional[int] = None

    @field_validator("title")
    @classmethod
    def _title(cls, v):
        return title_text(v, "Risk title", required=True, words=False)

    @field_validator("description", "mitigation", "contingency")
    @classmethod
    def _texts(cls, v):
        return _text(v)

    @field_validator("category")
    @classmethod
    def _category(cls, v):
        if v not in RISK_CATEGORIES:
            raise ValueError("Please Select Category")
        return v

    @model_validator(mode="after")
    def _high_needs_plan(self):
        # A High risk without a plan is just a worry: the mitigation is mandatory from score 15.
        if risk_level(self.probability * self.impact) == "High" and (not self.mitigation or len(self.mitigation) < 10):
            raise ValueError("Please Enter a Mitigation plan (at least 10 characters) - it is required for High risks")
        return self


class RiskStatusIn(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def _known(cls, v):
        if v not in RISK_STATUSES:
            raise ValueError(f"Status must be one of: {', '.join(RISK_STATUSES)}")
        return v


class IssueIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    severity: str = "Medium"
    owner_member_id: Optional[int] = None
    due_date: Optional[date] = None
    risk_id: Optional[int] = None

    @field_validator("title")
    @classmethod
    def _title(cls, v):
        return title_text(v, "Issue title", required=True, words=False)

    @field_validator("description")
    @classmethod
    def _description(cls, v):
        return _text(v)

    @field_validator("severity")
    @classmethod
    def _severity(cls, v):
        if v not in ISSUE_SEVERITIES:
            raise ValueError("Please Select Severity")
        return v


class IssueStatusIn(BaseModel):
    status: str
    resolution: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("status")
    @classmethod
    def _known(cls, v):
        if v not in ISSUE_STATUSES:
            raise ValueError(f"Status must be one of: {', '.join(ISSUE_STATUSES)}")
        return v

    @field_validator("resolution")
    @classmethod
    def _resolution(cls, v):
        return _text(v)


class ChangeRequestIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)
    change_type: str
    cost_impact: Optional[Decimal] = Field(default=None, ge=Decimal("-999999999999"), le=Decimal("999999999999"), max_digits=14, decimal_places=2)
    days_impact: Optional[int] = Field(default=None, ge=-365, le=730)
    milestone_id: Optional[int] = None

    @field_validator("title")
    @classmethod
    def _title(cls, v):
        return title_text(v, "Change title", required=True, words=False)

    @field_validator("reason")
    @classmethod
    def _reason(cls, v):
        v = _text(v)
        if not v or len(v) < 10:
            raise ValueError("Please Enter the Reason for the change (at least 10 characters)")
        return v

    @field_validator("change_type")
    @classmethod
    def _type(cls, v):
        if v not in CHANGE_TYPES:
            raise ValueError("Please Select Change Type")
        return v

    @model_validator(mode="after")
    def _impact(self):
        if not self.cost_impact and not self.days_impact and self.change_type != "Scope":
            raise ValueError("A Cost or Schedule change needs a cost impact or a days impact")
        if self.milestone_id and not self.cost_impact:
            raise ValueError("Pick a milestone only when there is a cost impact to add to it")
        return self


class DecisionIn(BaseModel):
    note: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("note")
    @classmethod
    def _note(cls, v):
        return _text(v, 1000)


def _d(v):
    return v.isoformat() if v else None


def risk_out(r, *, project=None, milestone_name=None, issue_count=0) -> dict:
    score = r.probability * r.impact
    return {
        "id": r.id, "risk_key": r.risk_key, "project_id": r.project_id,
        "project_code": project.project_code if project else None, "project_name": project.project_name if project else None, "project_status": project.status if project else None,
        "title": r.title, "description": r.description, "category": r.category, "probability": r.probability, "impact": r.impact,
        "score": score, "level": risk_level(score), "status": r.status, "next_statuses": RISK_TRANSITIONS.get(r.status, []),
        "owner_member_id": r.owner_member_id, "owner_name": r.owner_name, "mitigation": r.mitigation, "contingency": r.contingency,
        "review_date": _d(r.review_date), "review_due": bool(r.review_date and r.review_date <= date.today() and r.status in ("Open", "Monitoring")),
        "milestone_id": r.milestone_id, "milestone_name": milestone_name, "issue_count": issue_count,
        "raised_by_name": r.raised_by_name, "created_at": utc_iso(r.created_at), "closed_at": utc_iso(r.closed_at),
    }


def issue_out(i, *, project=None, task=None, risk_key=None) -> dict:
    return {
        "id": i.id, "issue_key": i.issue_key, "project_id": i.project_id,
        "project_code": project.project_code if project else None, "project_name": project.project_name if project else None, "project_status": project.status if project else None,
        "title": i.title, "description": i.description, "severity": i.severity, "status": i.status,
        "next_statuses": ISSUE_TRANSITIONS.get(i.status, []), "owner_member_id": i.owner_member_id, "owner_name": i.owner_name,
        "due_date": _d(i.due_date), "is_overdue": bool(i.due_date and i.due_date < date.today() and i.status in ("Open", "In Progress")),
        "risk_id": i.risk_id, "risk_key": risk_key, "task_id": i.task_id,
        "task_key": task.task_key if task else None, "task_status": task.status if task else None,
        "resolution": i.resolution, "resolved_at": utc_iso(i.resolved_at), "raised_by_name": i.raised_by_name, "created_at": utc_iso(i.created_at),
    }


def change_out(c, *, project=None, milestone_name=None) -> dict:
    return {
        "id": c.id, "cr_key": c.cr_key, "project_id": c.project_id,
        "project_code": project.project_code if project else None, "project_name": project.project_name if project else None, "project_status": project.status if project else None,
        "title": c.title, "reason": c.reason, "change_type": c.change_type,
        "cost_impact": float(c.cost_impact) if c.cost_impact is not None else None, "days_impact": c.days_impact,
        "milestone_id": c.milestone_id, "milestone_name": milestone_name, "status": c.status, "decision_note": c.decision_note,
        "decided_by_name": c.decided_by_name, "decided_at": utc_iso(c.decided_at), "applied_summary": c.applied_summary,
        "raised_by": c.raised_by, "raised_by_name": c.raised_by_name, "created_at": utc_iso(c.created_at),
    }
