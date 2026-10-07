"""Automation: jobs the PMS runs by itself so nobody has to remember them (Settings > Automation).

Two kinds of job:
- Scheduled: run once a day / week / month at the company's chosen time by the background scheduler
  (app/core/scheduler.py): reminders, the weekly status report, budget and invoice alerts, monthly invoices,
  recurring tasks, finishing sprints.
- Event: run straight after something happens in the app (a milestone accepted -> draft invoice; the last
  subtask done -> its main task done; all of a milestone's work done -> Ready for Review).

Each company switches every job on or off and sets its time and numbers. Every run is written to the run
history with what it did. The jobs themselves live in app/repositories/automation_jobs.py.
"""
import calendar
import json
import logging
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import text, union
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import roles
from app.core.security import Principal
from app.models.access import UserRole
from app.models.automation import AutomationRule, AutomationRun, AutomationSent
from app.models.projects import Project
from app.models.settings import CompanySettings
from app.repositories import work_calendar
from app.schemas.rules import utc_iso

logger = logging.getLogger("pms.automation")

SYSTEM_NAME = "Automation"
GROUPS = ["Reminders", "Reports & alerts", "Billing", "Work"]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
RUN_HISTORY_DAYS = 90


def _utcnow():
    """Stored timestamps are UTC, like SQL Server's own clock (schemas.rules.utc_iso). Schedules use local time."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _int(label, default, lo, hi, hint=None):
    return {"label": label, "type": "int", "default": default, "min": lo, "max": hi, "hint": hint}


# key -> how the job runs by default. schedule: daily | weekly | monthly | event.
# working_days: a scheduled job that only runs on the company's working days (no reminders on Sundays/holidays).
JOBS = {
    "task_reminders": {
        "group": "Reminders", "title": "Task due and overdue reminders", "schedule": "daily", "run_time": "09:00", "working_days": True,
        "description": "Each person gets one message listing their tasks due today or tomorrow and their overdue tasks. "
                       "A task still overdue after the set days is escalated to its project manager (once per due date).",
        "params": {"escalate_after_days": _int("Tell the project manager after (days overdue)", 3, 1, 60)},
    },
    "approval_reminders": {
        "group": "Reminders", "title": "Approval reminders", "schedule": "daily", "run_time": "09:30", "working_days": True,
        "description": "Approvers with requests waiting get a reminder; requests waiting too long are escalated to the Admins.",
        "params": {"remind_after_days": _int("Remind after (days waiting)", 2, 1, 30),
                   "escalate_after_days": _int("Escalate to Admins after (days waiting)", 4, 1, 60)},
    },
    "timesheet_reminders": {
        "group": "Reminders", "title": "Timesheet reminder", "schedule": "weekly", "weekday": 4, "run_time": "16:00",
        "description": "Team members of Active projects who have not logged or not submitted this week's hours are reminded to.",
        "params": {},
    },
    "timesheet_missing": {
        "group": "Reminders", "title": "Missing timesheets report", "schedule": "weekly", "weekday": 0, "run_time": "10:00",
        "description": "Each project manager gets the list of their team members who did not submit last week's timesheet.",
        "params": {},
    },
    "weekly_status_report": {
        "group": "Reports & alerts", "title": "Weekly project status report", "schedule": "weekly", "weekday": 0, "run_time": "08:30",
        "description": "Project managers get the status of their projects; Directors and Admins get every project: health, "
                       "progress, overdue tasks, budget used and the next milestone.",
        "params": {},
    },
    "budget_alerts": {
        "group": "Reports & alerts", "title": "Budget alerts", "schedule": "daily", "run_time": "08:45", "working_days": True,
        "description": "When a project's approved cost passes its alert % (Project Settings, default 80%) and again when it "
                       "passes 100%, the project manager, Finance and Directors are told (once per level and budget).",
        "params": {},
    },
    "deadline_alerts": {
        "group": "Reports & alerts", "title": "Project deadline alerts", "schedule": "daily", "run_time": "08:50", "working_days": True,
        "description": "When an Active project ends within the set days and its work is not finished, its project manager is told (once).",
        "params": {"days_before": _int("Warn this many days before the end date", 7, 1, 60)},
    },
    "milestone_invoice": {
        "group": "Billing", "title": "Draft invoice when a milestone is accepted", "schedule": "event",
        "description": "As soon as a milestone with an amount is accepted (by the client or for them), a Draft milestone "
                       "invoice is created with the project's tax and payment terms. Finance reviews and issues it.",
        "params": {},
    },
    "monthly_invoices": {
        "group": "Billing", "title": "Monthly time & material invoices", "schedule": "monthly", "month_day": 1, "run_time": "07:00",
        "description": "On the set day, every billable project gets a Draft invoice for last month's approved, unbilled hours "
                       "and billable expenses. Projects with people missing a billing rate are listed for the project manager instead.",
        "params": {},
    },
    "invoice_reminders": {
        "group": "Billing", "title": "Invoice due and overdue reminders", "schedule": "daily", "run_time": "09:15", "working_days": True,
        "description": "Finance and the project manager hear about issued invoices falling due soon, and about overdue ones "
                       "again every few days until they are paid.",
        "params": {"due_soon_days": _int("Warn this many days before the due date", 3, 0, 30, "0 = no early warning"),
                   "repeat_every_days": _int("Repeat overdue reminders every (days)", 7, 1, 30)},
    },
    "recurring_tasks": {
        "group": "Work", "title": "Create recurring tasks", "schedule": "daily", "run_time": "06:00",
        "description": "Creates the tasks set up in Tasks > Recurring Tasks on their days (Active projects only) and tells the assignee.",
        "params": {},
    },
    "sprint_auto_complete": {
        "group": "Work", "title": "Complete sprints on their end date", "schedule": "daily", "run_time": "07:30",
        "description": "An Active sprint past its end date is completed: unfinished tasks move to the next Planned sprint "
                       "(or the backlog) and the project manager is told.",
        "params": {},
    },
    "parent_auto_done": {
        "group": "Work", "title": "Finish a main task when its subtasks are done", "schedule": "event",
        "description": "When the last open subtask is done, its main task moves to Done. If a subtask is reopened, a Done "
                       "main task moves back to In Progress.",
        "params": {},
    },
    "milestone_auto_review": {
        "group": "Work", "title": "Send a milestone for review when its work is done", "schedule": "event",
        "description": "When every linked task and deliverable of an In Progress milestone is done, it moves to Ready for "
                       "Review and the approvers are told.",
        "params": {},
    },
}


class AutomationError(Exception):
    """A rule of the automation settings was broken; the message is safe to show to the user."""


def system_principal(client_id, user_id=None, user_name=SYSTEM_NAME) -> Principal:
    """Who automation acts as. No role: company-wide, like other internal callers (access.project_scope)."""
    return Principal(client_id=client_id, user_id=user_id, user_name=user_name, role=None, is_superadmin=False, raw_claims={})


# ------------------------------------------------------------------------------ settings per company


def _defaults(job_key) -> dict:
    job = JOBS[job_key]
    return {"enabled": True, "run_time": job.get("run_time"), "weekday": job.get("weekday"), "month_day": job.get("month_day"),
            "params": {k: p["default"] for k, p in job["params"].items()}}


def _params(job_key, row) -> dict:
    values = _defaults(job_key)["params"]
    if row is not None and row.params:
        try:
            stored = json.loads(row.params)
        except ValueError:
            stored = {}
        values.update({k: v for k, v in stored.items() if k in values})
    return values


def rule_values(job_key, row) -> dict:
    """The job's settings for one company: its row, else the defaults."""
    d = _defaults(job_key)
    if row is None:
        return d
    return {"enabled": bool(row.enabled), "run_time": row.run_time or d["run_time"],
            "weekday": row.weekday if row.weekday is not None else d["weekday"],
            "month_day": row.month_day if row.month_day is not None else d["month_day"], "params": _params(job_key, row)}


