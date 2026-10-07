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


def get_project(db, principal, project_id, lock=False):
    """lock=True holds the project row (UPDLOCK) until the request commits, so two status changes or approvals of
    the same project at the same moment run one after the other and the second sees the first's result."""
    if lock:
        db.execute(text("SELECT id FROM projectmanagement.projects WITH (UPDLOCK, ROWLOCK) WHERE id = :id"), {"id": project_id})
        return _scoped(db, principal).filter(Project.id == project_id).populate_existing().one_or_none()
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


def _lock_names(db: Session, client_id: int) -> None:
    """Holds the company's project counter (the same lock _next_project_code takes) until commit, so a name check
    and the save that follows cannot interleave with another create or rename of the same company."""
    db.execute(
        text("SELECT last_no FROM projectmanagement.project_counters WITH (UPDLOCK, HOLDLOCK) WHERE client_id = :c AND year = :y"),
        {"c": client_id, "y": date.today().year},
    )


def _ensure_unique_name(db, principal, name: str, own_id=None):
    # Company-wide, not only the projects this person can see: names must not repeat in the company.
    _lock_names(db, principal.client_id)
    query = db.query(Project).filter(
        Project.client_id == principal.client_id, Project.is_deleted == False, func.lower(Project.project_name) == name.lower()  # noqa: E712
    )
    if own_id:
        query = query.filter(Project.id != own_id)
    if query.first() is not None:
        raise DuplicateProject(f"A project named '{name}' already exists")


def _link_manager(db, principal, data: dict) -> None:
    """The manager runs and sees the project through their login user id. A name typed without picking it from the
    list still links when it is exactly one login user's name (otherwise the manager could not open the project)."""
    if data.get("project_manager_id") or not (data.get("project_manager_name") or "").strip():
        return
    name = data["project_manager_name"].strip().lower()
    matches = [p for p in team_repo.company_people(db, principal) if p["name"].strip().lower() == name]
    if len(matches) == 1:
        data["project_manager_id"] = matches[0]["user_id"]


def create_project(db, principal, data: dict, commit=True) -> Project:
    """commit=False lets a caller (create from template) add milestones/tasks and commit everything at once."""
    _ensure_unique_name(db, principal, data["project_name"])
    _link_manager(db, principal, data)
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
    _link_manager(db, principal, data)
    if (data.get("customer_name") or "").strip().lower() != (project.customer_name or "").strip().lower():
        # The client portal finds invoices by the project's customer: renaming it would hand issued invoices
        # to another client and hide them from the one they were sent to.
        from app.models.billing import Invoice

        sent = db.query(Invoice.invoice_no).filter(Invoice.project_id == project.id, Invoice.is_deleted == False,  # noqa: E712
                                                   Invoice.status.in_(("Issued", "Paid"))).first()
        if sent:
            raise ProjectLocked(f"The client cannot be changed: invoice {sent[0]} was already issued to {project.customer_name}")
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


class ProjectLocked(Exception):
    """A change that would rewrite something already sent out (e.g. the client of an issued invoice)."""


def reopen_project(db, principal, project: Project, reason: str) -> tuple:
    """Closed -> Active, for a project closed by mistake. Only an Admin or Director may, always with a reason;
    the reopening is kept in the approval history and the project manager is told."""
    from app.core import roles
    from app.repositories import approvals, notifications as notification_repo  # local import: both read the project model

    if project.status != "Closed":
        raise InvalidTransition(f"{project.project_code} is {project.status}. Only a Closed project can be reopened")
    if getattr(principal, "role_key", None) not in (roles.ADMIN, roles.DIRECTOR):
        raise InvalidTransition("Only an Admin or a Director can reopen a closed project")
    project.status = "Active"
    project.updated_by = principal.user_id
    approvals.log(db, principal, "project", project.id, "Reopened", project_id=project.id, remarks=reason)
    name = notification_repo.person_name(principal.user_name) or principal.user_name
    notification_repo.notify(
        db, principal, [(project.project_manager_id, project.project_manager_name), (project.approved_by, project.approved_by_name)], "approval",
        f"{name} reopened {project.project_code} {project.project_name}", body=reason,
        link=f"projects/projectDetails/?id={project.id}", project_id=project.id,
    )
    db.commit()
    db.refresh(project)
    return project, f"{project.project_code} is reopened and Active again"


def close_blockers(db, project: Project) -> list:
    """What still waits for a decision on a project. Once Closed nothing can change, so these would be stuck:
    hours, expenses and change requests waiting for approval, and invoices still in Draft."""
    from app.models.billing import Invoice
    from app.models.expenses import Expense
    from app.models.risks import ChangeRequest
    from app.models.timesheets import TimeEntry

    checks = [
        (TimeEntry, TimeEntry.status == "Submitted", "timesheet entries waiting for approval"),
        (Expense, Expense.status == "Submitted", "expenses waiting for approval"),
        (ChangeRequest, ChangeRequest.status == "Submitted", "change requests waiting for a decision"),
        (Invoice, Invoice.status == "Draft", "Draft invoices (issue or cancel them)"),
    ]
    found = []
    for model, cond, label in checks:
        n = db.query(func.count(model.id)).filter(model.project_id == project.id, model.is_deleted == False, cond).scalar()  # noqa: E712
        if n:
            found.append(f"{n} {label}" if n > 1 else f"1 {label.replace('entries', 'entry').replace('expenses', 'expense').replace('requests', 'request').replace('invoices', 'invoice')}")
    # A running sprint would be left half done (its unfinished tasks never go back to the backlog).
    from app.models.sprints import Sprint

    for (name,) in db.query(Sprint.name).filter(Sprint.project_id == project.id, Sprint.is_deleted == False, Sprint.status == "Active"):  # noqa: E712
        found.append(f"Sprint {name} is still active (complete it first)")
    return found


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
            if new_status == "Closed":
                blockers = close_blockers(db, project)
                if blockers:
                    raise InvalidTransition(f"{project.project_code} cannot be closed yet: {'; '.join(blockers)}")
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
