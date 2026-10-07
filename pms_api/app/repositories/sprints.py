"""Sprints (time-boxed commitments), the product backlog, capacity, burndown and velocity."""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session, aliased

from app.models.projects import Project
from app.models.sprints import MAX_SPRINT_DAYS, Sprint
from app.models.tasks import Task, TaskActivity
from app.models.team import ProjectMember
from app.repositories import work_calendar
from app.repositories import tasks as task_repo
from app.repositories.risks import _next_key
from app.repositories.task_activity import log_activity
from app.schemas.rules import utc_iso
from app.core.access import project_scope

PRIORITY_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


class SprintError(Exception):
    """A sprint rule was broken; the message is safe to show to the user."""


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _fmt(d):
    return d.strftime("%d %b %Y")


def _live(db: Session, principal):
    return db.query(Sprint).join(Project, Project.id == Sprint.project_id).filter(
        Sprint.client_id == principal.client_id, Sprint.is_deleted == False, Project.is_deleted == False, project_scope(db, principal)  # noqa: E712
    )


def get_sprint(db, principal, sprint_id):
    return _live(db, principal).filter(Sprint.id == sprint_id).one_or_none()


def _sprint_tasks(db, sprint_id):
    return db.query(Task).filter(Task.sprint_id == sprint_id, Task.is_deleted == False).all()  # noqa: E712


def capacity_hours(db, cal, project_id, start, end, as_of=None) -> float:
    """Team capacity for the sprint: each member's working days inside the sprint (their From/To dates on the
    project, company calendar) x hours per day x their allocation %. as_of (a completed sprint's completion
    time) counts the team as it was then: members added later are left out, members removed later still count."""
    query = db.query(ProjectMember).filter(ProjectMember.project_id == project_id)
    if as_of:
        query = query.filter(ProjectMember.created_at <= as_of, (ProjectMember.is_deleted == False) | (ProjectMember.updated_at > as_of))  # noqa: E712
    else:
        query = query.filter(ProjectMember.is_deleted == False)  # noqa: E712
    total = 0.0
    for m in query:
        if not m.allocation_pct:
            continue
        days = cal.count(max(start, m.start_date) if m.start_date else start, min(end, m.end_date) if m.end_date else end)
        total += days * cal.hours_per_day * float(m.allocation_pct) / 100
    return round(total, 2)


def sprint_out(db, s) -> dict:
    tasks = _sprint_tasks(db, s.id)
    today = date.today()
    completed = s.status == "Completed"
    # A completed sprint's numbers are the ones frozen when it closed (its unfinished tasks have moved on since).
    committed = float(s.committed_hours or 0) if completed else sum(float(t.estimated_hours or 0) for t in tasks)
    done = float(s.completed_hours or 0) if completed else sum(float(t.estimated_hours or 0) for t in tasks if t.status == "Done")
    cal = work_calendar.for_client(db, s.client_id)
    capacity = capacity_hours(db, cal, s.project_id, s.start_date, s.end_date, as_of=s.completed_at if completed else None)
    by_status = {st: sum(1 for t in tasks if t.status == st) for st in ("To Do", "In Progress", "Testing", "Done")}
    task_total = (s.committed_tasks or 0) if completed else len(tasks)
    task_done = (s.completed_tasks or 0) if completed else by_status["Done"]
    return {
        "id": s.id, "sprint_key": s.sprint_key, "project_id": s.project_id, "name": s.name, "goal": s.goal,
        "start_date": s.start_date.isoformat(), "end_date": s.end_date.isoformat(), "status": s.status,
        "days": (s.end_date - s.start_date).days + 1, "working_days": cal.count(s.start_date, s.end_date),
        "days_left": max(0, (s.end_date - today).days + 1) if s.status == "Active" else None,
        "is_overdue": s.status == "Active" and s.end_date < today,
        "task_count": len(tasks), "by_status": by_status, "unestimated": sum(1 for t in tasks if not t.estimated_hours),
        "committed_hours": round(committed, 2),
        "done_hours": round(done, 2),
        "committed_tasks": task_total,
        "completed_tasks": task_done,
        "capacity_hours": capacity,
        "load_pct": round(committed / capacity * 100) if capacity else None,
        "progress": round(done / committed * 100) if committed else (round(task_done / task_total * 100) if task_total else 0),
        "started_at": utc_iso(s.started_at), "completed_at": utc_iso(s.completed_at),
    }


