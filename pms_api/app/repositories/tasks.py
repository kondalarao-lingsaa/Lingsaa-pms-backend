from datetime import date

from sqlalchemy import case, func, or_, text
from sqlalchemy.orm import Session

from app.core.security import Principal
from app.models.projects import Project
from app.models.tasks import TASK_STATUSES, Task, TaskLabel
from app.models.team import ProjectMember
from app.models.milestones import Milestone
from app.models.sprints import Sprint
from app.repositories import automation_jobs
from app.repositories import milestones as milestone_repo
from app.repositories import notifications as notification_repo
from app.repositories import planning as planning_repo
from app.repositories import team as team_repo
from app.repositories.task_activity import blocked_message, log_activity, open_blockers
from app.schemas.rules import utc_iso
from app.schemas.tasks import task_out
from app.core.access import project_scope


class TaskError(Exception):
    """A rule of the task workflow was broken; the message is safe to show to the user."""


class TaskConflict(TaskError):
    """The task changed after the form was loaded (answered with 409)."""


PRIORITY_RANK = case({"Critical": 0, "High": 1, "Medium": 2, "Low": 3}, value=Task.priority, else_=4)
STATUS_RANK = case({"To Do": 0, "In Progress": 1, "Testing": 2, "Done": 3}, value=Task.status, else_=4)

SORTABLE = {
    "task_key": Task.task_key,
    "title": Task.title,
    "project": Project.project_name,
    "assignee_name": Task.assignee_name,
    "priority": PRIORITY_RANK,
    "status": STATUS_RANK,
    "due_date": Task.due_date,
    "created_at": Task.created_at,
}


def _scoped(db: Session, principal: Principal):
    """Live tasks of live projects of this company only."""
    return (
        db.query(Task)
        .join(Project, Project.id == Task.project_id)
        .filter(Task.client_id == principal.client_id, Task.is_deleted == False, Project.is_deleted == False, project_scope(db, principal))  # noqa: E712
    )


def get_task(db, principal, task_id):
    return _scoped(db, principal).filter(Task.id == task_id).one_or_none()


def _get_project(db, principal, project_id):
    return (
        db.query(Project)
        .filter(Project.id == project_id, Project.client_id == principal.client_id, Project.is_deleted == False, project_scope(db, principal))  # noqa: E712
        .one_or_none()
    )


def _labels_for(db, task_ids):
    result = {tid: [] for tid in task_ids}
    if task_ids:
        for tid, label in db.query(TaskLabel.task_id, TaskLabel.label).filter(TaskLabel.task_id.in_(task_ids)).order_by(TaskLabel.id):
            result[tid].append(label)
    return result


def _parents_for(db, tasks):
    ids = {t.parent_task_id for t in tasks if t.parent_task_id}
    if not ids:
        return {}
    return {pid: (key, title) for pid, key, title in db.query(Task.id, Task.task_key, Task.title).filter(Task.id.in_(ids))}


def _subtask_counts(db, task_ids):
    if not task_ids:
        return {}
    rows = (
        db.query(Task.parent_task_id, func.count())
        .filter(Task.parent_task_id.in_(task_ids), Task.is_deleted == False)  # noqa: E712
        .group_by(Task.parent_task_id)
    )
    return dict(rows.all())


def serialize(db, tasks_with_project):
    """tasks_with_project: list of (Task, project_code, project_name)."""
    tasks = [row[0] for row in tasks_with_project]
    ids = [t.id for t in tasks]
    labels = _labels_for(db, ids)
    parents = _parents_for(db, tasks)
    subs = _subtask_counts(db, ids)
    milestone_ids = {t.milestone_id for t in tasks if t.milestone_id}
    milestones = dict(db.query(Milestone.id, Milestone.name).filter(Milestone.id.in_(milestone_ids)).all()) if milestone_ids else {}
    sprint_ids = {t.sprint_id for t in tasks if t.sprint_id}
    sprints = dict(db.query(Sprint.id, Sprint.name).filter(Sprint.id.in_(sprint_ids)).all()) if sprint_ids else {}
    return [
        task_out(t, project_code=code, project_name=name, labels=labels.get(t.id), parent=parents.get(t.parent_task_id),
                 subtask_count=subs.get(t.id, 0), milestone_name=milestones.get(t.milestone_id), sprint_name=sprints.get(t.sprint_id))
        for t, code, name in tasks_with_project
    ]