def _rows(db: Session, client_id) -> dict:
    return {r.job_key: r for r in db.query(AutomationRule).filter(AutomationRule.client_id == client_id)}


def is_enabled(db: Session, client_id, job_key) -> bool:
    row = db.query(AutomationRule.enabled).filter(AutomationRule.client_id == client_id, AutomationRule.job_key == job_key).first()
    return True if row is None else bool(row[0])


def params_for(db: Session, client_id, job_key) -> dict:
    row = db.query(AutomationRule).filter(AutomationRule.client_id == client_id, AutomationRule.job_key == job_key).one_or_none()
    return _params(job_key, row)


def schedule_text(job_key, values) -> str:
    job = JOBS[job_key]
    if job["schedule"] == "event":
        return "Straight away, when it happens"
    at = values["run_time"]
    if job["schedule"] == "weekly":
        return f"Every {WEEKDAYS[values['weekday']]} at {at}"
    if job["schedule"] == "monthly":
        return f"Day {values['month_day']} of every month at {at}"
    return f"Every {'working ' if job.get('working_days') else ''}day at {at}"


def next_run(job_key, values, rule_row, cal, now: datetime):
    """When the scheduler will run the job next (None for event jobs or when switched off)."""
    job = JOBS[job_key]
    if job["schedule"] == "event" or not values["enabled"]:
        return None
    hh, mm = (int(x) for x in values["run_time"].split(":"))
    ran_today = rule_row is not None and rule_row.last_run_on is not None and rule_row.last_run_on >= now.date()
    for i in range(400):
        day = now.date() + timedelta(days=i)
        if not _day_matches(job, values, day, cal):
            continue
        at = datetime.combine(day, time(hh, mm))
        if i == 0:
            if ran_today:
                continue
            if at <= now:  # today's time has passed and it has not run yet: the scheduler picks it up within a minute
                return now.replace(second=0, microsecond=0)
        return at
    return None


