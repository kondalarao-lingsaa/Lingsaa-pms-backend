from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import Principal, get_current_principal
from app.db.session import get_db
from app.models.projects import PROJECT_PRIORITIES, PROJECT_STATUSES, PROJECT_TYPES
from app.core import access
from app.repositories import approvals
from app.repositories import projects as repo
from app.schemas.projects import ProjectIn, ReopenIn, StatusChange, project_out

router = APIRouter(prefix="/projects", tags=["projects"])

PROJECT_CATEGORIES = ["Software Development", "Implementation", "Consulting", "Support & Maintenance", "Construction", "Marketing", "Other"]
BUSINESS_DOMAINS = ["IT & Software", "Construction", "Manufacturing", "Consulting", "Healthcare", "Education", "Finance", "Government", "Retail", "Other"]


@router.get("/meta")
def project_meta(principal: Principal = Depends(get_current_principal)):
    return {
        "detail": {
            "statuses": PROJECT_STATUSES,
            "priorities": PROJECT_PRIORITIES,
            "project_types": PROJECT_TYPES,
            "categories": PROJECT_CATEGORIES,
            "business_domains": BUSINESS_DOMAINS,
        }
    }


@router.get("/list")
def list_projects(
    offset: int = Query(0, ge=0),
    page_size: int = Query(10, ge=1, le=100),
    search: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    mine: bool = False,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    rows, total, counts = repo.list_projects(
        db,
        principal,
        page=offset // page_size + 1,
        page_size=page_size,
        search=search,
        status=status,
        priority=priority,
        sort_by=sort_by,
        sort_order=sort_order,
        mine=mine,
    )
    progress = repo.progress_for(db, [p.id for p in rows])
    return {
        "detail": [{**project_out(p), **progress.get(p.id, {"task_count": 0, "progress": 0})} for p in rows],
        "stack_values": {"count_pg": total, "status_counts": counts, "all_count": sum(counts.values())},
    }


@router.get("/options")
def project_options(db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    """Every project of the company, by name - for project dropdowns (no 100-row page limit)."""
    rows = sorted(repo.all_projects(db, principal), key=lambda p: (p.project_name or "").lower())
    return {"detail": [project_out(p) for p in rows], "stack_values": {"count_pg": len(rows)}}


def _money(value):
    return round(float(value), 2) if value is not None else None


@router.get("/{project_id}")
def get_project(project_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    project = repo.get_project(db, principal, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    lim = approvals.limits(db, principal.client_id)
    approval = {
        "rule": approvals.rule_text(project, lim),
        "levels": approvals.project_levels(project, lim),
        "can_approve": project.status == "Pending Approval" and approvals.can_approve_project(db, principal, project) is None,
        "blocked_reason": approvals.can_approve_project(db, principal, project) if project.status == "Pending Approval" else None,
        # The requester (or the project's manager) may withdraw a request without giving a reason.
        "is_requester": bool(principal.user_id and principal.user_id in (project.submitted_by, project.project_manager_id, project.created_by)),
        "waiting_for": approvals.LEVEL_NAMES.get(project.approval_level) if project.status == "Pending Approval" else None,
        "history": approvals.history(db, principal, "project", project.id),
    }
    return {"detail": {**project_out(project), "stats": repo.project_stats(db, project.id), "setup": repo.project_setup(db, project), "approval": approval}}


@router.get("/{project_id}/approvals")
def project_approvals(project_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    project = repo.get_project(db, principal, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"detail": approvals.history(db, principal, "project", project.id)}


@router.post("/create", status_code=201)
def create_project(body: ProjectIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    try:
        project = repo.create_project(db, principal, body.model_dump())
    except repo.DuplicateProject as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"detail": f"Project {project.project_code} created successfully", "data": project_out(project)}


@router.put("/{project_id}")
def update_project(
    project_id: int, body: ProjectIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)
):
    project = repo.get_project(db, principal, project_id, lock=True)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.status == "Closed":
        # Same rule as its tasks, team, milestones and costs: a Closed project is kept as history.
        raise HTTPException(status_code=409, detail=f"{project.project_code} is Closed, so it can no longer change")
    access.require_runs_project(principal, project, "change this project")
    if project.status == "Pending Approval":
        raise HTTPException(status_code=409, detail=f"{project.project_code} is waiting for approval. Send it back to Draft to change it")
    if project.status != "Draft":
        # The approved plan is the baseline: budget and dates change through a Change Request, approved by the right
        # person; the type decided which approval the project needed, so it cannot change after approval either.
        if _money(body.budget) != _money(project.budget):
            raise HTTPException(status_code=409, detail="The budget was approved. Change it with a Change Request (Risks tab), so the right person approves it")
        if (body.project_type or None) != (project.project_type or None):
            raise HTTPException(status_code=409, detail="The project type was approved and cannot change. Create a new project if the work is different")
        if body.start_date != project.start_date or body.end_date != project.end_date:
            raise HTTPException(status_code=409, detail="The dates were approved. Move them with a Schedule Change Request (Risks tab)")
    try:
        project = repo.update_project(db, principal, project, body.model_dump())
    except (repo.DuplicateProject, repo.ProjectLocked) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"detail": f"Project {project.project_code} updated successfully", "data": project_out(project)}


@router.post("/{project_id}/status")
def change_project_status(
    project_id: int, body: StatusChange, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)
):
    # Locked, so a second click or a second approver at the same moment waits and then sees the new status.
    project = repo.get_project(db, principal, project_id, lock=True)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    # Approve and an approver's Send back follow the approval rules; every other move is the project manager's.
    if not (body.status == "Approved" or (project.status == "Pending Approval" and body.status == "Draft")):
        access.require_runs_project(principal, project, "move this project to " + body.status)
    try:
        project, message = repo.change_status(db, principal, project, body.status, body.remarks)
    except repo.InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"detail": message, "data": project_out(project)}


@router.post("/{project_id}/reopen")
def reopen_project(project_id: int, body: ReopenIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    project = repo.get_project(db, principal, project_id, lock=True)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        project, message = repo.reopen_project(db, principal, project, body.reason)
    except repo.InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"detail": message, "data": project_out(project)}


@router.delete("/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    project = repo.get_project(db, principal, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    access.require_runs_project(principal, project, "delete this project")
    if project.status not in ("Draft", "Pending Approval") and principal.role_key != "admin":
        # Approved work has history (hours, costs, invoices): close it instead, so the records stay.
        raise HTTPException(status_code=409, detail=f"{project.project_code} is {project.status}. Close it instead; only an Admin can delete an approved project")
    repo.delete_project(db, principal, project)
    return {"detail": f"Project {project.project_code} deleted successfully"}
