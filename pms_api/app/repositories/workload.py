"""Time-based views of work and people: the task calendar, forward capacity (planned work vs available hours per
week) and backward utilization (logged hours vs available hours).

Working days and hours per day come from the company calendar (Settings: weekdays, hours, holidays), times each
person's allocation % on each project while both the project and their membership are running. A person is keyed like the allocation screen: `u<user_id>` when known,
otherwise `n<lower name>`."""
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.milestones import Milestone
from app.models.projects import Project
from app.models.tasks import Task
from app.models.team import ProjectMember
from app.models.timesheets import TimeEntry
from app.repositories import work_calendar
from app.repositories.team import INACTIVE_PROJECT_STATUSES
from app.core.access import project_scope

MAX_CALENDAR_DAYS = 62
MAX_CAPACITY_WEEKS = 12
MAX_UTILIZATION_DAYS = 92


class WorkloadError(Exception):
    """Bad filters; the message is safe to show to the user."""


class ProjectNotFound(WorkloadError):
    """The project filter names a project the caller cannot see (answered like /projects/{id}: 404)."""


def _d(v):
    return v.isoformat() if v else None


def _num(v):
    return float(v) if v is not None else None


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _person_key(user_id, name):
    return f"u{user_id}" if user_id else f"n{(name or '').strip().lower()}"


def _live_tasks(db, principal):
    return (
        db.query(Task, Project.project_code)
        .join(Project, Project.id == Task.project_id)
        .filter(Task.client_id == principal.client_id, Task.is_deleted == False, Project.is_deleted == False, project_scope(db, principal))  # noqa: E712
    )


def _check_project(db, principal, project_id) -> None:
    """A project filter must name a project the caller can see."""
    if project_id and not (
        db.query(Project.id)
        .filter(Project.id == project_id, Project.client_id == principal.client_id, Project.is_deleted == False, project_scope(db, principal))  # noqa: E712
        .first()
    ):
        raise ProjectNotFound("Project not found")


def _members(db, principal, project_id=None, include_closed=False):
    """Team memberships on projects the caller can see, with the project's dates. Forward-looking views skip
    Closed projects (they no longer hold time); backward-looking ones keep them, so closing a project does not
    change past numbers (its windows end when it was closed, see _member_window)."""
    query = (
        db.query(ProjectMember, Project)
        .join(Project, Project.id == ProjectMember.project_id)
        .filter(ProjectMember.client_id == principal.client_id, ProjectMember.is_deleted == False, Project.is_deleted == False,  # noqa: E712
                project_scope(db, principal))
    )
    if not include_closed:
        query = query.filter(Project.status.notin_(INACTIVE_PROJECT_STATUSES))
    if project_id:
        query = query.filter(Project.id == project_id)
    return query.all()


def _member_window(m: ProjectMember, p: Project):
    """The days a membership holds time: inside both the project's and the member's dates (open ends = unlimited).
    A Closed project stops holding time on the day it was closed (it cannot be edited afterwards)."""
    starts = [d for d in (p.start_date, m.start_date) if d]
    ends = [d for d in (p.end_date, m.end_date) if d]
    if p.status in INACTIVE_PROJECT_STATUSES and p.updated_at:
        ends.append(p.updated_at.date())
    return (max(starts) if starts else date.min), (min(ends) if ends else date.max)


def _people(memberships):
    """{key: {name, roles, projects, memberships[(pct, window)]}} and a name -> key map for tasks assigned by name."""
    people, by_name = {}, {}
    for m, p in memberships:
        key = _person_key(m.user_id, m.member_name)
        person = people.setdefault(key, {"key": key, "user_id": m.user_id, "member_name": m.member_name, "roles": [], "projects": [], "windows": []})
        if m.role not in person["roles"]:
            person["roles"].append(m.role)
        person["projects"].append({"project_id": p.id, "project_code": p.project_code, "allocation_pct": m.allocation_pct})
        person["windows"].append((m.allocation_pct, *_member_window(m, p)))
        by_name[m.member_name.strip().lower()] = key
    return people, by_name


