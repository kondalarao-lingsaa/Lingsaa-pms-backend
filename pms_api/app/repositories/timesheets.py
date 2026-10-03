"""Timesheets (hours per task per day), their approval, and the project budget built from approved hours."""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.projects import Project
from app.models.tasks import Task
from app.models.team import ProjectMember
from app.models.timesheets import EDITABLE_STATUSES, TimeEntry
from app.repositories import notifications as notification_repo
from app.repositories import project_settings as project_settings_repo
from app.repositories.billing import project_revenue
from app.repositories.task_activity import log_activity
from app.schemas.timesheets import MAX_HOURS_PER_DAY, entry_out
from app.core.access import project_scope

# Only running projects accept new time.
LOGGABLE_PROJECT_STATUSES = ("Active",)


class TimesheetError(Exception):
    """A timesheet rule was broken; the message is safe to show to the user."""


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def week_start_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _entries(db: Session, principal):
    """Live entries of live tasks in live projects - hours on a deleted task or project no longer count anywhere."""
    live_task = db.query(Task.id).join(Project, Project.id == Task.project_id).filter(
        Task.is_deleted == False, Project.is_deleted == False, project_scope(db, principal)  # noqa: E712
    )
    return db.query(TimeEntry).filter(
        TimeEntry.client_id == principal.client_id,
        TimeEntry.is_deleted == False,  # noqa: E712
        TimeEntry.task_id.in_(live_task),
    )


def _my_memberships(db, principal):
    """(member, project) pairs where the logged-in user is on the team."""
    if not principal.user_id:
        return []
    return (
        db.query(ProjectMember, Project)
        .join(Project, Project.id == ProjectMember.project_id)
        .filter(
            ProjectMember.client_id == principal.client_id,
            ProjectMember.user_id == principal.user_id,
            ProjectMember.is_deleted == False,  # noqa: E712
            Project.is_deleted == False,  # noqa: E712
        )
        .all()
    )


def _week_status(statuses) -> str:
    if not statuses:
        return "Empty"
    if "Rejected" in statuses:
        return "Rejected"
    if "Draft" in statuses:
        return "Draft"
    if "Submitted" in statuses:
        return "Submitted"
    return "Approved"


def my_week(db, principal, week_start: date) -> dict:
    week_end = week_start + timedelta(days=6)
    days = [(week_start + timedelta(days=i)).isoformat() for i in range(7)]
    memberships = _my_memberships(db, principal)
    member_by_project = {m.project_id: m for m, _ in memberships}

    entries = (
        _entries(db, principal)
        .filter(TimeEntry.user_id == principal.user_id, TimeEntry.work_date >= week_start, TimeEntry.work_date <= week_end)
        .all()
        if principal.user_id
        else []
    )
    task_ids = {e.task_id for e in entries}

    # Tasks I can log on: open tasks of Active projects I am a member of (mine first), plus anything already logged.
    loggable_projects = [p.id for m, p in memberships if p.status in LOGGABLE_PROJECT_STATUSES]
    task_rows = []
    if loggable_projects or task_ids:
        task_rows = (
            db.query(Task, Project.project_code, Project.project_name, Project.status)
            .join(Project, Project.id == Task.project_id)
            .filter(Task.client_id == principal.client_id, Task.is_deleted == False, Project.is_deleted == False)  # noqa: E712
            .filter(or_(Task.id.in_(task_ids or [-1]), (Task.project_id.in_(loggable_projects or [-1])) & (Task.status != "Done")))
            .order_by(Project.project_code, Task.task_key)
            .all()
        )

    def task_brief(t, code, name, status):
        member = member_by_project.get(t.project_id)
        mine = bool(member and ((t.assignee_id and t.assignee_id == principal.user_id) or (t.assignee_name or "").lower() == member.member_name.lower()))
        return {"task_id": t.id, "task_key": t.task_key, "title": t.title, "task_status": t.status, "project_id": t.project_id,
                "project_code": code, "project_name": name, "project_status": status, "assigned_to_me": mine,
                "can_log": status in LOGGABLE_PROJECT_STATUSES and t.project_id in member_by_project}

    briefs = {t.id: task_brief(t, c, n, s) for t, c, n, s in task_rows}
    rows = {}
    for e in entries:
        row = rows.setdefault(e.task_id, {**briefs.get(e.task_id, {"task_id": e.task_id}), "cells": {}, "total": 0.0})
        row["cells"][e.work_date.isoformat()] = {"id": e.id, "hours": float(e.hours), "status": e.status, "note": e.note, "reject_reason": e.reject_reason}
        row["total"] += float(e.hours)

    day_totals = {d: 0.0 for d in days}
    for e in entries:
        day_totals[e.work_date.isoformat()] += float(e.hours)

    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "days": days,
        "today": date.today().isoformat(),
        "rows": sorted(rows.values(), key=lambda r: (r.get("project_code") or "", r.get("task_key") or "")),
        "day_totals": day_totals,
        "week_total": sum(day_totals.values()),
        "status": _week_status({e.status for e in entries}),
        "tasks": sorted(briefs.values(), key=lambda b: (not b["assigned_to_me"], b["project_code"], b["task_key"])),
        "is_member": bool(memberships),
    }


