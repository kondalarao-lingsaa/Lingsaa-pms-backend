from datetime import date
from decimal import Decimal
from typing import Dict, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.automation import RECURRING_FREQUENCIES
from app.models.tasks import TASK_PRIORITIES
from app.schemas.rules import capitalize_first, person_name, title_text


class AutomationRuleIn(BaseModel):
    """Settings > Automation: one job's switch, time and numbers. Fields left out keep their value."""

    enabled: Optional[bool] = None
    run_time: Optional[str] = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    weekday: Optional[int] = Field(default=None, ge=0, le=6)
    # 1-28, so a monthly job runs in every month (February included).
    month_day: Optional[int] = Field(default=None, ge=1, le=28)
    params: Optional[Dict[str, int]] = None


class RecurringTaskIn(BaseModel):
    project_id: int
    title: str = Field(min_length=1, max_length=250)
    description: Optional[str] = Field(default=None, max_length=4000)
    priority: str = "Medium"
    assignee_id: Optional[int] = None
    assignee_name: Optional[str] = Field(default=None, max_length=200)
    estimated_hours: Optional[Decimal] = Field(default=None, ge=0, le=999.99, max_digits=8, decimal_places=2)
    frequency: str
    every: int = Field(default=1, ge=1, le=30)
    weekday: Optional[int] = Field(default=None, ge=0, le=6)
    month_day: Optional[int] = Field(default=None, ge=1, le=31)
    working_days_only: bool = True
    due_in_days: int = Field(default=0, ge=0, le=60)
    start_date: date
    end_date: Optional[date] = None
    is_active: bool = True

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

    @field_validator("priority")
    @classmethod
    def _priority(cls, v):
        if v not in TASK_PRIORITIES:
            raise ValueError(f"Priority must be one of: {', '.join(TASK_PRIORITIES)}")
        return v

    @field_validator("frequency")
    @classmethod
    def _frequency(cls, v):
        if v not in RECURRING_FREQUENCIES:
            raise ValueError("Please Select how often it repeats")
        return v

    @model_validator(mode="after")
    def _by_frequency(self):
        if self.frequency in ("Weekly", "Monthly") and self.every > 12:
            raise ValueError("Repeat every 1 to 12 weeks or months")
        return self