def _day_matches(job, values, day: date, cal) -> bool:
    if job["schedule"] == "weekly" and day.weekday() != values["weekday"]:
        return False
    if job["schedule"] == "monthly" and day.day != min(values["month_day"], calendar.monthrange(day.year, day.month)[1]):
        return False
    if job.get("working_days") and not cal.is_working(day):
        return False
    return True


def overview(db: Session, principal) -> dict:
    """Settings > Automation: every job with its settings, schedule, last run and next run."""
    rows = _rows(db, principal.client_id)
    cal = work_calendar.for_client(db, principal.client_id)
    now = datetime.now()
    jobs = []
    for key, job in JOBS.items():
        row = rows.get(key)
        values = rule_values(key, row)
        nxt = next_run(key, values, row, cal, now)
        jobs.append({
            "key": key, "group": job["group"], "title": job["title"], "description": job["description"], "schedule": job["schedule"],
            "working_days": bool(job.get("working_days")), "enabled": values["enabled"], "run_time": values["run_time"],
            "weekday": values["weekday"], "month_day": values["month_day"], "params": values["params"],
            "param_fields": [{"key": k, **p} for k, p in job["params"].items()],
            "schedule_text": schedule_text(key, values),
            "next_run_at": nxt.isoformat(timespec="minutes") if nxt else None,
            "last_run_at": utc_iso(row.last_run_at) if row is not None and row.last_run_at else None,
            "last_status": row.last_status if row is not None else None,
            "last_summary": row.last_summary if row is not None else None,
            "updated_by_name": row.updated_by_name if row is not None else None,
        })
    return {"groups": GROUPS, "jobs": jobs, "weekdays": WEEKDAYS, "server_time": now.isoformat(timespec="minutes")}