def save_entry(db, principal, data: dict):
    """Creates, changes or (hours = 0) clears the logged-in user's hours for one task on one day."""
    if not principal.user_id:
        raise TimesheetError("Your session has no user id, so time cannot be logged")
    task = (
        db.query(Task)
        .join(Project, Project.id == Task.project_id)
        .filter(Task.id == data["task_id"], Task.client_id == principal.client_id, Task.is_deleted == False, Project.is_deleted == False)  # noqa: E712
        .one_or_none()
    )
    if task is None:
        raise LookupError("Task not found")
    project = db.query(Project).filter(Project.id == task.project_id).one()
    member = (
        db.query(ProjectMember)
        .filter(ProjectMember.project_id == project.id, ProjectMember.user_id == principal.user_id, ProjectMember.is_deleted == False)  # noqa: E712
        .first()
    )
    if member is None:
        raise TimesheetError(f"You are not in {project.project_code}'s team, so you cannot log time on its tasks")
    if project.status not in LOGGABLE_PROJECT_STATUSES:
        raise TimesheetError(f"{project.project_code} is {project.status}. Time can only be logged on Active projects")

    day, hours = data["work_date"], data["hours"]
    if day > date.today():
        raise TimesheetError("You cannot log time for a future date")
    if (member.start_date and day < member.start_date) or (member.end_date and day > member.end_date):
        raise TimesheetError(f"{day.strftime('%d %b %Y')} is outside your time on {project.project_code}")
    if project.start_date and day < project.start_date:
        raise TimesheetError(f"{project.project_code} starts on {project.start_date.strftime('%d %b %Y')}")
    lock_days = project_settings_repo.get(db, project.id)["timesheet_lock_days"]
    if lock_days and day < date.today() - timedelta(days=lock_days):
        raise TimesheetError(f"Hours older than {lock_days} days are locked for {project.project_code} (Project Settings). Ask the project manager if a correction is needed")

    entry = (
        _entries(db, principal)
        .filter(TimeEntry.task_id == task.id, TimeEntry.user_id == principal.user_id, TimeEntry.work_date == day)
        .one_or_none()
    )
    if entry is not None and entry.status not in EDITABLE_STATUSES:
        raise TimesheetError(f"Your hours for {day.strftime('%d %b')} on {task.task_key} are {entry.status} and locked")

    others = (
        _entries(db, principal)
        .filter(TimeEntry.user_id == principal.user_id, TimeEntry.work_date == day, TimeEntry.id != (entry.id if entry else -1))
        .with_entities(func.coalesce(func.sum(TimeEntry.hours), 0))
        .scalar()
    )
    if Decimal(others) + hours > MAX_HOURS_PER_DAY:
        raise TimesheetError(f"{day.strftime('%d %b')} would have {float(Decimal(others) + hours):g} hours. A day has at most 24")

    if hours == 0:
        if entry is not None:
            entry.is_deleted = True
            db.commit()
        return None
    if entry is None:
        entry = TimeEntry(client_id=principal.client_id, project_id=project.id, task_id=task.id, member_id=member.id,
                          user_id=principal.user_id, member_name=member.member_name, work_date=day)
        db.add(entry)
    entry.hours = hours
    entry.note = data.get("note")
    entry.status = "Draft"  # an edited rejected entry goes back to Draft until it is submitted again
    db.commit()
    db.refresh(entry)
    return entry