def list_tasks(
    db, principal, *, page, page_size, search=None, status=None, priority=None, project_id=None,
    mine=False, top_level=False, sprint_id=None, sort_by="created_at", sort_order="desc"
):
    query = _scoped(db, principal)

    if project_id:
        query = query.filter(Task.project_id == project_id)
    if sprint_id:
        query = query.filter(Task.sprint_id == sprint_id)
    if mine:
        uid = principal.user_id
        query = query.filter(Task.assignee_id == uid) if uid else query.filter(text("1 = 0"))
    if top_level:
        query = query.filter(Task.parent_task_id == None)  # noqa: E711
    if priority:
        query = query.filter(Task.priority == priority)
    if search:
        like = f"%{search}%"
        query = query.filter(or_(Task.title.ilike(like), Task.task_key.ilike(like), Task.assignee_name.ilike(like), Project.project_name.ilike(like)))

    # Counts ignore the status filter so every status chip always shows its own total.
    counts = dict.fromkeys(TASK_STATUSES, 0)
    for status_name, n in query.with_entities(Task.status, func.count()).group_by(Task.status):
        counts[status_name] = n
    overdue = query.filter(Task.due_date != None, Task.due_date < date.today(), Task.status != "Done").count()  # noqa: E711

    if status:
        query = query.filter(Task.status == status)

    total = query.count()
    column = SORTABLE.get(sort_by, Task.created_at)
    query = query.order_by(column.asc() if sort_order == "asc" else column.desc(), Task.id.desc())
    rows = query.with_entities(Task, Project.project_code, Project.project_name).offset((page - 1) * page_size).limit(page_size).all()

    return serialize(db, rows), total, counts, overdue


def get_detail(db, principal, task_id):
    row = (
        _scoped(db, principal)
        .filter(Task.id == task_id)
        .with_entities(Task, Project.project_code, Project.project_name)
        .one_or_none()
    )
    if row is None:
        return None
    detail = serialize(db, [row])[0]
    subtasks = (
        db.query(Task)
        .filter(Task.parent_task_id == task_id, Task.is_deleted == False)  # noqa: E712
        .order_by(Task.id)
        .all()
    )
    detail["subtasks"] = [
        {"id": s.id, "task_key": s.task_key, "title": s.title, "status": s.status, "assignee_name": s.assignee_name}
        for s in subtasks
    ]
    return detail


def _next_task_key(db: Session, project: Project) -> str:
    # UPDLOCK/HOLDLOCK serialises concurrent creates in one project so keys never repeat.
    row = db.execute(
        text("SELECT last_no FROM projectmanagement.task_counters WITH (UPDLOCK, HOLDLOCK) WHERE project_id = :p"),
        {"p": project.id},
    ).first()
    if row is None:
        next_no = 1
        db.execute(text("INSERT INTO projectmanagement.task_counters (project_id, last_no) VALUES (:p, 1)"), {"p": project.id})
    else:
        next_no = row[0] + 1
        db.execute(text("UPDATE projectmanagement.task_counters SET last_no = :n WHERE project_id = :p"), {"n": next_no, "p": project.id})
    return f"{project.project_code}-T{next_no}"


def _check_parent(db, principal, project_id, parent_task_id, own_id=None):
    if not parent_task_id:
        return None
    if own_id and parent_task_id == own_id:
        raise TaskError("A task cannot be its own parent")
    parent = get_task(db, principal, parent_task_id)
    if parent is None or parent.project_id != project_id:
        raise TaskError("The parent task must belong to the same project")
    if parent.parent_task_id is not None:
        raise TaskError("Subtasks can only be added under a main task, not under another subtask")
    return parent


def _apply_assignee(db, principal, project_id, data):
    """Tasks go to members of the project's team; the member's login user id is filled in so My Tasks works.
    The stored user id is always the member's own (None for a member without a login), never the caller's."""
    sent_id, sent_name = data.get("assignee_id"), data.get("assignee_name")
    try:
        # Refuses anyone who is not on the team at all.
        team_repo.resolve_assignee(db, principal, project_id, sent_name, sent_id)
    except team_repo.TeamError as exc:
        raise TaskError(str(exc)) from exc
    if not sent_name and not sent_id:
        data["assignee_id"], data["assignee_name"] = None, None
        return
    team = team_repo._live_members(db, principal).filter(ProjectMember.project_id == project_id)
    member = team.filter(ProjectMember.user_id == sent_id).first() if sent_id else None
    if member is None and sent_name:
        member = team.filter(func.lower(ProjectMember.member_name) == sent_name.lower()).first()
    if member is None or (sent_id and member.user_id != sent_id):
        raise TaskError(f"{sent_name or 'This person'} is not in this project's team. Pick the assignee from the project's team.")
    data["assignee_id"], data["assignee_name"] = member.user_id, member.member_name


