"""Milestones and their deliverables. Progress comes from the milestone's linked tasks and its deliverables."""
from datetime import datetime, timezone

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.billing import Invoice
from app.models.milestones import MILESTONE_TRANSITIONS, Deliverable, Milestone
from app.models.projects import Project
from app.models.tasks import Task
from app.schemas.milestones import milestone_out
from app.core.access import project_scope


# Milestones without a due date go last (SQL Server has no "NULLS LAST").
NULLS_LAST = case((Milestone.due_date == None, 1), else_=0)  # noqa: E711


class MilestoneError(Exception):
    """A milestone rule was broken; the message is safe to show to the user."""


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _live(db: Session, principal):
    return (
        db.query(Milestone)
        .join(Project, Project.id == Milestone.project_id)
        .filter(Milestone.client_id == principal.client_id, Milestone.is_deleted == False, Project.is_deleted == False, project_scope(db, principal))  # noqa: E712
    )


def get_milestone(db, principal, milestone_id, project_id=None):
    query = _live(db, principal).filter(Milestone.id == milestone_id)
    if project_id:
        query = query.filter(Milestone.project_id == project_id)
    return query.one_or_none()


def _deliverables(db, milestone_ids):
    result = {mid: [] for mid in milestone_ids}
    if milestone_ids:
        for d in db.query(Deliverable).filter(Deliverable.milestone_id.in_(milestone_ids), Deliverable.is_deleted == False).order_by(Deliverable.id):  # noqa: E712
            result[d.milestone_id].append(d)
    return result


def _task_stats(db, milestone_ids):
    if not milestone_ids:
        return {}
    rows = (
        db.query(Task.milestone_id, func.count(), func.sum(case((Task.status == "Done", 1), else_=0)))
        .filter(Task.milestone_id.in_(milestone_ids), Task.is_deleted == False)  # noqa: E712
        .group_by(Task.milestone_id)
    )
    return {mid: {"total": total, "done": int(done or 0)} for mid, total, done in rows}


def _active_invoices(db, milestone_ids):
    if not milestone_ids:
        return {}
    rows = db.query(Invoice).filter(Invoice.milestone_id.in_(milestone_ids), Invoice.status != "Cancelled", Invoice.is_deleted == False)  # noqa: E712
    return {i.milestone_id: {"id": i.id, "invoice_no": i.invoice_no, "status": i.status, "total": float(i.total)} for i in rows}


def serialize(db, milestones, projects=None) -> list:
    ids = [m.id for m in milestones]
    deliverables, stats, invoices = _deliverables(db, ids), _task_stats(db, ids), _active_invoices(db, ids)
    projects = projects or {}
    return [
        milestone_out(m, deliverables=deliverables.get(m.id, []), task_stats=stats.get(m.id), invoice=invoices.get(m.id), project=projects.get(m.project_id))
        for m in milestones
    ]


def list_for_project(db, principal, project_id) -> list:
    rows = _live(db, principal).filter(Milestone.project_id == project_id).order_by(NULLS_LAST, Milestone.due_date, Milestone.id).all()
    return serialize(db, rows)


def list_all(db, principal, *, project_id=None, status=None, search=None) -> list:
    query = _live(db, principal).add_entity(Project)
    if project_id:
        query = query.filter(Milestone.project_id == project_id)
    if status:
        query = query.filter(Milestone.status == status)
    if search:
        like = f"%{search}%"
        query = query.filter((Milestone.name.ilike(like)) | (Project.project_name.ilike(like)) | (Project.project_code.ilike(like)))
    rows = query.order_by(NULLS_LAST, Milestone.due_date, Milestone.id).all()
    return serialize(db, [m for m, _ in rows], {p.id: p for _, p in rows})


def _check(db, principal, project, data, own_id=None):
    if project.status == "Closed":
        raise MilestoneError(f"{project.project_code} is Closed, so its milestones can no longer change")
    dupe = _live(db, principal).filter(Milestone.project_id == project.id, func.lower(Milestone.name) == data["name"].lower())
    if own_id:
        dupe = dupe.filter(Milestone.id != own_id)
    if dupe.first():
        raise MilestoneError(f"A milestone named '{data['name']}' already exists in this project")
    due = data.get("due_date")
    if due and project.start_date and due < project.start_date:
        raise MilestoneError(f"The due date cannot be before the project starts ({project.start_date.strftime('%d %b %Y')})")
    if due and project.end_date and due > project.end_date:
        raise MilestoneError(f"The due date cannot be after the project ends ({project.end_date.strftime('%d %b %Y')})")


def create_milestone(db, principal, project, data) -> Milestone:
    _check(db, principal, project, data)
    milestone = Milestone(**data, client_id=principal.client_id, project_id=project.id, created_by=principal.user_id, updated_by=principal.user_id)
    db.add(milestone)
    db.commit()
    db.refresh(milestone)
    return milestone


def _unlocked(milestone):
    if milestone.status == "Accepted":
        raise MilestoneError(f"'{milestone.name}' is Accepted, so it can no longer change")