def submit_week(db, principal, week_start: date) -> int:
    entries = (
        _entries(db, principal)
        .filter(
            TimeEntry.user_id == principal.user_id,
            TimeEntry.work_date >= week_start,
            TimeEntry.work_date <= week_start + timedelta(days=6),
            TimeEntry.status.in_(EDITABLE_STATUSES),
        )
        .all()
    )
    if not entries:
        raise TimesheetError("There are no draft or rejected hours in this week to submit")
    now = _utcnow()
    for e in entries:
        e.status = "Submitted"
        e.submitted_at = now
    db.commit()
    return len(entries)


def _with_context(query):
    return query.join(Task, Task.id == TimeEntry.task_id).join(Project, Project.id == TimeEntry.project_id).join(
        ProjectMember, ProjectMember.id == TimeEntry.member_id
    ).filter(Project.is_deleted == False).with_entities(  # noqa: E712
        TimeEntry, Task.task_key, Task.title, Project.project_code, Project.project_name, ProjectMember.hourly_rate
    )


def _serialize(rows):
    return [entry_out(e, task_key=k, task_title=t, project_code=pc, project_name=pn, rate=r) for e, k, t, pc, pn, r in rows]


def list_entries(db, principal, *, page=1, page_size=20, project_id=None, member=None, status=None, date_from=None, date_to=None):
    query = _entries(db, principal)
    if project_id:
        query = query.filter(TimeEntry.project_id == project_id)
    if member:
        query = query.filter(TimeEntry.member_name.ilike(f"%{member}%"))
    if status:
        query = query.filter(TimeEntry.status == status)
    if date_from:
        query = query.filter(TimeEntry.work_date >= date_from)
    if date_to:
        query = query.filter(TimeEntry.work_date <= date_to)

    full = _with_context(query)
    total = full.count()
    all_rows = _serialize(full.all()) if total <= 5000 else []
    totals = {
        "hours": round(sum(r["hours"] for r in all_rows), 2),
        "cost": round(sum(r["cost"] or 0 for r in all_rows), 2),
        "by_status": {s: round(sum(r["hours"] for r in all_rows if r["status"] == s), 2) for s in ("Draft", "Submitted", "Approved", "Rejected")},
    }
    rows = full.order_by(TimeEntry.work_date.desc(), TimeEntry.member_name, TimeEntry.id).offset((page - 1) * page_size).limit(page_size).all()
    return _serialize(rows), total, totals


def approval_queue(db, principal, project_id=None) -> list:
    """Submitted hours grouped per person per week - the unit a manager approves."""
    from app.repositories import approvals  # local import: approvals reads these models

    query = _entries(db, principal).filter(TimeEntry.status == "Submitted")
    managed = approvals.managed_project_ids(db, principal) if getattr(principal, "role_key", None) else None
    if managed is not None:
        query = query.filter(TimeEntry.project_id.in_(managed))
    if project_id:
        query = query.filter(TimeEntry.project_id == project_id)
    rows = _serialize(_with_context(query).order_by(TimeEntry.work_date, TimeEntry.id).all())
    groups = {}
    for r in rows:
        ws = week_start_of(date.fromisoformat(r["work_date"])).isoformat()
        key = f"{r['user_id'] or r['member_name'].lower()}|{ws}"
        g = groups.setdefault(key, {"key": key, "member_name": r["member_name"], "user_id": r["user_id"], "week_start": ws,
                                    "entries": [], "hours": 0.0, "cost": 0.0, "projects": [],
                                    "is_own": bool(principal.user_id and r["user_id"] == principal.user_id)})
        g["entries"].append(r)
        g["hours"] += r["hours"]
        g["cost"] += r["cost"] or 0
        if r["project_code"] not in g["projects"]:
            g["projects"].append(r["project_code"])
    return sorted(groups.values(), key=lambda g: (g["week_start"], g["member_name"].lower()))


def _recompute_actual_hours(db, task_ids):
    """A task's actual hours = its approved timesheet hours."""
    for task_id in task_ids:
        approved = (
            db.query(func.coalesce(func.sum(TimeEntry.hours), 0))
            .filter(TimeEntry.task_id == task_id, TimeEntry.status == "Approved", TimeEntry.is_deleted == False)  # noqa: E712
            .scalar()
        )
        db.query(Task).filter(Task.id == task_id).update({Task.actual_hours: approved}, synchronize_session=False)


