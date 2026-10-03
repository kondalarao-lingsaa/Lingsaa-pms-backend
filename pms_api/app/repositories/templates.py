"""Project templates: save a project's plan once, start new projects from it with every date shifted to the new
start. Dates are kept as "day N from the start" (day 0 = the first day)."""
from datetime import timedelta

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.milestones import Milestone
from app.models.tasks import Task
from app.models.templates import ProjectTemplate, TemplateMilestone, TemplateTask
from app.repositories import projects as project_repo
from app.repositories import tasks as task_repo
from app.repositories.notifications import person_name
from app.repositories.task_activity import log_activity
from app.schemas.rules import utc_iso


class TemplateError(Exception):
    """A template rule was broken; the message is safe to show to the user."""


def _num(v):
    return float(v) if v is not None else None


def _live(db: Session, principal):
    return db.query(ProjectTemplate).filter(ProjectTemplate.client_id == principal.client_id, ProjectTemplate.is_deleted == False)  # noqa: E712


def get_template(db, principal, template_id):
    return _live(db, principal).filter(ProjectTemplate.id == template_id).one_or_none()


def _children(db, template_id):
    ms = db.query(TemplateMilestone).filter(TemplateMilestone.template_id == template_id).order_by(TemplateMilestone.sort_order).all()
    ts = db.query(TemplateTask).filter(TemplateTask.template_id == template_id).order_by(TemplateTask.sort_order).all()
    return ms, ts


def template_out(db, t: ProjectTemplate, full=False) -> dict:
    ms, ts = _children(db, t.id)
    out = {
        "id": t.id, "name": t.name, "description": t.description, "project_type": t.project_type, "duration_days": t.duration_days,
        "source_project_code": t.source_project_code, "times_used": t.times_used, "created_by_name": t.created_by_name,
        "created_at": utc_iso(t.created_at), "updated_at": utc_iso(t.updated_at),
        "milestone_count": len(ms), "task_count": sum(1 for x in ts if x.parent_index is None), "subtask_count": sum(1 for x in ts if x.parent_index is not None),
        "estimated_hours": round(sum(float(x.estimated_hours or 0) for x in ts), 2),
    }
    if full:
        out["milestones"] = [{"name": m.name, "description": m.description, "due_offset": m.due_offset, "amount": _num(m.amount)} for m in ms]
        out["tasks"] = [{"title": x.title, "description": x.description, "task_type": x.task_type, "priority": x.priority,
                         "estimated_hours": _num(x.estimated_hours), "start_offset": x.start_offset, "duration_days": x.duration_days,
                         "milestone_index": x.milestone_index, "parent_index": x.parent_index} for x in ts]
    return out


def list_templates(db, principal, search=None) -> list:
    query = _live(db, principal)
    if search:
        query = query.filter(ProjectTemplate.name.ilike(f"%{search}%"))
    return [template_out(db, t) for t in query.order_by(ProjectTemplate.name).all()]


def _unique_name(db, principal, name, own_id=None):
    q = _live(db, principal).filter(func.lower(ProjectTemplate.name) == name.lower())
    if own_id:
        q = q.filter(ProjectTemplate.id != own_id)
    if q.first():
        raise TemplateError(f"A template named '{name}' already exists")


def _write_children(db, template_id, milestones, tasks):
    db.query(TemplateMilestone).filter(TemplateMilestone.template_id == template_id).delete()
    db.query(TemplateTask).filter(TemplateTask.template_id == template_id).delete()
    for i, m in enumerate(milestones):
        db.add(TemplateMilestone(template_id=template_id, sort_order=i, **m))
    for i, t in enumerate(tasks):
        db.add(TemplateTask(template_id=template_id, sort_order=i, **t))


def create_template(db, principal, data: dict, source_project_code=None) -> ProjectTemplate:
    _unique_name(db, principal, data["name"])
    milestones, tasks = data.pop("milestones"), data.pop("tasks")
    t = ProjectTemplate(**data, client_id=principal.client_id, source_project_code=source_project_code, created_by=principal.user_id,
                        created_by_name=person_name(principal.user_name) or principal.user_name)
    db.add(t)
    db.flush()
    _write_children(db, t.id, milestones, tasks)
    db.commit()
    db.refresh(t)
    return t


def update_template(db, principal, t: ProjectTemplate, data: dict) -> ProjectTemplate:
    _unique_name(db, principal, data["name"], own_id=t.id)
    milestones, tasks = data.pop("milestones"), data.pop("tasks")
    for k, v in data.items():
        setattr(t, k, v)
    _write_children(db, t.id, milestones, tasks)
    db.commit()
    db.refresh(t)
    return t


def delete_template(db, principal, t: ProjectTemplate) -> None:
    t.is_deleted = True
    db.commit()


# ------------------------------------------------------------------------------ project -> template