def update_milestone(db, principal, project, milestone, data) -> Milestone:
    _unlocked(milestone)
    _check(db, principal, project, data, own_id=milestone.id)
    for key, value in data.items():
        setattr(milestone, key, value)
    milestone.updated_by = principal.user_id
    db.commit()
    db.refresh(milestone)
    return milestone


def delete_milestone(db, principal, milestone) -> None:
    _unlocked(milestone)
    if _active_invoices(db, [milestone.id]):
        raise MilestoneError(f"'{milestone.name}' has an invoice. Cancel the invoice first")
    # Its tasks stay; they just no longer belong to a milestone.
    db.query(Task).filter(Task.milestone_id == milestone.id).update({Task.milestone_id: None}, synchronize_session=False)
    milestone.is_deleted = True
    milestone.updated_by = principal.user_id
    db.commit()


def change_status(db, principal, milestone, new_status, feedback=None) -> Milestone:
    if new_status not in MILESTONE_TRANSITIONS.get(milestone.status, []):
        raise MilestoneError(f"A milestone that is {milestone.status} cannot move to {new_status}")
    if new_status == "Ready for Review":
        stats = _task_stats(db, [milestone.id]).get(milestone.id, {"total": 0, "done": 0})
        deliverables = _deliverables(db, [milestone.id])[milestone.id]
        if not stats["total"] and not deliverables:
            raise MilestoneError("Link at least one task or add a deliverable before sending this milestone for review")
        open_tasks = stats["total"] - stats["done"]
        open_deliverables = sum(1 for d in deliverables if not d.is_done)
        if open_tasks or open_deliverables:
            parts = [f"{open_tasks} task{'s' if open_tasks != 1 else ''}" if open_tasks else "", f"{open_deliverables} deliverable{'s' if open_deliverables != 1 else ''}" if open_deliverables else ""]
            raise MilestoneError(f"Finish {' and '.join(p for p in parts if p)} first - everything must be done before review")
    if new_status == "Changes Requested":
        if not feedback or len(feedback) < 5:
            raise MilestoneError("Please Enter Feedback (at least 5 characters) so the team knows what to change")
        milestone.feedback = feedback
    if new_status == "Accepted":
        milestone.accepted_at = _utcnow()
        milestone.accepted_by_name = principal.user_name
        milestone.feedback = feedback or milestone.feedback
    milestone.status = new_status
    milestone.updated_by = principal.user_id
    db.commit()
    db.refresh(milestone)
    return milestone


def add_deliverable(db, principal, milestone, name) -> Deliverable:
    _unlocked(milestone)
    exists = db.query(Deliverable).filter(Deliverable.milestone_id == milestone.id, Deliverable.is_deleted == False, func.lower(Deliverable.name) == name.lower()).first()  # noqa: E712
    if exists:
        raise MilestoneError(f"'{name}' is already a deliverable of this milestone")
    item = Deliverable(milestone_id=milestone.id, name=name)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _deliverable(db, milestone, deliverable_id):
    item = db.query(Deliverable).filter(Deliverable.id == deliverable_id, Deliverable.milestone_id == milestone.id, Deliverable.is_deleted == False).one_or_none()  # noqa: E712
    if item is None:
        raise LookupError("Deliverable not found")
    return item


def set_deliverable_done(db, principal, milestone, deliverable_id, is_done) -> None:
    _unlocked(milestone)
    item = _deliverable(db, milestone, deliverable_id)
    item.is_done = is_done
    item.done_at = _utcnow() if is_done else None
    item.done_by_name = principal.user_name if is_done else None
    db.commit()


def rename_deliverable(db, principal, milestone, deliverable_id, name) -> Deliverable:
    _unlocked(milestone)
    item = _deliverable(db, milestone, deliverable_id)
    clash = (
        db.query(Deliverable)
        .filter(Deliverable.milestone_id == milestone.id, Deliverable.is_deleted == False, Deliverable.id != item.id, func.lower(Deliverable.name) == name.lower())  # noqa: E712
        .first()
    )
    if clash:
        raise MilestoneError(f"'{name}' is already a deliverable of this milestone")
    item.name = name
    db.commit()
    return item


def delete_deliverable(db, principal, milestone, deliverable_id) -> None:
    _unlocked(milestone)
    _deliverable(db, milestone, deliverable_id).is_deleted = True
    db.commit()


# ------------------------------------------------------------------ used by the task workflow


def check_task_milestone(db, principal, project_id, milestone_id):
    """A task can join a milestone of its own project that is not Accepted yet."""
    if not milestone_id:
        return
    milestone = get_milestone(db, principal, milestone_id, project_id)
    if milestone is None:
        raise MilestoneError("The milestone must belong to the same project")
    if milestone.status == "Accepted":
        raise MilestoneError(f"'{milestone.name}' is already Accepted, so no more tasks can be added to it")


def start_from_task(db, task) -> None:
    """Work starting on a linked task starts a Planned milestone."""
    if task.milestone_id and task.status != "To Do":
        db.query(Milestone).filter(Milestone.id == task.milestone_id, Milestone.status == "Planned").update(
            {Milestone.status: "In Progress"}, synchronize_session=False
        )