def review(db, principal, entry_ids, approve: bool, reason: str = None) -> int:
    entries = _entries(db, principal).filter(TimeEntry.id.in_(entry_ids)).all()
    if len(entries) != len(set(entry_ids)):
        raise LookupError("Some of these timesheet entries were not found")
    not_submitted = [e for e in entries if e.status != "Submitted"]
    if not_submitted:
        raise TimesheetError(f"{len(not_submitted)} of these entries are not waiting for approval any more. Refresh and try again")
    if not principal.user_id:
        raise TimesheetError("Your login has no user id, so it cannot approve or reject. Please sign in again")
    if any(e.user_id == principal.user_id for e in entries):
        raise TimesheetError("You cannot approve or reject your own time. Another manager has to review it")
    from app.repositories import approvals  # local import: approvals reads these models

    try:
        approvals.check_timesheet_authority(db, principal, entries)
    except approvals.ApprovalError as exc:
        raise TimesheetError(str(exc)) from exc

    rates = dict(db.query(ProjectMember.id, ProjectMember.hourly_rate).filter(ProjectMember.id.in_({e.member_id for e in entries})).all())
    now = _utcnow()
    per_task = defaultdict(float)
    for e in entries:
        e.status = "Approved" if approve else "Rejected"
        e.reviewed_by, e.reviewed_by_name, e.reviewed_at = principal.user_id, principal.user_name, now
        if approve:
            e.hourly_rate = rates.get(e.member_id)
            e.reject_reason = None
        else:
            e.reject_reason = reason
        per_task[(e.task_id, e.member_name)] += float(e.hours)

    for (task_id, who), hours in per_task.items():
        log_activity(db, principal, task_id, "time", f"{hours:g} h of {who} {'approved' if approve else 'rejected'}" + ("" if approve else f": {reason}"))

    # The person who logged the hours hears the outcome, once per person.
    reviewer = notification_repo.person_name(principal.user_name) or "Your manager"
    per_person = defaultdict(float)
    for e in entries:
        per_person[(e.user_id, e.member_name)] += float(e.hours)
    for (user_id, name), hours in per_person.items():
        notification_repo.notify(
            db, principal, [(user_id, name)], "timesheet",
            f"{reviewer} {'approved' if approve else 'rejected'} {hours:g} h of your time",
            body=None if approve else f"Reason: {reason}. Fix the entries and submit again.",
            link="timesheets/myTimesheets/",
        )
    db.flush()
    _recompute_actual_hours(db, {e.task_id for e in entries})
    db.commit()
    return len(entries)


# ----------------------------------------------------------------------------- budget


def _revenue(db, project_id, actual_cost) -> dict:
    revenue = project_revenue(db, project_id)
    margin = round(revenue["billed"] - actual_cost, 2)
    return {**revenue, "margin": margin, "margin_pct": round(margin / revenue["billed"] * 100, 1) if revenue["billed"] else None}


def labour_cost(db, project_id) -> float:
    """Cost of a project's approved hours (hours x the rate locked at approval)."""
    value = (
        db.query(func.coalesce(func.sum(TimeEntry.hours * func.coalesce(TimeEntry.hourly_rate, 0)), 0))
        .join(Task, Task.id == TimeEntry.task_id)
        .filter(TimeEntry.project_id == project_id, TimeEntry.status == "Approved", TimeEntry.is_deleted == False, Task.is_deleted == False)  # noqa: E712
        .scalar()
    )
    return round(float(value or 0), 2)


