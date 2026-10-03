from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.rules import EMAIL_REGEX, clean, person_name, utc_iso


class MemberIn(BaseModel):
    member_name: str = Field(min_length=1, max_length=200)
    user_id: Optional[int] = None
    email: Optional[str] = Field(default=None, max_length=150)
    role: str
    allocation_pct: int = Field(ge=1, le=100)
    hourly_rate: Optional[Decimal] = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    start_date: Optional[date] = None
    end_date: Optional[date] = None

    @field_validator("member_name")
    @classmethod
    def _name(cls, v):
        v = person_name(v)
        if not v:
            raise ValueError("Please Enter Member Name")
        return v

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        v = clean(v)
        if v and not EMAIL_REGEX.match(v):
            raise ValueError("Enter a valid email address (e.g. name@example.com)")
        return v.lower() if v else v

    @field_validator("role")
    @classmethod
    def _role(cls, v):
        # Which roles exist is the company's list (Settings > Industry); checked when saving the member.
        v = " ".join(str(v or "").split())
        if not v:
            raise ValueError("Please Select Role")
        return v

    @model_validator(mode="after")
    def _dates(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("End date cannot be before start date")
        return self


def member_out(m, stats=None) -> dict:
    stats = stats or {}
    return {
        "id": m.id,
        "project_id": m.project_id,
        "user_id": m.user_id,
        "member_name": m.member_name,
        "email": m.email,
        "role": m.role,
        "allocation_pct": m.allocation_pct,
        "hourly_rate": float(m.hourly_rate) if m.hourly_rate is not None else None,
        "start_date": m.start_date.isoformat() if m.start_date else None,
        "end_date": m.end_date.isoformat() if m.end_date else None,
        "open_tasks": stats.get("open", 0),
        "done_tasks": stats.get("done", 0),
        "overdue_tasks": stats.get("overdue", 0),
        "created_at": utc_iso(m.created_at),
    }
