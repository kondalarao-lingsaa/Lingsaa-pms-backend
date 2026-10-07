"""Planning views built from tasks, dependencies and milestones: Gantt timeline, WBS, roadmap, dependency list."""
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models.milestones import Milestone
from app.models.projects import Project
from app.models.tasks import Task, TaskDependency
from app.repositories import projects as project_repo
from app.repositories import work_calendar
from app.repositories.task_activity import log_activity
from app.core.access import project_scope

STATUS_PROGRESS = {"To Do": 0, "In Progress": 50, "Testing": 80, "Done": 100}


class PlanningError(Exception):
    """A scheduling rule was broken; the message is safe to show to the user."""


def _d(v):
    return v.isoformat() if v else None


def _fmt(v):
    return v.strftime("%d %b %Y")


def _tasks(db, project_id):
    return db.query(Task).filter(Task.project_id == project_id, Task.is_deleted == False).order_by(Task.id).all()  # noqa: E712


def _dependencies(db, task_ids):
    if not task_ids:
        return []
    return db.query(TaskDependency).filter(TaskDependency.task_id.in_(task_ids), TaskDependency.depends_on_id.in_(task_ids)).all()


def _critical_path(tasks, deps, cal=None) -> list:
    """Dated tasks that decide when the plan ends, from their real dates: the task(s) due last, then, walking back
    through the dependencies, every blocker due right before its waiting task starts (no working day in between).
    Delaying any of them delays the end."""
    dated = {t.id: t for t in tasks if t.start_date and t.due_date}
    if not dated:
        return []
    preds = defaultdict(list)
    for d in deps:
        if d.task_id in dated and d.depends_on_id in dated:
            preds[d.task_id].append(d.depends_on_id)

    def no_slack(blocker, task):
        day_before = task.start_date - timedelta(days=1)
        if blocker.due_date >= day_before:
            return True
        return cal is not None and cal.count(blocker.due_date + timedelta(days=1), day_before) == 0

    end = max(t.due_date for t in dated.values())
    critical, frontier = set(), [tid for tid, t in dated.items() if t.due_date == end]
    while frontier:
        tid = frontier.pop()
        if tid in critical:  # also guards against loops (refused when links are added)
            continue
        critical.add(tid)
        frontier.extend(p for p in preds[tid] if no_slack(dated[p], dated[tid]))
    return sorted(critical, key=lambda i: (dated[i].start_date, dated[i].due_date, i))


def _warnings(project, tasks, deps, milestones, by_id):
    today = date.today()
    warnings = []
    for d in deps:
        task, blocker = by_id.get(d.task_id), by_id.get(d.depends_on_id)
        if task and blocker and task.start_date and blocker.due_date and task.start_date <= blocker.due_date and task.status != "Done":
            warnings.append({"type": "dependency", "task_id": task.id,
                             "message": f"{task.task_key} starts {_fmt(task.start_date)}, before its blocker {blocker.task_key} is due ({_fmt(blocker.due_date)})"})
    for t in tasks:
        if project.start_date and t.start_date and t.start_date < project.start_date:
            warnings.append({"type": "range", "task_id": t.id, "message": f"{t.task_key} starts before the project ({_fmt(project.start_date)})"})
        if project.end_date and t.due_date and t.due_date > project.end_date:
            warnings.append({"type": "range", "task_id": t.id, "message": f"{t.task_key} is due after the project ends ({_fmt(project.end_date)})"})
        if t.due_date and t.due_date < today and t.status != "Done":
            warnings.append({"type": "overdue", "task_id": t.id, "message": f"{t.task_key} was due {_fmt(t.due_date)} and is {t.status}"})
    for m in milestones:
        late = [t for t in tasks if t.milestone_id == m.id and t.due_date and m.due_date and t.due_date > m.due_date]
        if late:
            warnings.append({"type": "milestone", "milestone_id": m.id,
                             "message": f"Milestone '{m.name}' is due {_fmt(m.due_date)} but {len(late)} of its tasks {'are' if len(late) > 1 else 'is'} due later"})
    undated = [t for t in tasks if not (t.start_date and t.due_date)]
    if undated:
        warnings.append({"type": "undated", "message": f"{len(undated)} task{'s have' if len(undated) > 1 else ' has'} no start or due date, so they are not on the timeline"})
    return warnings