def _available(cal, person, start: date, end: date) -> float:
    """Hours the person's allocations give between start and end (inclusive)."""
    total = 0.0
    for pct, w_start, w_end in person["windows"]:
        if pct:
            total += cal.count(max(start, w_start), min(end, w_end)) * cal.hours_per_day * pct / 100
    return round(total, 2)


def _task_person(task, people, by_name):
    if task.assignee_id and f"u{task.assignee_id}" in people:
        return f"u{task.assignee_id}"
    if task.assignee_name:
        return by_name.get(task.assignee_name.strip().lower())
    return None


# ------------------------------------------------------------------------------ calendar


def calendar(db: Session, principal, start: date, end: date, project_id=None, mine=False, assignee=None, include_done=True) -> dict:
    if end < start:
        raise WorkloadError("To date cannot be before From date")
    if (end - start).days + 1 > MAX_CALENDAR_DAYS:
        raise WorkloadError(f"The calendar shows at most {MAX_CALENDAR_DAYS} days at a time")
    today = date.today()

    query = _live_tasks(db, principal)
    if project_id:
        query = query.filter(Task.project_id == project_id)
    if mine:
        query = query.filter(Task.assignee_id == principal.user_id) if principal.user_id else query.filter(Task.id == -1)
    if assignee:
        query = query.filter(Task.assignee_name == assignee)
    if not include_done:
        query = query.filter(Task.status != "Done")

    # A task with only one date sits on that day; a task with both spans start -> due.
    dated = query.filter(or_(Task.start_date != None, Task.due_date != None))  # noqa: E711
    rows = []
    for t, code in dated.all():
        first, last = t.start_date or t.due_date, t.due_date or t.start_date
        if first > end or last < start:
            continue
        rows.append({
            "id": t.id, "task_key": t.task_key, "title": t.title, "project_id": t.project_id, "project_code": code,
            "status": t.status, "priority": t.priority, "assignee_name": t.assignee_name, "parent_task_id": t.parent_task_id,
            "start_date": _d(t.start_date), "due_date": _d(t.due_date), "estimated_hours": _num(t.estimated_hours),
            "is_overdue": bool(t.due_date and t.due_date < today and t.status != "Done"),
        })
    rows.sort(key=lambda r: (r["start_date"] or r["due_date"], r["due_date"] or "", r["task_key"]))

    undated = query.filter(Task.start_date == None, Task.due_date == None, Task.status != "Done").count()  # noqa: E711

    ms_query = (
        db.query(Milestone, Project.project_code)
        .join(Project, Project.id == Milestone.project_id)
        .filter(Milestone.client_id == principal.client_id, Milestone.is_deleted == False, Project.is_deleted == False, project_scope(db, principal),  # noqa: E712
                Milestone.due_date >= start, Milestone.due_date <= end)
    )
    if project_id:
        ms_query = ms_query.filter(Milestone.project_id == project_id)
    milestones = [{"id": m.id, "name": m.name, "project_id": m.project_id, "project_code": code, "due_date": _d(m.due_date), "status": m.status}
                  for m, code in ms_query.order_by(Milestone.due_date).all()]

    return {"tasks": rows, "milestones": milestones, "undated": undated, "range": {"from": _d(start), "to": _d(end)}, "today": _d(today)}


# ------------------------------------------------------------------------------ capacity