def _check_milestone(db, principal, project_id, milestone_id):
    try:
        milestone_repo.check_task_milestone(db, principal, project_id, milestone_id)
    except milestone_repo.MilestoneError as exc:
        raise TaskError(str(exc)) from exc


def _notify_assigned(db, principal, task):
    if task.assignee_name or task.assignee_id:
        who = notification_repo.person_name(principal.user_name) or "Someone"
        notification_repo.notify(db, principal, [(task.assignee_id, task.assignee_name)], "assigned", f"{who} assigned {task.task_key} to you: {task.title}",
                                 body=f"Priority {task.priority}" + (f", due {task.due_date.strftime('%d %b %Y')}" if task.due_date else ""),
                                 link=notification_repo.task_link(task.id), project_id=task.project_id, task_id=task.id)


def _notify_status(db, principal, task, old_status):
    who = notification_repo.person_name(principal.user_name) or "Someone"
    notification_repo.notify(db, principal, notification_repo.task_audience(db, task), "status", f"{task.task_key} moved to {task.status}: {task.title}",
                             body=f"{who} changed the status from {old_status} to {task.status}", link=notification_repo.task_link(task.id),
                             project_id=task.project_id, task_id=task.id)


def _set_labels(db, task_id, labels):
    db.query(TaskLabel).filter(TaskLabel.task_id == task_id).delete()
    for label in labels:
        db.add(TaskLabel(task_id=task_id, label=label))


def _ensure_open(db, project_id=None, project=None):
    """A Closed project is history: its tasks can be read and discussed, not changed."""
    project = project or db.query(Project).filter(Project.id == project_id).one_or_none()
    if project is not None and project.status == "Closed":
        raise TaskError(f"{project.project_code} is Closed, so its tasks can no longer change")


def _check_schedule(db, project, task_key, data, task_id=None):
    """Task dates follow the same plan rules as the timeline (project dates, blockers, waiting tasks)."""
    try:
        planning_repo.check_dates(db, project, task_key, data.get("start_date"), data.get("due_date"), task_id=task_id, status=data.get("status"))
    except planning_repo.PlanningError as exc:
        raise TaskError(str(exc)) from exc


def create_task(db, principal, data: dict) -> Task:
    project = _get_project(db, principal, data["project_id"])
    if project is None:
        raise TaskError("Project not found")
    _ensure_open(db, project=project)
    data.pop("updated_at", None)  # only used when editing
    _check_schedule(db, project, "The task", data)
    parent = _check_parent(db, principal, project.id, data.get("parent_task_id"))

    labels = data.pop("labels", [])
    data.pop("actual_hours", None)  # filled from approved timesheets
    _check_milestone(db, principal, project.id, data.get("milestone_id"))
    if parent is not None:
        data["task_type"] = "Subtask"
    _apply_assignee(db, principal, project.id, data)

    task = Task(
        **data,
        client_id=principal.client_id,
        task_key=_next_task_key(db, project),
        reporter_id=principal.user_id,
        reporter_name=principal.user_name,
        created_by=principal.user_id,
        updated_by=principal.user_id,
    )
    db.add(task)
    db.flush()
    _set_labels(db, task.id, labels)
    log_activity(db, principal, task.id, "created", f"Created in {task.status}" + (f", assigned to {task.assignee_name}" if task.assignee_name else ""))
    _notify_assigned(db, principal, task)
    milestone_repo.start_from_task(db, task)
    db.commit()
    db.refresh(task)
    return task