def project_budget(db, principal, project, progress_pct: int) -> dict:
    """Planned budget vs actual cost (approved hours + approved expenses), what is waiting for approval, and where
    the project is heading."""
    from app.repositories import expenses as expense_repo  # local import: expenses imports this module lazily too

    rows = _serialize(_with_context(_entries(db, principal).filter(TimeEntry.project_id == project.id)).all())
    approved = [r for r in rows if r["status"] == "Approved"]
    pending = [r for r in rows if r["status"] in ("Submitted", "Draft")]

    exp = expense_repo.totals(db, project.id)
    alert_pct = project_settings_repo.get(db, project.id)["budget_alert_pct"]
    labour = round(sum(r["cost"] or 0 for r in approved), 2)
    actual_cost = round(labour + exp["approved"], 2)
    pending_cost = round(sum(r["cost"] or 0 for r in pending) + exp["submitted"], 2)
    budget = float(project.budget) if project.budget is not None else None
    # Forecast at completion: if X% of the work cost Y so far, the whole project costs about Y / X%.
    forecast = round(actual_cost / (progress_pct / 100), 2) if progress_pct and actual_cost else None

    tasks = (
        db.query(Task.id, Task.task_key, Task.title, Task.estimated_hours, Task.actual_hours, Task.status)
        .filter(Task.project_id == project.id, Task.is_deleted == False)  # noqa: E712
        .all()
    )
    estimated = sum(float(t.estimated_hours or 0) for t in tasks)
    approved_hours = sum(r["hours"] for r in approved)

    # Health, with the reason shown to the user. Hours past the estimate before the work is done is an early
    # warning that money alone does not show yet (e.g. no rates set, or no progress to forecast from).
    if budget is None:
        health, reason = "No budget", "Set a budget on the project to track spending against it."
    elif actual_cost > budget:
        health, reason = "Over budget", "Approved cost (hours + expenses) is already above the budget."
    elif budget and actual_cost / budget * 100 >= alert_pct:
        health, reason = "At risk", f"{actual_cost / budget * 100:.0f}% of the budget is used (this project alerts at {alert_pct}%)."
    elif forecast is not None and forecast > budget:
        health, reason = "At risk", f"At this rate the project will cost about {forecast:,.0f}, more than its budget."
    elif estimated and approved_hours > estimated and progress_pct < 100:
        health, reason = "At risk", f"{approved_hours:g} h used against an estimate of {estimated:g} h, with {progress_pct}% of the work done."
    else:
        health, reason = "On track", "Spending is in line with the work done."

    by_member = {}
    for r in rows:
        m = by_member.setdefault(r["member_id"], {"member_id": r["member_id"], "member_name": r["member_name"], "hourly_rate": None,
                                                  "approved_hours": 0.0, "pending_hours": 0.0, "cost": 0.0, "unrated_hours": 0.0})
        if r["status"] == "Approved":
            m["approved_hours"] += r["hours"]
            m["cost"] += r["cost"] or 0
            if r["hourly_rate"] is None:
                m["unrated_hours"] += r["hours"]
        elif r["status"] in ("Submitted", "Draft"):
            m["pending_hours"] += r["hours"]
    current_rates = dict(db.query(ProjectMember.id, ProjectMember.hourly_rate).filter(ProjectMember.project_id == project.id).all())
    for m in by_member.values():
        rate = current_rates.get(m["member_id"])
        m["hourly_rate"] = float(rate) if rate is not None else None
        m["cost"] = round(m["cost"], 2)

    today_ws = week_start_of(date.today())
    weeks = [(today_ws - timedelta(weeks=i)) for i in range(7, -1, -1)]
    by_week = {w.isoformat(): {"week_start": w.isoformat(), "hours": 0.0, "cost": 0.0} for w in weeks}
    for r in approved:
        ws = week_start_of(date.fromisoformat(r["work_date"])).isoformat()
        if ws in by_week:
            by_week[ws]["hours"] += r["hours"]
            by_week[ws]["cost"] += r["cost"] or 0

    over_estimate = sorted(
        [{"task_id": t.id, "task_key": t.task_key, "title": t.title, "estimated_hours": float(t.estimated_hours), "actual_hours": float(t.actual_hours or 0), "status": t.status}
         for t in tasks if t.estimated_hours and (t.actual_hours or 0) > t.estimated_hours],
        key=lambda t: t["actual_hours"] - t["estimated_hours"], reverse=True,
    )[:10]

    return {
        "budget": budget,
        "actual_cost": actual_cost,
        "labour_cost": labour,
        "expense_cost": exp["approved"],
        "pending_expenses": exp["submitted"],
        "billable_expenses": exp["billable_approved"],
        "pending_cost": pending_cost,
        "remaining": round(budget - actual_cost, 2) if budget is not None else None,
        "used_pct": round(actual_cost / budget * 100, 1) if budget else None,
        "forecast": forecast,
        "variance": round(budget - forecast, 2) if budget is not None and forecast is not None else None,
        "health": health,
        "health_reason": reason,
        # Income side: billed (issued + paid, before tax) against the cost of approved hours.
        **_revenue(db, project.id, actual_cost),
        "progress": progress_pct,
        "approved_hours": round(sum(r["hours"] for r in approved), 2),
        "pending_hours": round(sum(r["hours"] for r in pending), 2),
        "estimated_hours": round(estimated, 2),
        "unrated_hours": round(sum(m["unrated_hours"] for m in by_member.values()), 2),
        "by_member": sorted(by_member.values(), key=lambda m: -m["cost"]),
        "by_week": list(by_week.values()),
        "over_estimate": over_estimate,
    }