def capacity(db: Session, principal, start=None, weeks=8, project_id=None) -> dict:
    """Per person and week: hours available (allocations) vs hours of open work planned (remaining estimates
    spread evenly over each task's working days). Overdue work lands in the current week."""
    if not 1 <= weeks <= MAX_CAPACITY_WEEKS:
        raise WorkloadError(f"Pick between 1 and {MAX_CAPACITY_WEEKS} weeks")
    today = date.today()
    first = _monday(start or today)
    week_starts = [first + timedelta(weeks=i) for i in range(weeks)]
    last = week_starts[-1] + timedelta(days=6)

    _check_project(db, principal, project_id)
    cal = work_calendar.for_client(db, principal.client_id)
    people, by_name = _people(_members(db, principal, project_id))
    for p in people.values():
        p["weeks"] = [{"available": _available(cal, p, w, w + timedelta(days=6)), "planned": 0.0} for w in week_starts]
        p["tasks"], p["unscheduled_hours"], p["unestimated"] = [], 0.0, 0

    # Open work of Closed projects no longer needs anyone's time.
    query = _live_tasks(db, principal).filter(Task.status != "Done", Project.status.notin_(INACTIVE_PROJECT_STATUSES))
    if project_id:
        query = query.filter(Task.project_id == project_id)
    unassigned = {"count": 0, "hours": 0.0}
    for t, code in query.all():
        remaining = max(0.0, (_num(t.estimated_hours) or 0) - (_num(t.actual_hours) or 0))
        key = _task_person(t, people, by_name)
        person = people.get(key) if key else None
        if person is None:
            unassigned["count"] += 1
            unassigned["hours"] += remaining
            continue
        if not t.estimated_hours:
            person["unestimated"] += 1
            continue
        if not remaining:
            continue
        if not t.due_date:
            person["unscheduled_hours"] += remaining
            continue
        # Spread the remaining hours over the task's working days from today (overdue -> all today).
        window_start = max(t.start_date or today, today)
        days = cal.days(window_start, t.due_date) if t.due_date >= today else [today]
        if not days:
            days = [t.due_date if t.due_date >= today else today]
        per_day = remaining / len(days)
        split = defaultdict(float)
        for day in days:
            idx = (_monday(day) - first).days // 7
            if 0 <= idx < weeks:
                split[idx] += per_day
        if not split:
            continue
        for idx, hours in split.items():
            person["weeks"][idx]["planned"] += hours
        person["tasks"].append({
            "id": t.id, "task_key": t.task_key, "title": t.title, "project_code": code, "status": t.status, "priority": t.priority,
            "due_date": _d(t.due_date), "remaining": round(remaining, 2), "is_overdue": t.due_date < today,
            "weeks": {str(i): round(h, 2) for i, h in split.items()},
        })

    rows = []
    for p in people.values():
        total_available = total_planned = 0.0
        for w in p["weeks"]:
            w["planned"] = round(w["planned"], 2)
            w["load_pct"] = round(w["planned"] / w["available"] * 100) if w["available"] else (None if not w["planned"] else 999)
            w["state"] = _state(w["available"], w["planned"])
            total_available += w["available"]
            total_planned += w["planned"]
        p["tasks"].sort(key=lambda t: (t["due_date"] or "9999", t["task_key"]))
        rows.append({
            "key": p["key"], "member_name": p["member_name"], "roles": p["roles"], "projects": p["projects"],
            "allocation": sum(pr["allocation_pct"] for pr in p["projects"]), "weeks": p["weeks"], "tasks": p["tasks"],
            "available": round(total_available, 2), "planned": round(total_planned, 2),
            "load_pct": round(total_planned / total_available * 100) if total_available else None,
            "over_weeks": sum(1 for w in p["weeks"] if w["state"] == "Over"),
            "unscheduled_hours": round(p["unscheduled_hours"], 2), "unestimated": p["unestimated"],
        })
    rows.sort(key=lambda r: (-r["over_weeks"], -(r["load_pct"] or 0), r["member_name"].lower()))
    return {
        "weeks": [{"index": i, "start": _d(w), "end": _d(w + timedelta(days=6)), "is_current": w <= today <= w + timedelta(days=6)} for i, w in enumerate(week_starts)],
        "people": rows,
        "unassigned": {"count": unassigned["count"], "hours": round(unassigned["hours"], 2)},
        "range": {"from": _d(first), "to": _d(last), "hours_per_day": cal.hours_per_day},
        "summary": {
            "people": len(rows), "available": round(sum(r["available"] for r in rows), 2), "planned": round(sum(r["planned"] for r in rows), 2),
            "overloaded": sum(1 for r in rows if r["over_weeks"]),
        },
    }