def save_rule(db: Session, principal, job_key, data: dict) -> None:
    if job_key not in JOBS:
        raise LookupError("This automation does not exist")
    job = JOBS[job_key]
    row = _ensure_rows(db, principal.client_id)[job_key]
    values = rule_values(job_key, row)
    if data.get("enabled") is not None:
        row.enabled = bool(data["enabled"])
    if job["schedule"] != "event":
        if data.get("run_time"):
            row.run_time = data["run_time"]
        if job["schedule"] == "weekly" and data.get("weekday") is not None:
            row.weekday = data["weekday"]
        if job["schedule"] == "monthly" and data.get("month_day") is not None:
            row.month_day = data["month_day"]
    params = dict(values["params"])
    for k, v in (data.get("params") or {}).items():
        spec = job["params"].get(k)
        if spec is None:
            raise AutomationError(f"'{k}' is not a setting of this automation")
        if not isinstance(v, int) or isinstance(v, bool) or not spec["min"] <= v <= spec["max"]:
            raise AutomationError(f"{spec['label']}: enter a whole number from {spec['min']} to {spec['max']}")
        params[k] = v
    if job_key == "approval_reminders" and params["escalate_after_days"] <= params["remind_after_days"]:
        raise AutomationError("Escalate after must be more days than Remind after")
    row.params = json.dumps(params)
    row.updated_by = principal.user_id
    row.updated_by_name = principal.user_name
    db.commit()


def _start_tomorrow(row: AutomationRule, job_key) -> None:
    """A company's first rows: start with the next scheduled time after today, so switching the PMS on (or a new
    company's first visit) does not send every reminder and report at once. "Run now" runs any job at once."""
    if JOBS[job_key]["schedule"] != "event":
        row.last_run_on = date.today()


# ------------------------------------------------------------------------------ run history


def runs(db: Session, principal, job_key=None, limit=50) -> list:
    q = db.query(AutomationRun).filter(AutomationRun.client_id == principal.client_id)
    if job_key:
        q = q.filter(AutomationRun.job_key == job_key)
    return [{"id": r.id, "job_key": r.job_key, "title": JOBS.get(r.job_key, {}).get("title", r.job_key), "trigger": r.trigger, "status": r.status,
             "items": r.items, "summary": r.summary, "started_by_name": r.started_by_name, "started_at": utc_iso(r.started_at),
             "finished_at": utc_iso(r.finished_at) if r.finished_at else None}
            for r in q.order_by(AutomationRun.id.desc()).limit(limit)]


def once(db: Session, client_id, job_key, ref_key) -> bool:
    """True the first time a (job, ref) pair is seen - and remembers it. For alerts that must not repeat."""
    seen = db.query(AutomationSent.id).filter(AutomationSent.client_id == client_id, AutomationSent.job_key == job_key,
                                              AutomationSent.ref_key == ref_key[:120]).first()
    if seen:
        return False
    db.add(AutomationSent(client_id=client_id, job_key=job_key, ref_key=ref_key[:120]))
    return True


def _finish(db: Session, client_id, job_key, trigger, by_name, started, result, failed=None) -> dict:
    items = int(result.get("items", 0)) if result else 0
    status = "Failed" if failed else ("Success" if items else "Nothing to do")
    summary = failed or (result.get("summary") if result else None) or "Nothing needed doing"
    db.add(AutomationRun(client_id=client_id, job_key=job_key, trigger=trigger, status=status, items=items, summary=summary[:2000],
                         started_by_name=by_name, started_at=started, finished_at=_utcnow()))
    if trigger != "Event" or items:
        db.query(AutomationRule).filter(AutomationRule.client_id == client_id, AutomationRule.job_key == job_key).update(
            {AutomationRule.last_run_at: started, AutomationRule.last_status: status, AutomationRule.last_summary: summary[:1000]},
            synchronize_session=False)
    db.commit()
    return {"job_key": job_key, "status": status, "items": items, "summary": summary}


def run_job(db: Session, client_id, job_key, trigger="Manual", by_name=SYSTEM_NAME, today=None) -> dict:
    """Runs one scheduled job for one company now and records the run. today: the day to act as (tests)."""
    from app.repositories import automation_jobs  # local import: the jobs use the repositories this module serves

    if job_key not in JOBS or JOBS[job_key]["schedule"] == "event":
        raise LookupError("This automation does not exist or runs by itself when its event happens")
    _ensure_rows(db, client_id)
    started = _utcnow()
    try:
        result = automation_jobs.RUNNERS[job_key](db, client_id, params_for(db, client_id, job_key), today or date.today())
    except Exception as exc:  # noqa: BLE001 - one failing job is recorded; it never stops the others
        db.rollback()
        logger.exception("Automation %s failed for company %s", job_key, client_id)
        return _finish(db, client_id, job_key, trigger, by_name, started, None, failed=f"Failed: {exc}"[:500])
    return _finish(db, client_id, job_key, trigger, by_name, started, result)