def list_sprints(db, principal, project_id) -> list:
    rows = _live(db, principal).filter(Sprint.project_id == project_id).order_by(Sprint.start_date, Sprint.id).all()
    return [sprint_out(db, s) for s in rows]


def _lock(db, project_id) -> None:
    """Holds the project row until commit, so two people changing the project's sprints at the same moment
    are checked one after the other (one Active sprint, unique names, no overlaps)."""
    db.execute(text("SELECT id FROM projectmanagement.projects WITH (UPDLOCK, HOLDLOCK) WHERE id = :p"), {"p": project_id})


def _open_project(db, sprint):
    """The sprint's project, locked; a Closed project's sprints are history and no longer change."""
    _lock(db, sprint.project_id)
    db.refresh(sprint)
    project = db.query(Project).filter(Project.id == sprint.project_id).populate_existing().one()
    if project.status == "Closed":
        raise SprintError(f"{project.project_code} is Closed, so its sprints can no longer change")
    return project


def _check(db, principal, project, data, own_id=None):
    if project.status == "Closed":
        raise SprintError(f"{project.project_code} is Closed")
    start, end = data["start_date"], data["end_date"]
    if end < start:
        raise SprintError("The end date cannot be before the start date")
    if (end - start).days + 1 > MAX_SPRINT_DAYS:
        raise SprintError(f"A sprint lasts at most {MAX_SPRINT_DAYS} days (4 weeks)")
    if project.start_date and start < project.start_date:
        raise SprintError(f"The sprint cannot start before the project ({_fmt(project.start_date)})")
    if project.end_date and end > project.end_date:
        raise SprintError(f"The sprint cannot end after the project ({_fmt(project.end_date)})")
    others = _live(db, principal).filter(Sprint.project_id == project.id)
    if own_id:
        others = others.filter(Sprint.id != own_id)
    for o in others:
        if o.name.lower() == data["name"].lower():
            raise SprintError(f"A sprint named '{data['name']}' already exists in this project")
        if start <= o.end_date and end >= o.start_date:
            raise SprintError(f"The dates overlap {o.name} ({_fmt(o.start_date)} - {_fmt(o.end_date)})")


def create_sprint(db, principal, project, data) -> Sprint:
    _lock(db, project.id)
    _check(db, principal, project, data)
    sprint = Sprint(**data, client_id=principal.client_id, project_id=project.id, sprint_key=_next_key(db, project, "S"), created_by=principal.user_id)
    db.add(sprint)
    db.commit()
    db.refresh(sprint)
    return sprint


def update_sprint(db, principal, project, sprint, data) -> Sprint:
    _lock(db, project.id)
    db.refresh(sprint)
    if sprint.status == "Completed":
        raise SprintError(f"{sprint.name} is Completed and kept as history")
    if sprint.status == "Active" and data["start_date"] != sprint.start_date:
        raise SprintError("An active sprint's start date cannot change")
    _check(db, principal, project, data, own_id=sprint.id)
    for key, value in data.items():
        setattr(sprint, key, value)
    db.commit()
    db.refresh(sprint)
    return sprint


def delete_sprint(db, principal, sprint) -> None:
    _open_project(db, sprint)
    if sprint.status != "Planned":
        raise SprintError(f"{sprint.name} is {sprint.status}; only Planned sprints can be deleted")
    db.query(Task).filter(Task.sprint_id == sprint.id).update({Task.sprint_id: None}, synchronize_session=False)
    sprint.is_deleted = True
    db.commit()


