from datetime import date

from sqlalchemy import case, func, or_, text
from sqlalchemy.orm import Session

from app.core.security import Principal
from app.models.projects import PROJECT_STATUSES, PROJECT_TRANSITIONS, Project
from app.models.tasks import TASK_STATUSES, Task
from app.repositories import team as team_repo
from app.schemas.projects import missing_for_approval
from app.core.access import project_scope

SORTABLE = {
    "project_code": Project.project_code,
    "project_name": Project.project_name,
    "customer_name": Project.customer_name,
    "status": Project.status,
    "priority": Project.priority,
    "start_date": Project.start_date,
    "end_date": Project.end_date,
    "budget": Project.budget,
    "created_at": Project.created_at,
}


def _scoped(db: Session, principal: Principal):
    return db.query(Project).filter(Project.client_id == principal.client_id, Project.is_deleted == False, project_scope(db, principal))  # noqa: E712


def list_projects(
    db, principal, *, page, page_size, search=None, status=None, priority=None, sort_by="created_at", sort_order="desc", mine=False
):
    query = _scoped(db, principal)

    if mine:
        # "My Projects" = projects I created, manage or am on the team of. Without a known user id nothing can be "mine".
        uid = principal.user_id
        if uid:
            member_of = team_repo.member_project_ids(db, principal, uid)
            query = query.filter(or_(Project.created_by == uid, Project.project_manager_id == uid, Project.id.in_(member_of or [-1])))
        else:
            query = query.filter(text("1 = 0"))

    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                Project.project_name.ilike(like),
                Project.project_code.ilike(like),
                Project.customer_name.ilike(like),
                Project.project_manager_name.ilike(like),
            )
        )
    if priority:
        query = query.filter(Project.priority == priority)

    # Status counts ignore the status filter so the chips always show every bucket.
    counts = dict.fromkeys(PROJECT_STATUSES, 0)
    for status_name, n in query.with_entities(Project.status, func.count()).group_by(Project.status):
        counts[status_name] = n

    if status:
        query = query.filter(Project.status == status)

    total = query.count()
    column = SORTABLE.get(sort_by, Project.created_at)
    query = query.order_by(column.asc() if sort_order == "asc" else column.desc(), Project.id.desc())
    rows = query.offset((page - 1) * page_size).limit(page_size).all()

    return rows, total, counts


def all_projects(db, principal) -> list:
    """Every live project of the company, by code (for portfolio views such as the budget overview)."""
    return _scoped(db, principal).order_by(Project.project_code).all()


def get_project(db, principal, project_id):
    return _scoped(db, principal).filter(Project.id == project_id).one_or_none()


def _next_project_code(db: Session, client_id: int) -> str:
    year = date.today().year
    # UPDLOCK/HOLDLOCK serialises concurrent creates for the same client+year so codes never repeat.
    row = db.execute(
        text(
            "SELECT last_no FROM projectmanagement.project_counters WITH (UPDLOCK, HOLDLOCK) "
            "WHERE client_id = :c AND year = :y"
        ),
        {"c": client_id, "y": year},
    ).first()
    if row is None:
        next_no = 1
        db.execute(
            text("INSERT INTO projectmanagement.project_counters (client_id, year, last_no) VALUES (:c, :y, 1)"),
            {"c": client_id, "y": year},
        )
    else:
        next_no = row[0] + 1
        db.execute(
            text("UPDATE projectmanagement.project_counters SET last_no = :n WHERE client_id = :c AND year = :y"),
            {"n": next_no, "c": client_id, "y": year},
        )
    return f"PRJ-{year}-{next_no:04d}"


def _ensure_unique_name(db, principal, name: str, own_id=None):
    query = _scoped(db, principal).filter(func.lower(Project.project_name) == name.lower())
    if own_id:
        query = query.filter(Project.id != own_id)
    if query.first() is not None:
        raise DuplicateProject(f"A project named '{name}' already exists")