def update_task(db, principal, task: Task, data: dict) -> Task:
    _ensure_open(db, task.project_id)
    loaded = data.pop("updated_at", None)
    if loaded and loaded != utc_iso(task.updated_at):
        raise TaskConflict(f"{task.task_key} was changed by someone else after you opened it. Close and open it again to see the latest version")
    if data["project_id"] != task.project_id:
        raise TaskError("A task cannot be moved to another project")
    data.pop("project_id")

    parent = _check_parent(db, principal, task.project_id, data.get("parent_task_id"), own_id=task.id)
    if parent is not None:
        has_subtasks = db.query(Task).filter(Task.parent_task_id == task.id, Task.is_deleted == False).count()  # noqa: E712
        if has_subtasks:
            raise TaskError("This task has subtasks, so it cannot become a subtask itself")
        data["task_type"] = "Subtask"
    elif task.parent_task_id and data.get("task_type") == "Subtask":
        data["task_type"] = "Task"

    # Only a changed assignee is checked, so older tasks assigned before teams existed can still be edited.
    if (data.get("assignee_name") or None) != (task.assignee_name or None) or data.get("assignee_id") != task.assignee_id:
        _apply_assignee(db, principal, task.project_id, data)

    if data.get("status") == "Done" and task.status != "Done":
        blockers = open_blockers(db, task.id)
        if blockers:
            raise TaskError(blocked_message(blockers))

    # Only changed dates are checked, so a task planned before the rules (or the project dates) changed can still be edited.
    if data.get("start_date") != task.start_date or data.get("due_date") != task.due_date:
        project = db.query(Project).filter(Project.id == task.project_id).one()
        _check_schedule(db, project, task.task_key, data, task_id=task.id)

    data.pop("actual_hours", None)  # filled from approved timesheets
    if data.get("milestone_id") != task.milestone_id:
        try:
            # The client signed off on an Accepted milestone's work: its tasks stay where they are.
            milestone_repo.check_task_leaves_milestone(db, principal, task.milestone_id)
        except milestone_repo.MilestoneError as exc:
            raise TaskError(str(exc)) from exc
        _check_milestone(db, principal, task.project_id, data.get("milestone_id"))
    changes = _describe_changes(task, data)
    labels = data.pop("labels", [])
    old_assignee, old_status = (task.assignee_id, (task.assignee_name or "").lower()), task.status
    for key, value in data.items():
        setattr(task, key, value)
    task.updated_by = principal.user_id
    _set_labels(db, task.id, labels)
    if changes:
        log_activity(db, principal, task.id, "updated", "; ".join(changes))
    if (task.assignee_id, (task.assignee_name or "").lower()) != old_assignee:
        _notify_assigned(db, principal, task)
    if task.status != old_status:
        _notify_status(db, principal, task, old_status)
    milestone_repo.start_from_task(db, task)
    automation_jobs.after_task_status(db, task, old_status)
    db.commit()
    db.refresh(task)
    return task


# Fields whose changes are written to the task history, with the label shown to users.
TRACKED_FIELDS = {
    "title": "Name",
    "status": "Status",
    "priority": "Priority",
    "assignee_name": "Assignee",
    "start_date": "Start date",
    "due_date": "Due date",
    "estimated_hours": "Estimate",
    "actual_hours": "Actual hours",
}


def _describe_changes(task: Task, data: dict) -> list:
    changes = []
    for field, label in TRACKED_FIELDS.items():
        if field not in data:
            continue
        old, new = getattr(task, field), data[field]
        if (float(old) if old is not None and field.endswith("hours") else old) != (float(new) if new is not None and field.endswith("hours") else new):
            changes.append(f"{label}: {old if old not in (None, '') else '-'} -> {new if new not in (None, '') else '-'}")
    return changes


def change_status(db, principal, task: Task, new_status: str) -> Task:
    if new_status == task.status:
        return task
    _ensure_open(db, task.project_id)
    if new_status == "Done":
        blockers = open_blockers(db, task.id)
        if blockers:
            raise TaskError(blocked_message(blockers))
    log_activity(db, principal, task.id, "status", f"{task.status} -> {new_status}")
    old_status, task.status = task.status, new_status
    task.updated_by = principal.user_id
    _notify_status(db, principal, task, old_status)
    milestone_repo.start_from_task(db, task)
    automation_jobs.after_task_status(db, task, old_status)
    db.commit()
    db.refresh(task)
    return task


def delete_task(db, principal, task: Task) -> None:
    _ensure_open(db, task.project_id)
    # Submitted or approved hours are real cost (and maybe billed): deleting the task would drop them out of
    # the budget, earned value and billing without a trace.
    from app.models.timesheets import TimeEntry  # local import: timesheets reads the task model

    subtask_ids = [t.id for t in db.query(Task.id).filter(Task.parent_task_id == task.id, Task.is_deleted == False)]  # noqa: E712
    logged = (
        db.query(func.coalesce(func.sum(TimeEntry.hours), 0))
        .filter(TimeEntry.task_id.in_([task.id] + subtask_ids), TimeEntry.is_deleted == False,  # noqa: E712
                TimeEntry.status.in_(("Submitted", "Approved")))
        .scalar()
    )
    if logged:
        raise TaskError(f"{task.task_key} has {float(logged):g} hours submitted or approved against it, so it cannot be deleted. "
                        "Move it to Done instead")
    log_activity(db, principal, task.id, "deleted", "Task deleted")
    task.is_deleted = True
    task.updated_by = principal.user_id
    for sub in db.query(Task).filter(Task.parent_task_id == task.id, Task.is_deleted == False):  # noqa: E712
        sub.is_deleted = True
        sub.updated_by = principal.user_id
    db.commit()


