from datetime import date
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.rules import capitalize_first, utc_iso

MAX_HOURS_PER_DAY = Decimal("24")


class EntryIn(BaseModel):
    """One cell of the weekly grid. hours = 0 clears the cell."""

    task_id: int
    work_date: date
    hours: Decimal = Field(ge=0, le=24, max_digits=5, decimal_places=2)
    note: Optional[str] = Field(default=None, max_length=500)

    @field_validator("hours")
    @classmethod
    def _quarter_hours(cls, v):
        # Time is recorded in 15-minute steps (0.25 h), like most timesheet systems.
        if (v * 4) % 1 != 0:
            raise ValueError("Hours must be in steps of 0.25 (15 minutes), e.g. 1.5 or 2.75")
        return v

    @field_validator("note")
    @classmethod
    def _note(cls, v):
        return capitalize_first(v)


class WeekIn(BaseModel):
    week_start: date

    @field_validator("week_start")
    @classmethod
    def _monday(cls, v):
        if v.weekday() != 0:
            raise ValueError("A timesheet week starts on a Monday")
        return v


class ReviewIn(BaseModel):
    entry_ids: List[int] = Field(min_length=1, max_length=500)


class RejectIn(ReviewIn):
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def _reason(cls, v):
        v = capitalize_first(" ".join(v.split()))
        if not v or len(v) < 5:
            raise ValueError("Please Enter a Reason (at least 5 characters) so the person knows what to fix")
        return v


def _num(v):
    return float(v) if v is not None else None


def entry_out(e, *, task_key=None, task_title=None, project_code=None, project_name=None, rate=None) -> dict:
    hours = float(e.hours)
    effective_rate = e.hourly_rate if e.hourly_rate is not None else rate
    return {
        "id": e.id,
        "project_id": e.project_id,
        "project_code": project_code,
        "project_name": project_name,
        "task_id": e.task_id,
        "task_key": task_key,
        "task_title": task_title,
        "member_id": e.member_id,
        "user_id": e.user_id,
        "member_name": e.member_name,
        "work_date": e.work_date.isoformat(),
        "hours": hours,
        "note": e.note,
        "status": e.status,
        "hourly_rate": _num(effective_rate),
        "cost": round(hours * float(effective_rate), 2) if effective_rate is not None else None,
        "submitted_at": utc_iso(e.submitted_at),
        "reviewed_by_name": e.reviewed_by_name,
        "reviewed_at": utc_iso(e.reviewed_at),
        "reject_reason": e.reject_reason,
    }
