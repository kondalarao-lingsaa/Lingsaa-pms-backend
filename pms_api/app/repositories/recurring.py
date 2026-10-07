"""Recurring tasks (Tasks > Recurring Tasks): a task that is created again on a schedule.

Daily (every N days, optionally working days only), Weekly (every N weeks on a weekday) or Monthly (every N
months on a day; short months use their last day). The "recurring_tasks" automation job creates each task on its
day for Active projects and moves next_run_on on; a schedule that passed while the server was off creates only
the latest missed task, never a pile of them.
"""
import calendar as month_calendar
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.core.access import project_scope
from app.models.automation import RecurringTask
from app.models.projects import Project
from app.models.tasks import Task
from app.repositories import work_calendar
from app.repositories.automation import WEEKDAYS
from app.schemas.rules import utc_iso

LOOKAHEAD_DAYS = 800


class RecurringError(Exception):
    """A recurring-task rule was broken; the message is safe to show to the user."""


def _months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def _matches(rule, cal, day: date) -> bool:
    if day < rule.start_date or (rule.end_date and day > rule.end_date):
        return False
    every = max(1, rule.every or 1)
    if rule.frequency == "Daily":
        if (day - rule.start_date).days % every:
            return False
        return not rule.working_days_only or cal.is_working(day)
    if rule.frequency == "Weekly":
        start_monday = rule.start_date - timedelta(days=rule.start_date.weekday())
        return day.weekday() == rule.weekday and ((day - start_monday).days // 7) % every == 0
    if rule.frequency == "Monthly":
        last = month_calendar.monthrange(day.year, day.month)[1]
        return day.day == min(rule.month_day, last) and _months_between(rule.start_date, day) % every == 0
    return False


def next_occurrence(rule, cal, on_or_after: date):
    """The first day on or after the given day when the rule creates a task (None once it has ended)."""
    day = max(on_or_after, rule.start_date)
    for _ in range(LOOKAHEAD_DAYS):
        if rule.end_date and day > rule.end_date:
            return None
        if _matches(rule, cal, day):
            return day
        day += timedelta(days=1)
    return None


def schedule_text(rule) -> str:
    n = max(1, rule.every or 1)
    if rule.frequency == "Daily":
        base = "Every working day" if n == 1 and rule.working_days_only else "Every day" if n == 1 else f"Every {n} days"
        return base + (" (working days only)" if rule.working_days_only and n > 1 else "")
    if rule.frequency == "Weekly":
        return f"Every {WEEKDAYS[rule.weekday]}" if n == 1 else f"Every {n} weeks on {WEEKDAYS[rule.weekday]}"
    suffix = "th" if 11 <= rule.month_day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(rule.month_day % 10, "th")
    return f"Every {'month' if n == 1 else f'{n} months'} on the {rule.month_day}{suffix}"


# ------------------------------------------------------------------------------ list / save


def _scoped(db: Session, principal):
    return (
        db.query(RecurringTask, Project)
        .join(Project, Project.id == RecurringTask.project_id)
        .filter(RecurringTask.client_id == principal.client_id, RecurringTask.is_deleted == False, Project.is_deleted == False,  # noqa: E712
                project_scope(db, principal))
    )


def get(db: Session, principal, rule_id):
    row = _scoped(db, principal).filter(RecurringTask.id == rule_id).first()
    return row[0] if row else None


def rule_out(rule: RecurringTask, project: Project, last_task_key=None) -> dict:
    return {
        "id": rule.id, "project_id": rule.project_id, "project_code": project.project_code, "project_name": project.project_name,
        "project_status": project.status, "title": rule.title, "description": rule.description, "priority": rule.priority,
        "assignee_id": rule.assignee_id, "assignee_name": rule.assignee_name,
        "estimated_hours": float(rule.estimated_hours) if rule.estimated_hours is not None else None,
        "frequency": rule.frequency, "every": rule.every, "weekday": rule.weekday, "month_day": rule.month_day,
        "working_days_only": bool(rule.working_days_only), "due_in_days": rule.due_in_days,
        "start_date": rule.start_date.isoformat(), "end_date": rule.end_date.isoformat() if rule.end_date else None,
        "next_run_on": rule.next_run_on.isoformat() if rule.next_run_on else None, "is_active": bool(rule.is_active),
        "created_count": rule.created_count, "last_task_id": rule.last_task_id, "last_task_key": last_task_key,
        "last_created_on": rule.last_created_on.isoformat() if rule.last_created_on else None, "last_note": rule.last_note,
        "schedule_text": schedule_text(rule), "created_by_name": rule.created_by_name, "updated_at": utc_iso(rule.updated_at),
    }


def list_rules(db: Session, principal, project_id=None, search=None) -> list:
    q = _scoped(db, principal)
    if project_id:
        q = q.filter(RecurringTask.project_id == project_id)
    if search:
        like = f"%{search.strip()}%"
        q = q.filter(RecurringTask.title.ilike(like) | Project.project_name.ilike(like) | RecurringTask.assignee_name.ilike(like))
    rows = q.order_by(RecurringTask.is_active.desc(), RecurringTask.next_run_on, RecurringTask.id).all()
    keys = dict(db.query(Task.id, Task.task_key).filter(Task.id.in_([r.last_task_id for r, _ in rows if r.last_task_id] or [-1])).all())
    return [rule_out(r, p, keys.get(r.last_task_id)) for r, p in rows]


def _project(db, principal, project_id):
    project = db.query(Project).filter(Project.id == project_id, Project.client_id == principal.client_id, Project.is_deleted == False,  # noqa: E712
                                       project_scope(db, principal)).one_or_none()
    if project is None:
        raise RecurringError("Project not found")
    if project.status == "Closed":
        raise RecurringError(f"{project.project_code} is Closed, so no new tasks can repeat on it")
    return project


def _check(db, principal, project, data, rule_id=None):
    from app.repositories import tasks as task_repo  # local import: tasks imports the automation hooks

    if data["frequency"] == "Weekly" and data.get("weekday") is None:
        raise RecurringError("Please Select the weekday")
    if data["frequency"] == "Monthly" and not data.get("month_day"):
        raise RecurringError("Please Enter the day of the month")
    if data.get("end_date") and data["end_date"] < data["start_date"]:
        raise RecurringError("The end date cannot be before the start date")
    if project.end_date and data["start_date"] > project.end_date:
        raise RecurringError(f"The start date is after the project ends ({project.end_date.strftime('%d %b %Y')})")
    if project.start_date and data.get("end_date") and data["end_date"] < project.start_date:
        raise RecurringError(f"The end date is before the project starts ({project.start_date.strftime('%d %b %Y')})")
    dupe = db.query(RecurringTask.id).filter(RecurringTask.project_id == project.id, RecurringTask.is_deleted == False,  # noqa: E712
                                            RecurringTask.title == data["title"])
    if rule_id:
        dupe = dupe.filter(RecurringTask.id != rule_id)
    if dupe.first():
        raise RecurringError(f"'{data['title']}' already repeats in this project")
    try:
        task_repo._apply_assignee(db, principal, project.id, data)
    except task_repo.TaskError as exc:
        raise RecurringError(str(exc)) from exc
    # Only the fields the schedule uses are kept for each frequency.
    if data["frequency"] != "Weekly":
        data["weekday"] = None
    if data["frequency"] != "Monthly":
        data["month_day"] = None
    if data["frequency"] != "Daily":
        data["working_days_only"] = False


def _reschedule(db, rule: RecurringTask) -> None:
    cal = work_calendar.for_client(db, rule.client_id)
    rule.next_run_on = next_occurrence(rule, cal, max(rule.start_date, date.today())) if rule.is_active else None


def create(db: Session, principal, data: dict) -> RecurringTask:
    project = _project(db, principal, data["project_id"])
    _check(db, principal, project, data)
    rule = RecurringTask(**data, client_id=principal.client_id, created_by=principal.user_id, created_by_name=principal.user_name,
                         updated_by=principal.user_id)
    _reschedule(db, rule)
    if rule.next_run_on is None:
        raise RecurringError("With these dates the task would never be created. Check the start and end dates")
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def update(db: Session, principal, rule: RecurringTask, data: dict) -> RecurringTask:
    if data["project_id"] != rule.project_id:
        raise RecurringError("A recurring task cannot move to another project")
    project = _project(db, principal, rule.project_id)
    _check(db, principal, project, data, rule_id=rule.id)
    for key, value in data.items():
        setattr(rule, key, value)
    rule.updated_by = principal.user_id
    rule.last_note = None
    # Never create a second task for a day that already has one.
    _reschedule(db, rule)
    if rule.next_run_on and rule.last_created_on and rule.next_run_on <= rule.last_created_on:
        rule.next_run_on = next_occurrence(rule, work_calendar.for_client(db, rule.client_id), rule.last_created_on + timedelta(days=1))
    if rule.is_active and rule.next_run_on is None:
        raise RecurringError("With these dates the task would never be created again. Check the start and end dates, or pause it")
    db.commit()
    db.refresh(rule)
    return rule


def delete(db: Session, principal, rule: RecurringTask) -> None:
    # Tasks already created stay; only the schedule goes.
    rule.is_deleted = True
    rule.is_active = False
    rule.next_run_on = None
    rule.updated_by = principal.user_id
    db.commit()


def project_of(db: Session, rule: RecurringTask) -> Project:
    return db.query(Project).filter(Project.id == rule.project_id).one()