def project_timeline(db: Session, principal, project) -> dict:
    tasks = _tasks(db, project.id)
    by_id = {t.id: t for t in tasks}
    deps = _dependencies(db, list(by_id))
    milestones = db.query(Milestone).filter(Milestone.project_id == project.id, Milestone.is_deleted == False).order_by(Milestone.due_date).all()  # noqa: E712
    critical = _critical_path(tasks, deps, work_calendar.for_client(db, project.client_id))

    dates = [d for t in tasks for d in (t.start_date, t.due_date) if d] + [m.due_date for m in milestones if m.due_date]
    dates += [d for d in (project.start_date, project.end_date) if d]
    start = min(dates) if dates else date.today()
    end = max(dates) if dates else date.today() + timedelta(days=30)

    # Main tasks first, each followed by its subtasks (the WBS order).
    children = defaultdict(list)
    for t in tasks:
        children[t.parent_task_id].append(t)
    ordered = []
    for parent in sorted(children[None], key=lambda t: (t.start_date or date.max, t.id)):
        ordered.append(parent)
        ordered.extend(sorted(children[parent.id], key=lambda t: (t.start_date or date.max, t.id)))
    ordered += [t for t in tasks if t not in ordered]  # orphaned subtasks (parent deleted)

    return {
        "project": {"id": project.id, "code": project.project_code, "name": project.project_name, "status": project.status,
                    "start": _d(project.start_date), "end": _d(project.end_date)},
        "range": {"start": _d(start), "end": _d(end)},
        "today": _d(date.today()),
        "tasks": [
            {"id": t.id, "key": t.task_key, "title": t.title, "status": t.status, "priority": t.priority, "type": t.task_type,
             "assignee": t.assignee_name, "start": _d(t.start_date), "due": _d(t.due_date), "parent_id": t.parent_task_id,
             "milestone_id": t.milestone_id, "progress": STATUS_PROGRESS.get(t.status, 0),
             "estimated_hours": float(t.estimated_hours) if t.estimated_hours is not None else None,
             "actual_hours": float(t.actual_hours) if t.actual_hours is not None else None,
             "is_overdue": bool(t.due_date and t.due_date < date.today() and t.status != "Done"), "is_critical": t.id in critical}
            for t in ordered
        ],
        "dependencies": [{"id": d.id, "from": d.depends_on_id, "to": d.task_id} for d in deps],
        "milestones": [{"id": m.id, "name": m.name, "due": _d(m.due_date), "status": m.status, "amount": float(m.amount) if m.amount is not None else None} for m in milestones],
        "critical_path": critical,
        "warnings": _warnings(project, tasks, deps, milestones, by_id),
    }


def check_dates(db: Session, project: Project, task_key: str, start, due, task_id=None, status=None) -> None:
    """The scheduling rules every date change follows (timeline drag, calendar, task create and edit): inside the
    project's dates, after open blockers are due and before the tasks waiting for this one start. A task with
    only one date is treated as starting and ending on it. task_id is None for a task not saved yet (no links)."""
    if not start and not due:
        return
    start, due = start or due, due or start
    if due < start:
        raise PlanningError("The due date cannot be before the start date")
    if project.start_date and start < project.start_date:
        raise PlanningError(f"{task_key} cannot start before the project starts ({_fmt(project.start_date)})")
    if project.end_date and due > project.end_date:
        raise PlanningError(f"{task_key} cannot be due after the project ends ({_fmt(project.end_date)}). Raise a change request to extend the project")
    if task_id is None:
        return
    live = Task.is_deleted == False  # noqa: E712
    blockers = db.query(Task).join(TaskDependency, TaskDependency.depends_on_id == Task.id).filter(TaskDependency.task_id == task_id, live).all()
    late_blockers = [b for b in blockers if b.due_date and start <= b.due_date and b.status != "Done"]
    if late_blockers and status != "Done":
        b = max(late_blockers, key=lambda b: b.due_date)
        raise PlanningError(f"{task_key} waits for {b.task_key} (due {_fmt(b.due_date)}), so it can start from {_fmt(b.due_date + timedelta(days=1))}")
    waiting = db.query(Task).join(TaskDependency, TaskDependency.task_id == Task.id).filter(TaskDependency.depends_on_id == task_id, live).all()
    pushed = [w for w in waiting if w.start_date and w.start_date <= due and w.status != "Done"]
    if pushed:
        w = min(pushed, key=lambda w: w.start_date)
        raise PlanningError(f"{w.task_key} waits for {task_key} and starts {_fmt(w.start_date)}, so {task_key} must be due by {_fmt(w.start_date - timedelta(days=1))}. Move {w.task_key} first")