def suggest_assignees(db: Session, principal, project_id, start=None, due=None, hours=None) -> dict:
    """Who on the project's team has the most free time for a task (start..due; two weeks when undated).

    Free time = hours their allocations give minus open work already planned for them, counted across every
    project (not only the ones the caller sees), so a person busy elsewhere is not suggested."""
    from app.repositories.automation import system_principal  # local import: automation reads this module's neighbours

    _check_project(db, principal, project_id)
    today = date.today()
    first = max(start or today, today)
    last = due if due and due >= first else first + timedelta(days=13)
    weeks = max(1, min(MAX_CAPACITY_WEEKS, (_monday(last) - _monday(today)).days // 7 + 1))
    cal = work_calendar.for_client(db, principal.client_id)
    cap = capacity(db, system_principal(principal.client_id), start=today, weeks=weeks)
    load = {r["key"]: r for r in cap["people"]}
    share = []
    for w in cap["weeks"]:
        ws, we = date.fromisoformat(w["start"]), date.fromisoformat(w["end"])
        all_days = cal.count(ws, we)
        share.append(cal.count(max(ws, first), min(we, last)) / all_days if all_days else 0)
    team = (
        db.query(ProjectMember)
        .filter(ProjectMember.project_id == project_id, ProjectMember.client_id == principal.client_id, ProjectMember.is_deleted == False)  # noqa: E712
        .all()
    )
    open_tasks = defaultdict(int)
    for t, _ in _live_tasks(db, system_principal(principal.client_id)).filter(Task.status != "Done"):
        open_tasks[f"u{t.assignee_id}" if t.assignee_id else f"n{(t.assignee_name or '').strip().lower()}"] += 1
    people = []
    for m in team:
        key = _person_key(m.user_id, m.member_name)
        row = load.get(key)
        available = planned = 0.0
        if row:
            for i, w in enumerate(row["weeks"]):
                available += w["available"] * share[i]
                planned += w["planned"] * share[i]
        free = max(0.0, available - planned)
        people.append({
            "member_id": m.id, "user_id": m.user_id, "member_name": m.member_name, "role": m.role,
            "free_hours": round(free, 1), "available_hours": round(available, 1), "planned_hours": round(planned, 1),
            "load_pct": round(planned / available * 100) if available else None,
            "open_tasks": open_tasks[key], "fits": hours is None or free >= float(hours),
        })
    people.sort(key=lambda p: (-p["free_hours"], p["open_tasks"], p["member_name"].lower()))
    return {"from": _d(first), "to": _d(last), "hours": float(hours) if hours is not None else None, "people": people}


def _state(available, planned):
    if not available:
        return "Over" if planned else "None"
    pct = planned / available * 100
    return "Over" if pct > 100 else "Busy" if pct >= 85 else "OK" if pct >= 40 else "Free"


# ------------------------------------------------------------------------------ utilization


def utilization(db: Session, principal, start=None, end=None, project_id=None, person=None) -> dict:
    """Per person and week: available hours (allocations), logged hours (approved / waiting approval) and how
    much of the approved time is billable (non-Internal projects)."""
    today = date.today()
    start = start or _monday(today) - timedelta(weeks=3)
    end = end or today
    if end < start:
        raise WorkloadError("To date cannot be before From date")
    if (end - start).days + 1 > MAX_UTILIZATION_DAYS:
        raise WorkloadError(f"Pick at most {MAX_UTILIZATION_DAYS} days here (Reports > Resource Utilization covers longer periods)")

    first = _monday(start)
    week_starts = []
    w = first
    while w <= end:
        week_starts.append(w)
        w += timedelta(weeks=1)

    _check_project(db, principal, project_id)
    cal = work_calendar.for_client(db, principal.client_id)
    # Closed projects count only for the days they were still running inside this period.
    memberships = [(m, p) for m, p in _members(db, principal, project_id, include_closed=True)
                   if p.status not in INACTIVE_PROJECT_STATUSES or (_member_window(m, p)[0] <= end and _member_window(m, p)[1] >= start)]
    people, by_name = _people(memberships)
    for p in people.values():
        p["weeks"] = [{"available": _available(cal, p, max(ws, start), min(ws + timedelta(days=6), end)), "approved": 0.0, "pending": 0.0} for ws in week_starts]
        p["approved"] = p["pending"] = p["billable"] = 0.0

    entries = (
        db.query(TimeEntry.user_id, TimeEntry.member_name, TimeEntry.work_date, TimeEntry.hours, TimeEntry.status, Project.project_type)
        .join(Task, Task.id == TimeEntry.task_id)
        .join(Project, Project.id == TimeEntry.project_id)
        .filter(TimeEntry.client_id == principal.client_id, TimeEntry.is_deleted == False, Task.is_deleted == False, Project.is_deleted == False,  # noqa: E712
                project_scope(db, principal), TimeEntry.status.in_(("Approved", "Submitted")), TimeEntry.work_date >= start, TimeEntry.work_date <= end)
    )
    if project_id:
        entries = entries.filter(TimeEntry.project_id == project_id)
    for uid, name, work_date, hours, status, ptype in entries:
        key = _person_key(uid, name)
        if key not in people:
            key = by_name.get((name or "").strip().lower())
        p = people.get(key) if key else None
        if p is None:
            continue
        idx = (_monday(work_date) - first).days // 7
        h = float(hours)
        if status == "Approved":
            p["approved"] += h
            p["weeks"][idx]["approved"] += h
            if ptype != "Internal":
                p["billable"] += h
        else:
            p["pending"] += h
            p["weeks"][idx]["pending"] += h

    full_time = cal.count(start, end) * cal.hours_per_day
    rows = []
    for p in people.values():
        if person and person.lower() not in p["member_name"].lower():
            continue
        available = round(sum(w["available"] for w in p["weeks"]), 2)
        for w in p["weeks"]:
            w["approved"], w["pending"] = round(w["approved"], 2), round(w["pending"], 2)
            w["pct"] = round(w["approved"] / w["available"] * 100) if w["available"] else None
        rows.append({
            "key": p["key"], "member_name": p["member_name"], "roles": p["roles"], "projects": p["projects"],
            "allocation": sum(pr["allocation_pct"] for pr in p["projects"]), "weeks": p["weeks"],
            "available": available, "approved": round(p["approved"], 2), "pending": round(p["pending"], 2), "billable": round(p["billable"], 2),
            "utilization": round(p["approved"] / available * 100, 1) if available else None,
            "billable_pct": round(p["billable"] / p["approved"] * 100, 1) if p["approved"] else None,
            "of_full_time": round(p["approved"] / full_time * 100, 1) if full_time else None,
        })
    rows.sort(key=lambda r: (r["utilization"] is None, -(r["utilization"] or 0), r["member_name"].lower()))
    with_plan = [r for r in rows if r["utilization"] is not None]
    approved = sum(r["approved"] for r in rows)
    return {
        "weeks": [{"index": i, "start": _d(max(ws, start)), "end": _d(min(ws + timedelta(days=6), end))} for i, ws in enumerate(week_starts)],
        "people": rows,
        "range": {"from": _d(start), "to": _d(end), "working_days": cal.count(start, end), "hours_per_day": cal.hours_per_day},
        "summary": {
            "people": len(rows),
            "available": round(sum(r["available"] for r in rows), 2),
            "approved": round(approved, 2),
            "pending": round(sum(r["pending"] for r in rows), 2),
            "average": round(sum(r["utilization"] for r in with_plan) / len(with_plan), 1) if with_plan else None,
            "billable_pct": round(sum(r["billable"] for r in rows) / approved * 100, 1) if approved else None,
            "under": sum(1 for r in with_plan if r["utilization"] < 60),
            "over": sum(1 for r in with_plan if r["utilization"] > 100),
        },
    }
