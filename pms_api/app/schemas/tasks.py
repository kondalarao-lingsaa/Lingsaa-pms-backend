from datetime import date
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.rules import LABEL_REGEX, capitalize_first, person_name, title_text, utc_iso
from app.models.tasks import TASK_PRIORITIES, TASK_STATUSES, TASK_TYPES


class TaskIn(BaseModel):
    project_id: int
    title: str = Field(min_length=1, max_length=300)
    description: Optional[str] = Field(default=None, max_length=4000)
    task_type: str = "Task"
    parent_task_id: Optional[int] = None
    milestone_id: Optional[int] = None
    assignee_id: Optional[int] = None
    assignee_name: Optional[str] = Field(default=None, max_length=200)
    priority: str = "Medium"
    status: str = "To Do"
    start_date: Optional[date] = None
    due_date: Optional[date] = None
    estimated_hours: Optional[Decimal] = Field(default=None, ge=0, le=999.99, max_digits=8, decimal_places=2)
    actual_hours: Optional[Decimal] = Field(default=None, ge=0, le=999.99, max_digits=8, decimal_places=2)
    labels: List[str] = []

    @field_validator("title")
    @classmethod
    def _title(cls, v):
        return title_text(v, "Task name", required=True, words=False)

    @field_validator("description")
    @classmethod
    def _description(cls, v):
        return capitalize_first(v)

    @field_validator("assignee_name")
    @classmethod
    def _assignee(cls, v):
        return person_name(v)

    @field_validator("task_type")
    @classmethod
    def _type(cls, v):
        if v not in TASK_TYPES:
            raise ValueError(f"Type must be one of: {', '.join(TASK_TYPES)}")
        return v

    @field_validator("priority")
    @classmethod
    def _priority(cls, v):
        if v not in TASK_PRIORITIES:
            raise ValueError(f"Priority must be one of: {', '.join(TASK_PRIORITIES)}")
        return v

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        if v not in TASK_STATUSES:
            raise ValueError(f"Status must be one of: {', '.join(TASK_STATUSES)}")
        return v

    @field_validator("labels")
    @classmethod
    def _labels(cls, v):
        cleaned = []
        for label in v:
            label = " ".join(label.split())
            if not label:
                continue
            if len(label) > 50 or not LABEL_REGEX.match(label):
                raise ValueError("Labels can use letters, numbers, spaces, - and _ (up to 50 characters)")
            if label.lower() not in [c.lower() for c in cleaned]:
                cleaned.append(label)
        if len(cleaned) > 10:
            raise ValueError("A task can have at most 10 labels")
        return cleaned

    @model_validator(mode="after")
    def _dates(self):
        if self.start_date and self.due_date and self.due_date < self.start_date:
            raise ValueError("Due date cannot be before start date")
        return self


class TaskStatusChange(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def _known(cls, v):
        if v not in TASK_STATUSES:
            raise ValueError(f"Status must be one of: {', '.join(TASK_STATUSES)}")
        return v


def _num(value):
    return float(value) if value is not None else None


def task_out(t, *, project_code=None, project_name=None, labels=None, parent=None, subtask_count=0, milestone_name=None, sprint_name=None) -> dict:
    return {
        "id": t.id,
        "task_key": t.task_key,
        "task_type": t.task_type,
        "title": t.title,
        "description": t.description,
        "project_id": t.project_id,
        "project_code": project_code,
        "project_name": project_name,
        "parent_task_id": t.parent_task_id,
        "parent_key": parent[0] if parent else None,
        "parent_title": parent[1] if parent else None,
        "subtask_count": subtask_count,
        "milestone_id": t.milestone_id,
        "milestone_name": milestone_name,
        "sprint_id": t.sprint_id,
        "sprint_name": sprint_name,
        "assignee_id": t.assignee_id,
        "assignee_name": t.assignee_name,
        "reporter_id": t.reporter_id,
        "reporter_name": t.reporter_name,
        "priority": t.priority,
        "status": t.status,
        "start_date": t.start_date.isoformat() if t.start_date else None,
        "due_date": t.due_date.isoformat() if t.due_date else None,
        "is_overdue": bool(t.due_date and t.due_date < date.today() and t.status != "Done"),
        "estimated_hours": _num(t.estimated_hours),
        "actual_hours": _num(t.actual_hours),
        "labels": labels or [],
        "created_at": utc_iso(t.created_at),
        "updated_at": utc_iso(t.updated_at),
    }


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)

    @field_validator("body")
    @classmethod
    def _body(cls, v):
        v = capitalize_first(v.strip()) if v else v
        if not v:
            raise ValueError("Please Enter a Comment")
        return v


class DependencyIn(BaseModel):
    depends_on_id: int


class WatchIn(BaseModel):
    watching: bool


class TaskMove(BaseModel):
    """A card dropped on the board: its new column and the cards directly above and below it."""

    status: str
    prev_id: Optional[int] = None
    next_id: Optional[int] = None

    @field_validator("status")
    @classmethod
    def _known(cls, v):
        if v not in TASK_STATUSES:
            raise ValueError(f"Status must be one of: {', '.join(TASK_STATUSES)}")
        return v
