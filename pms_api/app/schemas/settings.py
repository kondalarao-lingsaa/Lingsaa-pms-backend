from datetime import date
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.tasks import TASK_PRIORITIES as PRIORITIES
from app.models.tasks import TASK_TYPES
from app.schemas.rules import capitalize_first, title_text

MAX_TEMPLATE_DAYS = 1095  # three years
MAX_TEMPLATE_TASKS = 200
MAX_TEMPLATE_MILESTONES = 50


class IndustryIn(BaseModel):
    industry: str
    member_roles: List[str] = Field(min_length=2, max_length=30)

    @field_validator("industry")
    @classmethod
    def _industry(cls, v):
        from app.core.industries import INDUSTRIES

        v = " ".join((v or "").split())
        if v in INDUSTRIES:
            return v
        # A company's own industry (for example "Solar Installation"): it starts from the General preset.
        if len(v) < 2 or len(v) > 60:
            raise ValueError("Please Enter your Industry (2 to 60 characters)")
        if "|" in v or not any(c.isalpha() for c in v):
            raise ValueError("Please Enter a valid Industry name")
        return v[:1].upper() + v[1:]

    @field_validator("member_roles")
    @classmethod
    def _roles(cls, v):
        from app.core.industries import PM_ROLE

        roles, seen = [], set()
        for raw in v:
            role = " ".join(str(raw or "").split())
            if not role:
                continue
            if len(role) < 2 or len(role) > 60:
                raise ValueError(f"Role '{role}' must be 2 to 60 characters")
            if "|" in role:
                raise ValueError("A role name cannot contain |")
            if role.lower() in seen:
                raise ValueError(f"Role '{role}' is listed twice")
            seen.add(role.lower())
            roles.append(role)
        if PM_ROLE not in roles:
            raise ValueError(f"Keep the '{PM_ROLE}' role: the project manager joins every team with it")
        if len(roles) < 2:
            raise ValueError("Add at least one role besides Project Manager")
        return roles


class CalendarIn(BaseModel):
    hours_per_day: Decimal = Field(ge=1, le=24, max_digits=4, decimal_places=2)
    working_days: List[int] = Field(min_length=1, max_length=7)

    @field_validator("hours_per_day")
    @classmethod
    def _half_hours(cls, v):
        if (v * 2) % 1:
            raise ValueError("Hours per day must be in steps of 0.5")
        return v

    @field_validator("working_days")
    @classmethod
    def _days(cls, v):
        if any(d < 0 or d > 6 for d in v):
            raise ValueError("Working days must be Monday (0) to Sunday (6)")
        return sorted(set(v))


class HolidayIn(BaseModel):
    holiday_date: date
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        return title_text(v, "Holiday name", required=True, min_len=2)


class TemplateMilestoneIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    due_offset: Optional[int] = Field(default=None, ge=0, le=MAX_TEMPLATE_DAYS)
    amount: Optional[Decimal] = Field(default=None, ge=0, max_digits=14, decimal_places=2)

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        return title_text(v, "Milestone name", required=True)

    @field_validator("description")
    @classmethod
    def _description(cls, v):
        return capitalize_first(v)


class TemplateTaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: Optional[str] = Field(default=None, max_length=4000)
    task_type: str = "Task"
    priority: str = "Medium"
    estimated_hours: Optional[Decimal] = Field(default=None, ge=0, le=9999, max_digits=8, decimal_places=2)
    start_offset: Optional[int] = Field(default=None, ge=0, le=MAX_TEMPLATE_DAYS)
    duration_days: Optional[int] = Field(default=None, ge=1, le=MAX_TEMPLATE_DAYS)
    milestone_index: Optional[int] = Field(default=None, ge=0)
    parent_index: Optional[int] = Field(default=None, ge=0)

    @field_validator("title")
    @classmethod
    def _title(cls, v):
        return title_text(v, "Task name", required=True, words=False)

    @field_validator("description")
    @classmethod
    def _description(cls, v):
        return capitalize_first(v)

    @field_validator("priority")
    @classmethod
    def _priority(cls, v):
        if v not in PRIORITIES:
            raise ValueError(f"Priority must be one of {', '.join(PRIORITIES)}")
        return v

    @field_validator("task_type")
    @classmethod
    def _type(cls, v):
        if v not in TASK_TYPES:
            raise ValueError(f"Type must be one of {', '.join(TASK_TYPES)}")
        return v


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=1000)
    project_type: Optional[str] = Field(default=None, max_length=100)
    duration_days: int = Field(ge=1, le=MAX_TEMPLATE_DAYS)
    milestones: List[TemplateMilestoneIn] = Field(default_factory=list, max_length=MAX_TEMPLATE_MILESTONES)
    tasks: List[TemplateTaskIn] = Field(default_factory=list, max_length=MAX_TEMPLATE_TASKS)

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        return title_text(v, "Template name", required=True)

    @field_validator("description")
    @classmethod
    def _description(cls, v):
        return capitalize_first(v)

    @model_validator(mode="after")
    def _plan(self):
        if not self.tasks and not self.milestones:
            raise ValueError("Add at least one task or milestone")
        names = [m.name.lower() for m in self.milestones]
        if len(names) != len(set(names)):
            raise ValueError("Two milestones have the same name")
        for i, m in enumerate(self.milestones, start=1):
            if m.due_offset is not None and m.due_offset > self.duration_days:
                raise ValueError(f"Milestone {i} ({m.name}) is due on day {m.due_offset}, after the project length of {self.duration_days} days")
        for i, t in enumerate(self.tasks, start=1):
            if t.start_offset is not None and t.start_offset + (t.duration_days or 1) - 1 > self.duration_days:
                raise ValueError(f"Task {i} ({t.title}) ends after the project length of {self.duration_days} days")
            if t.milestone_index is not None and t.milestone_index >= len(self.milestones):
                raise ValueError(f"Task {i} ({t.title}) points to a milestone that is not in the list")
            if t.parent_index is not None:
                if t.parent_index >= len(self.tasks) or t.parent_index == i - 1:
                    raise ValueError(f"Task {i} ({t.title}) has an invalid parent task")
                if self.tasks[t.parent_index].parent_index is not None:
                    raise ValueError(f"Task {i} ({t.title}): subtasks can only sit under a main task")
        return self


class SaveAsTemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        return title_text(v, "Template name", required=True)

    @field_validator("description")
    @classmethod
    def _description(cls, v):
        return capitalize_first(v)


class ProjectSettingsIn(BaseModel):
    default_task_priority: str = "Medium"
    default_estimate_hours: Optional[Decimal] = Field(default=None, ge=0, le=9999, max_digits=8, decimal_places=2)
    task_labels: List[str] = Field(default_factory=list, max_length=30)
    timesheet_lock_days: Optional[int] = Field(default=None, ge=1, le=90)
    budget_alert_pct: int = Field(default=80, ge=50, le=100)
    receipt_required_above: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("999999999"), max_digits=14, decimal_places=2)
    default_tax_pct: Decimal = Field(default=Decimal("18"), ge=0, le=28, max_digits=5, decimal_places=2)
    default_payment_terms: int = Field(default=30, ge=0, le=180)

    @field_validator("default_task_priority")
    @classmethod
    def _priority(cls, v):
        if v not in PRIORITIES:
            raise ValueError(f"Priority must be one of {', '.join(PRIORITIES)}")
        return v

    @field_validator("task_labels")
    @classmethod
    def _labels(cls, v):
        out = []
        for label in v:
            label = (label or "").strip().lower()
            if not label:
                continue
            if len(label) > 30 or "," in label:
                raise ValueError("Each label can be at most 30 characters, without commas")
            if label not in out:
                out.append(label)
        return out