def add_tasks(db, principal, sprint, task_ids) -> int:
    _open_project(db, sprint)
    if sprint.status == "Completed":
        raise SprintError(f"{sprint.name} is Completed")
    moved = 0
    for tid in task_ids:
        task = task_repo.get_task(db, principal, tid)
        if task is None or task.project_id != sprint.project_id:
            raise SprintError("Every task must belong to this sprint's project")
        if task.status == "Done":
            raise SprintError(f"{task.task_key} is already Done, so it does not need a sprint")
        # A main task brings its subtasks along; a subtask goes with its parent's sprint.
        # (A subtask whose main task is already Done is planned on its own.)
        if task.parent_task_id:
            parent = task_repo.get_task(db, principal, task.parent_task_id)
            if parent and parent.status != "Done" and parent.sprint_id != sprint.id:
                raise SprintError(f"{task.task_key} is a subtask of {parent.task_key}; add {parent.task_key} to the sprint instead")
        family = [task] + db.query(Task).filter(Task.parent_task_id == task.id, Task.is_deleted == False, Task.status != "Done").all()  # noqa: E712
        for t in family:
            if t.sprint_id != sprint.id:
                if t.sprint_id:
                    other = db.query(Sprint).filter(Sprint.id == t.sprint_id).one_or_none()
                    if other and other.status == "Active" and other.id != sprint.id:
                        raise SprintError(f"{t.task_key} is in the active sprint {other.name}; remove it there first")
                log_activity(db, principal, t.id, "sprint", f"Added to sprint {sprint.name}")
                t.sprint_id = sprint.id
                moved += 1
    db.commit()
    return moved


def remove_task(db, principal, sprint, task_id) -> None:
    task = task_repo.get_task(db, principal, task_id)
    if task is None or task.sprint_id != sprint.id:
        raise LookupError("That task is not in this sprint")
    _open_project(db, sprint)
    if sprint.status == "Completed":
        raise SprintError(f"{sprint.name} is Completed and kept as history")
    if task.parent_task_id:
        parent = task_repo.get_task(db, principal, task.parent_task_id)
        if parent and parent.status != "Done" and parent.sprint_id == sprint.id:
            raise SprintError(f"{task.task_key} is a subtask of {parent.task_key}; it stays with {parent.task_key}. Move {parent.task_key} back instead")
    for t in [task] + db.query(Task).filter(Task.parent_task_id == task.id, Task.sprint_id == sprint.id).all():
        log_activity(db, principal, t.id, "sprint", f"Moved from sprint {sprint.name} back to the backlog")
        t.sprint_id = None
    db.commit()


def start_sprint(db, principal, project, sprint) -> Sprint:
    _lock(db, project.id)
    db.refresh(sprint)
    if sprint.status != "Planned":
        raise SprintError(f"{sprint.name} is already {sprint.status}")
    if project.status != "Active":
        raise SprintError(f"{project.project_code} is {project.status}; sprints start on Active projects")
    active = _live(db, principal).filter(Sprint.project_id == project.id, Sprint.status == "Active").first()
    if active:
        raise SprintError(f"{active.name} is still active. Complete it before starting another sprint")
    if not _sprint_tasks(db, sprint.id):
        raise SprintError("Add tasks to the sprint before starting it")
    sprint.status = "Active"
    sprint.started_at = _utcnow()
    db.commit()
    db.refresh(sprint)
    return sprint


def complete_sprint(db, principal, project, sprint, move_to_sprint_id=None) -> dict:
    """Closes the sprint, freezes its numbers, and moves unfinished tasks to the next sprint or the backlog.
    Allowed on a Closed project too, so a sprint left Active when the project closed can still be finished."""
    _lock(db, project.id)
    db.refresh(sprint)
    if sprint.status != "Active":
        raise SprintError(f"Only an active sprint can be completed ({sprint.name} is {sprint.status})")
    target = None
    if move_to_sprint_id:
        if project.status == "Closed":
            raise SprintError(f"{project.project_code} is Closed: unfinished tasks go back to the backlog, not to another sprint")
        target = get_sprint(db, principal, move_to_sprint_id)
        if target is None or target.project_id != project.id or target.status != "Planned":
            raise SprintError("Unfinished tasks can only move to a Planned sprint of this project")
    tasks = _sprint_tasks(db, sprint.id)
    sprint.committed_hours = sum(float(t.estimated_hours or 0) for t in tasks)
    sprint.completed_hours = sum(float(t.estimated_hours or 0) for t in tasks if t.status == "Done")
    sprint.committed_tasks = len(tasks)
    sprint.completed_tasks = sum(1 for t in tasks if t.status == "Done")
    unfinished = [t for t in tasks if t.status != "Done"]
    for t in unfinished:
        t.sprint_id = target.id if target else None
        log_activity(db, principal, t.id, "sprint", f"Not finished in {sprint.name}; moved to {target.name if target else 'the backlog'}")
    sprint.status = "Completed"
    sprint.completed_at = _utcnow()
    db.commit()
    return {"moved": len(unfinished), "to": target.name if target else "backlog", "done": sprint.completed_tasks, "committed": sprint.committed_tasks}