def record_event(db: Session, client_id, job_key, summary, items=1) -> None:
    """Logs what an event job did (the caller's transaction is committed with it)."""
    now = _utcnow()
    db.add(AutomationRun(client_id=client_id, job_key=job_key, trigger="Event", status="Success" if items else "Nothing to do", items=items,
                         summary=summary[:2000], started_by_name=SYSTEM_NAME, started_at=now, finished_at=now))
    db.query(AutomationRule).filter(AutomationRule.client_id == client_id, AutomationRule.job_key == job_key).update(
        {AutomationRule.last_run_at: now, AutomationRule.last_status: "Success", AutomationRule.last_summary: summary[:1000]},
        synchronize_session=False)


# ------------------------------------------------------------------------------ scheduler side


def companies(db: Session) -> list:
    """Every company using the PMS: has projects, settings or users."""
    q = union(
        db.query(Project.client_id).filter(Project.is_deleted == False).distinct().statement,  # noqa: E712
        db.query(CompanySettings.client_id).statement,
        db.query(UserRole.client_id).distinct().statement,
    )
    return sorted({r[0] for r in db.execute(q)})


def _ensure_rows(db: Session, client_id) -> dict:
    rows = _rows(db, client_id)
    missing = [k for k in JOBS if k not in rows]
    if missing:
        for key in missing:
            d = _defaults(key)
            row = AutomationRule(client_id=client_id, job_key=key, enabled=True, run_time=d["run_time"], weekday=d["weekday"],
                                 month_day=d["month_day"], params=json.dumps(d["params"]))
            _start_tomorrow(row, key)
            db.add(row)
        try:
            db.commit()
        except IntegrityError:  # another server wrote them at the same moment
            db.rollback()
        rows = _rows(db, client_id)
    return rows


def due_jobs(db: Session, client_id, now: datetime) -> list:
    rows = _ensure_rows(db, client_id)
    cal = work_calendar.for_client(db, client_id)
    due = []
    for key, job in JOBS.items():
        if job["schedule"] == "event":
            continue
        row = rows.get(key)
        values = rule_values(key, row)
        if not values["enabled"] or (row.last_run_on and row.last_run_on >= now.date()):
            continue
        if now.strftime("%H:%M") < values["run_time"]:
            continue
        if _day_matches(job, values, now.date(), cal):
            due.append(key)
    return due


def claim(db: Session, client_id, job_key, today: date) -> bool:
    """Marks the job as run today; True only for the one caller whose UPDATE changed the row."""
    result = db.execute(
        text("UPDATE projectmanagement.automation_rules SET last_run_on = :d WHERE client_id = :c AND job_key = :k "
             "AND (last_run_on IS NULL OR last_run_on < :d)"),
        {"d": today, "c": client_id, "k": job_key},
    )
    db.commit()
    return result.rowcount == 1


def prune(db: Session) -> None:
    cutoff = _utcnow() - timedelta(days=RUN_HISTORY_DAYS)
    db.query(AutomationRun).filter(AutomationRun.started_at < cutoff).delete(synchronize_session=False)
    db.commit()


def people_with_roles(db: Session, client_id, role_keys) -> list:
    """[(user_id, name)] of active logins with one of these roles."""
    return [(r.user_id, r.user_name) for r in db.query(UserRole).filter(
        UserRole.client_id == client_id, UserRole.is_active == True, UserRole.role.in_(role_keys))]  # noqa: E712


SENIOR_ROLES = (roles.ADMIN, roles.DIRECTOR)
FINANCE_ROLES = (roles.FINANCE,)