def from_project(db, principal, project, name, description) -> ProjectTemplate:
    """The project's milestones and tasks, with dates turned into days from the project start."""
    tasks = db.query(Task).filter(Task.project_id == project.id, Task.is_deleted == False).order_by(case((Task.parent_task_id == None, 0), else_=1), Task.id).all()  # noqa: E712
    milestones = db.query(Milestone).filter(Milestone.project_id == project.id, Milestone.is_deleted == False).order_by(Milestone.due_date, Milestone.id).all()  # noqa: E712
    if not tasks and not milestones:
        raise TemplateError(f"{project.project_code} has no tasks or milestones to save")
    dates = [d for t in tasks for d in (t.start_date, t.due_date) if d] + [m.due_date for m in milestones if m.due_date]
    base = project.start_date or (min(dates) if dates else None)
    last = max([project.end_date] + dates if project.end_date else dates) if dates or project.end_date else None
    off = lambda d: max(0, (d - base).days) if d and base else None  # noqa: E731

    m_index = {m.id: i for i, m in enumerate(milestones)}
    # Main tasks first, so a subtask's parent_index always points backwards.
    t_index = {t.id: i for i, t in enumerate(tasks)}
    data = {
        "name": name, "description": description, "project_type": project.project_type,
        "duration_days": max(1, ((last - base).days + 1) if last and base else 30),
        "milestones": [{"name": m.name, "description": m.description, "due_offset": off(m.due_date), "amount": m.amount} for m in milestones],
        "tasks": [{
            "title": t.title, "description": t.description, "task_type": t.task_type, "priority": t.priority, "estimated_hours": t.estimated_hours,
            "start_offset": off(t.start_date or t.due_date),
            "duration_days": ((t.due_date - t.start_date).days + 1) if t.start_date and t.due_date else (1 if t.due_date else None),
            "milestone_index": m_index.get(t.milestone_id), "parent_index": t_index.get(t.parent_task_id),
        } for t in tasks],
    }
    return create_template(db, principal, data, source_project_code=project.project_code)


# ------------------------------------------------------------------------------ template -> project


def create_project(db, principal, t: ProjectTemplate, project_data: dict) -> tuple:
    """New Draft project from the template: milestones and tasks created with dates from the project start."""
    start = project_data.get("start_date")
    if not start:
        raise TemplateError("Please Select Start Date - every date of the plan is counted from it")
    if not project_data.get("end_date"):
        project_data["end_date"] = start + timedelta(days=t.duration_days - 1)
    end = project_data["end_date"]
    if not project_data.get("project_type"):
        project_data["project_type"] = t.project_type
    ms, ts = _children(db, t.id)
    latest = max([start + timedelta(days=m.due_offset) for m in ms if m.due_offset is not None]
                 + [start + timedelta(days=x.start_offset + (x.duration_days or 1) - 1) for x in ts if x.start_offset is not None] or [start])
    if latest > end:
        raise TemplateError(f"The plan runs until {latest.strftime('%d %b %Y')}, after the end date {end.strftime('%d %b %Y')}. Move the end date or leave it empty")

    project = project_repo.create_project(db, principal, project_data, commit=False)
    milestone_ids = []
    for m in ms:
        row = Milestone(client_id=principal.client_id, project_id=project.id, name=m.name, description=m.description, amount=m.amount,
                        due_date=start + timedelta(days=m.due_offset) if m.due_offset is not None else None,
                        created_by=principal.user_id, updated_by=principal.user_id)
        db.add(row)
        db.flush()
        milestone_ids.append(row.id)
    task_ids = []
    for x in ts:
        s = start + timedelta(days=x.start_offset) if x.start_offset is not None else None
        due = s + timedelta(days=(x.duration_days or 1) - 1) if s else None
        row = Task(client_id=principal.client_id, project_id=project.id, task_key=task_repo._next_task_key(db, project), title=x.title,
                   description=x.description, task_type=x.task_type, priority=x.priority, estimated_hours=x.estimated_hours,
                   start_date=s if x.duration_days and x.duration_days > 1 else None, due_date=due,
                   milestone_id=milestone_ids[x.milestone_index] if x.milestone_index is not None and x.milestone_index < len(milestone_ids) else None,
                   parent_task_id=task_ids[x.parent_index] if x.parent_index is not None and x.parent_index < len(task_ids) else None,
                   reporter_id=principal.user_id, reporter_name=principal.user_name, created_by=principal.user_id, updated_by=principal.user_id)
        db.add(row)
        db.flush()
        task_ids.append(row.id)
        log_activity(db, principal, row.id, "created", f"Created from template '{t.name}'")
    t.times_used = (t.times_used or 0) + 1
    db.commit()
    db.refresh(project)
    return project, len(milestone_ids), len(task_ids)