def backlog(db, principal, project_id) -> list:
    """Open main tasks not in any open sprint (tasks left in a completed sprint count as backlog too), best first.
    An open subtask whose main task is already Done is listed on its own, so it can still be planned."""
    open_sprints = [sid for (sid,) in _live(db, principal).filter(Sprint.project_id == project_id, Sprint.status != "Completed").with_entities(Sprint.id)]
    parent = aliased(Task)
    done_parents = select(parent.id).where(parent.project_id == project_id, parent.status == "Done")
    query = task_repo._scoped(db, principal).filter(
        Task.project_id == project_id, Task.status != "Done", (Task.parent_task_id == None) | Task.parent_task_id.in_(done_parents)  # noqa: E711
    )
    if open_sprints:
        query = query.filter((Task.sprint_id == None) | (Task.sprint_id.notin_(open_sprints)))  # noqa: E711
    rows = task_repo.serialize(db, query.with_entities(Task, Project.project_code, Project.project_name).all())
    return sorted(rows, key=lambda t: (PRIORITY_RANK.get(t["priority"], 9), t["due_date"] or "9999", t["task_key"]))


def _new_status(action, detail):
    """The status a task moved to, read from its activity row: "To Do -> Done" (status) or
    "...; Status: To Do -> Done; ..." (Edit Task form). None when the row did not change the status."""
    if not detail:
        return None
    if action == "status":
        return detail.split("->")[-1].strip()
    part = next((p for p in detail.split("; ") if p.startswith("Status: ") and "->" in p), None)
    return part.split("->")[-1].strip() if part else None


def burndown(db, principal, sprint) -> dict:
    """Remaining estimated hours per day of the sprint (from when tasks were marked Done), with the ideal line.

    A completed sprint keeps its frozen committed hours as the total (its unfinished tasks have moved on, so
    they never burn down) and its tasks count as Done on the day they were marked Done before it closed."""
    tasks = _sprint_tasks(db, sprint.id)
    completed = sprint.status == "Completed" and sprint.completed_at is not None
    total = float(sprint.committed_hours or 0) if completed else sum(float(t.estimated_hours or 0) for t in tasks)
    done_on = {}
    ids = [t.id for t in tasks] or [-1]
    # Status changes come from the board / status button ("status") and from the Edit Task form ("updated").
    activity = db.query(TaskActivity.task_id, TaskActivity.created_at, TaskActivity.action, TaskActivity.detail).filter(
        TaskActivity.task_id.in_(ids), TaskActivity.action.in_(("status", "updated"))
    )
    if completed:
        activity = activity.filter(TaskActivity.created_at <= sprint.completed_at)
    for tid, when, action, detail in activity.order_by(TaskActivity.created_at, TaskActivity.id):
        new_status = _new_status(action, detail)
        if new_status is None:
            continue
        if new_status.startswith("Done"):
            done_on[tid] = when.date()
        elif tid in done_on:
            done_on.pop(tid)  # reopened later
    days = (sprint.end_date - sprint.start_date).days + 1
    today = date.today()
    last_day = sprint.completed_at.date() if completed else today
    # Tasks still in a completed sprint were all Done when it closed (the unfinished ones were moved out).
    burned = tasks if completed else [t for t in tasks if t.status == "Done"]
    points = []
    for i in range(days):
        day = sprint.start_date + timedelta(days=i)
        remaining = total - sum(float(t.estimated_hours or 0) for t in burned if done_on.get(t.id, last_day) <= day)
        points.append({"date": day.isoformat(), "ideal": round(total - total * i / max(days - 1, 1), 2), "remaining": round(remaining, 2) if day <= today else None})
    return {"total": round(total, 2), "points": points}


def velocity(db, principal, project_id) -> list:
    done = _live(db, principal).filter(Sprint.project_id == project_id, Sprint.status == "Completed").order_by(Sprint.end_date).all()
    return [{"name": s.name, "committed": float(s.committed_hours or 0), "completed": float(s.completed_hours or 0)} for s in done[-8:]]