def create_project(db, principal, data: dict, commit=True) -> Project:
    """commit=False lets a caller (create from template) add milestones/tasks and commit everything at once."""
    _ensure_unique_name(db, principal, data["project_name"])
    project = Project(
        **data,
        client_id=principal.client_id,
        status="Draft",
        project_code=_next_project_code(db, principal.client_id),
        created_by=principal.user_id,
        updated_by=principal.user_id,
    )
    db.add(project)
    db.flush()
    team_repo.ensure_manager_member(db, principal, project, commit=False)
    if commit:
        db.commit()
        db.refresh(project)
    return project


def update_project(db, principal, project: Project, data: dict) -> Project:
    _ensure_unique_name(db, principal, data["project_name"], own_id=project.id)
    for key, value in data.items():
        setattr(project, key, value)
    project.updated_by = principal.user_id
    db.commit()
    db.refresh(project)
    team_repo.ensure_manager_member(db, principal, project)
    return project


def delete_project(db, principal, project: Project) -> None:
    project.is_deleted = True
    project.updated_by = principal.user_id
    db.commit()


class InvalidTransition(Exception):
    pass


class DuplicateProject(Exception):
    pass


def change_status(db, principal, project: Project, new_status: str, remarks: str = None) -> tuple:
    """Moves a project along its lifecycle. Submit, Approve and Send back follow the approval rules
    (app/repositories/approvals.py). Returns (project, message)."""
    from app.repositories import approvals  # local import: approvals reads the project model

    if new_status not in PROJECT_TRANSITIONS.get(project.status, []):
        raise InvalidTransition(f"A {project.status} project cannot move to {new_status}")
    try:
        if new_status == "Pending Approval":
            missing = missing_for_approval(project)
            if missing:
                raise InvalidTransition(f"Add {' and '.join(missing)} before sending this project for approval")
            message = approvals.submit_project(db, principal, project)
        elif new_status == "Approved":
            message = approvals.approve_project(db, principal, project, remarks)
        elif project.status == "Pending Approval" and new_status == "Draft":
            message = approvals.send_back_project(db, principal, project, remarks)
        else:
            project.status = new_status
            message = f"{project.project_code} is now {new_status}"
    except approvals.ApprovalError as exc:
        db.rollback()
        raise InvalidTransition(str(exc)) from exc
    project.updated_by = principal.user_id
    db.commit()
    db.refresh(project)
    return project, message


def progress_for(db: Session, project_ids: list) -> dict:
    """Task count and % done per project (done tasks / all tasks)."""
    if not project_ids:
        return {}
    done = func.sum(case((Task.status == "Done", 1), else_=0))
    rows = (
        db.query(Task.project_id, func.count(), done)
        .filter(Task.project_id.in_(project_ids), Task.is_deleted == False)  # noqa: E712
        .group_by(Task.project_id)
        .all()
    )
    return {
        pid: {"task_count": total, "progress": round((d or 0) * 100 / total) if total else 0}
        for pid, total, d in rows
    }


def project_stats(db: Session, project_id: int) -> dict:
    tasks = db.query(Task).filter(Task.project_id == project_id, Task.is_deleted == False)  # noqa: E712
    by_status = dict.fromkeys(TASK_STATUSES, 0)
    for status, n in tasks.with_entities(Task.status, func.count()).group_by(Task.status):
        by_status[status] = n
    total = sum(by_status.values())
    overdue = tasks.filter(Task.due_date != None, Task.due_date < date.today(), Task.status != "Done").count()  # noqa: E711
    return {
        "task_count": total,
        "by_status": by_status,
        "overdue": overdue,
        "progress": round(by_status["Done"] * 100 / total) if total else 0,
    }


def project_setup(db: Session, project: Project) -> dict:
    """What the Project Details setup checklist needs: is the team, plan and approval data in place?"""
    from app.models.milestones import Milestone
    from app.models.team import ProjectMember

    members = db.query(ProjectMember).filter(ProjectMember.project_id == project.id, ProjectMember.is_deleted == False).count()  # noqa: E712
    milestones = db.query(Milestone).filter(Milestone.project_id == project.id, Milestone.is_deleted == False).count()  # noqa: E712
    return {"members": members, "milestones": milestones, "missing_for_approval": missing_for_approval(project)}