def row_for(db, principal, task_id):
    return serialize(db, _scoped(db, principal).filter(Task.id == task_id).with_entities(Task, Project.project_code, Project.project_name).all())[0]


BOARD_LIMIT = 500


def board(db, principal, *, project_id=None, mine=False, search=None, priority=None, assignee=None, sprint_id=None):
    """Tasks grouped by status for the Kanban board, in each column's saved card order."""
    query = _scoped(db, principal)
    if project_id:
        query = query.filter(Task.project_id == project_id)
    if mine:
        uid = principal.user_id
        query = query.filter(Task.assignee_id == uid) if uid else query.filter(text("1 = 0"))
    if priority:
        query = query.filter(Task.priority == priority)
    if assignee:
        query = query.filter(Task.assignee_name == assignee)
    if sprint_id:
        query = query.filter(Task.sprint_id == sprint_id)
    if search:
        like = f"%{search}%"
        query = query.filter(or_(Task.title.ilike(like), Task.task_key.ilike(like), Task.assignee_name.ilike(like), Project.project_name.ilike(like)))

    total = query.count()
    rows = (
        query.order_by(Task.board_order.asc(), PRIORITY_RANK.asc(), Task.id.asc())
        .with_entities(Task, Project.project_code, Project.project_name)
        .limit(BOARD_LIMIT)
        .all()
    )
    columns = {status: [] for status in TASK_STATUSES}
    for item in serialize(db, rows):
        columns.setdefault(item["status"], []).append(item)
    return columns, total, total > BOARD_LIMIT


BOARD_GAP = 1024.0


def _renumber_column(db, principal, status, project_id=None):
    """Spreads a column's cards out again (1024 apart) when two neighbours have run out of room between them.
    Without a project (neighbours from different projects on the All Projects board) the whole company's
    column is renumbered, so the order every user sees stays the same."""
    if project_id:
        query = _scoped(db, principal).filter(Task.project_id == project_id)
    else:
        query = (
            db.query(Task)
            .join(Project, Project.id == Task.project_id)
            .filter(Task.client_id == principal.client_id, Task.is_deleted == False, Project.is_deleted == False)  # noqa: E712
        )
    cards = (
        query.filter(Task.status == status)
        .order_by(Task.board_order.asc(), PRIORITY_RANK.asc(), Task.id.asc())
        .all()
    )
    for index, card in enumerate(cards, start=1):
        card.board_order = index * BOARD_GAP
        card.updated_at = Task.updated_at  # housekeeping, not a change to the task: keeps its version (see update_task)
    db.flush()


def move_task(db, principal, task: Task, new_status: str, prev_id=None, next_id=None) -> Task:
    """Drops a card into a column between two neighbours (either may be missing: top or bottom of the column)."""
    _ensure_open(db, task.project_id)
    # Neighbours may belong to other projects: the All Projects board shows every project in one column,
    # ordered by board_order.
    neighbours = {n.id: n for n in (get_task(db, principal, i) for i in (prev_id, next_id) if i) if n}
    for n in neighbours.values():
        if n.status != new_status:
            neighbours = {}  # stale board: fall back to dropping at the bottom
            break
    prev_card, next_card = neighbours.get(prev_id), neighbours.get(next_id)
    same_project = all(n.project_id == task.project_id for n in neighbours.values())

    if prev_card and next_card and next_card.board_order - prev_card.board_order < 1e-6:
        _renumber_column(db, principal, new_status, task.project_id if same_project else None)

    if prev_card and next_card:
        order = (prev_card.board_order + next_card.board_order) / 2
    elif prev_card:
        order = prev_card.board_order + BOARD_GAP
    elif next_card:
        order = next_card.board_order - BOARD_GAP
    else:
        last = (
            _scoped(db, principal)
            .filter(Task.status == new_status, Task.project_id == task.project_id, Task.id != task.id)
            .with_entities(func.max(Task.board_order))
            .scalar()
        )
        order = (last or 0) + BOARD_GAP

    if new_status != task.status:
        if new_status == "Done":
            blockers = open_blockers(db, task.id)
            if blockers:
                raise TaskError(blocked_message(blockers))
        log_activity(db, principal, task.id, "status", f"{task.status} -> {new_status} (board)")
        old_status, task.status = task.status, new_status
        _notify_status(db, principal, task, old_status)
        milestone_repo.start_from_task(db, task)
        automation_jobs.after_task_status(db, task, old_status)
    task.board_order = order
    task.updated_by = principal.user_id
    db.commit()
    db.refresh(task)
    return task