def reschedule(db: Session, principal, task: Task, new_start, due: date) -> Task:
    """New dates for a task (dragged on the timeline or calendar), checked against the project and its dependencies.
    new_start may be None for a task that only has a due date; the checks then treat the due date as its start."""
    project = db.query(Project).filter(Project.id == task.project_id).one()
    if project.status == "Closed":
        raise PlanningError(f"{project.project_code} is Closed, so its plan can no longer change")
    check_dates(db, project, task.task_key, new_start, due, task_id=task.id, status=task.status)

    if task.start_date == new_start and task.due_date == due:
        return task
    log_activity(db, principal, task.id, "updated", f"Rescheduled: {_d(task.start_date) or '-'} - {_d(task.due_date) or '-'} -> {_d(new_start) or '-'} - {_d(due)}")
    task.start_date, task.due_date = new_start, due
    task.updated_by = principal.user_id
    db.commit()
    db.refresh(task)
    return task


def roadmap(db: Session, principal) -> dict:
    """Every project as a bar (start - end, progress) with its milestones - the portfolio roadmap."""
    today = date.today()
    projects = project_repo.all_projects(db, principal)
    progress = project_repo.progress_for(db, [p.id for p in projects])
    ids = [p.id for p in projects] or [-1]
    milestones = defaultdict(list)
    for m in db.query(Milestone).filter(Milestone.project_id.in_(ids), Milestone.is_deleted == False).order_by(Milestone.due_date):  # noqa: E712
        milestones[m.project_id].append({"id": m.id, "name": m.name, "due": _d(m.due_date), "status": m.status})
    rows = [
        {"id": p.id, "code": p.project_code, "name": p.project_name, "status": p.status, "manager": p.project_manager_name,
         "start": _d(p.start_date), "end": _d(p.end_date), "progress": progress.get(p.id, {}).get("progress", 0),
         "is_late": bool(p.end_date and p.end_date < today and p.status != "Closed"), "milestones": milestones[p.id]}
        for p in projects
    ]
    rows.sort(key=lambda r: (r["status"] == "Closed", r["start"] or "9999"))
    dates = [d for r in rows for d in (r["start"], r["end"]) if d] + [m["due"] for r in rows for m in r["milestones"] if m["due"]]
    return {
        "projects": rows,
        "range": {"start": min(dates) if dates else _d(today), "end": max(dates) if dates else _d(today + timedelta(days=90))},
        "today": _d(today),
        "undated": sum(1 for r in rows if not (r["start"] and r["end"])),
    }


def all_dependencies(db: Session, principal, project_id=None) -> list:
    """Every task link, with the ones that break the plan flagged."""
    live_projects = db.query(Project.id).filter(Project.client_id == principal.client_id, Project.is_deleted == False, project_scope(db, principal))  # noqa: E712
    if project_id:
        live_projects = live_projects.filter(Project.id == project_id)
    tasks = {t.id: t for t in db.query(Task).filter(Task.project_id.in_(live_projects), Task.is_deleted == False)}  # noqa: E712
    codes = dict(db.query(Project.id, Project.project_code).filter(Project.id.in_({t.project_id for t in tasks.values()} or {-1})).all())
    rows = []
    for d in _dependencies(db, list(tasks)):
        task, blocker = tasks[d.task_id], tasks[d.depends_on_id]
        problem = None
        if task.status != "Done" and task.start_date and blocker.due_date and task.start_date <= blocker.due_date:
            problem = "Starts before its blocker is due"
        elif task.status in ("In Progress", "Testing") and blocker.status != "Done":
            problem = "Work started while the blocker is not done"
        rows.append({
            "id": d.id, "project_id": task.project_id, "project_code": codes.get(task.project_id),
            "task": {"id": task.id, "key": task.task_key, "title": task.title, "status": task.status, "start": _d(task.start_date)},
            "blocker": {"id": blocker.id, "key": blocker.task_key, "title": blocker.title, "status": blocker.status, "due": _d(blocker.due_date)},
            "problem": problem, "is_waiting": blocker.status != "Done",
        })
    return sorted(rows, key=lambda r: (r["problem"] is None, not r["is_waiting"], r["project_code"] or "", r["task"]["key"]))
