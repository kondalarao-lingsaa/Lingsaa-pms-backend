from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.milestones import MILESTONE_STATUSES, MILESTONE_TRANSITIONS
from app.schemas.rules import capitalize_first, title_text, utc_iso


class MilestoneIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    due_date: Optional[date] = None
    amount: Optional[Decimal] = Field(default=None, ge=0, max_digits=14, decimal_places=2)

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        return title_text(v, "Milestone name", required=True)

    @field_validator("description")
    @classmethod
    def _description(cls, v):
        return capitalize_first(v)


class MilestoneStatusIn(BaseModel):
    status: str
    feedback: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("status")
    @classmethod
    def _known(cls, v):
        if v not in MILESTONE_STATUSES:
            raise ValueError(f"Status must be one of: {', '.join(MILESTONE_STATUSES)}")
        return v

    @field_validator("feedback")
    @classmethod
    def _feedback(cls, v):
        return capitalize_first(" ".join(v.split())) if v else None


class DeliverableIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        return title_text(v, "Deliverable name", required=True, min_len=2, words=False)


class DeliverableDoneIn(BaseModel):
    is_done: bool


def milestone_out(m, *, deliverables=(), task_stats=None, invoice=None, project=None) -> dict:
    stats = task_stats or {"total": 0, "done": 0}
    done_deliverables = sum(1 for d in deliverables if d.is_done)
    parts = stats["total"] + len(deliverables)
    progress = round((stats["done"] + done_deliverables) / parts * 100) if parts else 0
    return {
        "id": m.id,
        "project_id": m.project_id,
        "project_code": project.project_code if project else None,
        "project_name": project.project_name if project else None,
        "name": m.name,
        "description": m.description,
        "due_date": m.due_date.isoformat() if m.due_date else None,
        "baseline_due_date": m.baseline_due_date.isoformat() if m.baseline_due_date else None,
        "is_overdue": bool(m.due_date and m.due_date < date.today() and m.status != "Accepted"),
        "amount": float(m.amount) if m.amount is not None else None,
        "status": m.status,
        "next_statuses": MILESTONE_TRANSITIONS.get(m.status, []),
        "feedback": m.feedback,
        "accepted_at": utc_iso(m.accepted_at),
        "accepted_by_name": m.accepted_by_name,
        "task_count": stats["total"],
        "tasks_done": stats["done"],
        "deliverables": [
            {"id": d.id, "name": d.name, "is_done": d.is_done, "done_at": utc_iso(d.done_at), "done_by_name": d.done_by_name} for d in deliverables
        ],
        "deliverables_done": done_deliverables,
        "progress": progress,
        "invoice": invoice,
    }
