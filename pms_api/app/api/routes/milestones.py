from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core import access
from app.core.security import Principal, get_current_principal
from app.db.session import get_db
from app.models.milestones import MILESTONE_STATUSES
from app.repositories import approvals
from app.repositories import milestones as repo
from app.repositories import projects as project_repo
from app.schemas.milestones import DeliverableDoneIn, DeliverableIn, MilestoneIn, MilestoneStatusIn

router = APIRouter(tags=["milestones"])


def _project(db, principal, project_id):
    project = project_repo.get_project(db, principal, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _milestone(db, principal, project_id, milestone_id):
    milestone = repo.get_milestone(db, principal, milestone_id, project_id)
    if milestone is None:
        raise HTTPException(status_code=404, detail="Milestone not found")
    return milestone


def _rule(fn, *args):
    try:
        return fn(*args)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except repo.MilestoneError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except approvals.ApprovalError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


def _one(db, milestone):
    return repo.serialize(db, [milestone])[0]


@router.get("/milestones/meta")
def milestone_meta(principal: Principal = Depends(get_current_principal)):
    return {"detail": {"statuses": MILESTONE_STATUSES}}


@router.get("/milestones/list")
def all_milestones(
    project_id: Optional[int] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    rows = repo.list_all(db, principal, project_id=project_id, status=status, search=search)
    return {
        "detail": rows,
        "stack_values": {
            "count_pg": len(rows),
            "status_counts": {s: sum(1 for r in rows if r["status"] == s) for s in MILESTONE_STATUSES},
            "overdue": sum(1 for r in rows if r["is_overdue"]),
            "accepted_value": round(sum(r["amount"] or 0 for r in rows if r["status"] == "Accepted"), 2),
        },
    }


@router.get("/projects/{project_id}/milestones")
def project_milestones(project_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    _project(db, principal, project_id)
    rows = repo.list_for_project(db, principal, project_id)
    return {"detail": rows, "stack_values": {"count_pg": len(rows), "total_value": round(sum(r["amount"] or 0 for r in rows), 2)}}


@router.post("/projects/{project_id}/milestones", status_code=201)
def create_milestone(project_id: int, body: MilestoneIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    project = _project(db, principal, project_id)
    milestone = _rule(repo.create_milestone, db, principal, project, body.model_dump())
    return {"detail": f"Milestone '{milestone.name}' created", "data": _one(db, milestone)}


@router.put("/projects/{project_id}/milestones/{milestone_id}")
def update_milestone(
    project_id: int, milestone_id: int, body: MilestoneIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)
):
    project = _project(db, principal, project_id)
    milestone = _rule(repo.update_milestone, db, principal, project, _milestone(db, principal, project_id, milestone_id), body.model_dump())
    return {"detail": f"Milestone '{milestone.name}' updated", "data": _one(db, milestone)}


@router.delete("/projects/{project_id}/milestones/{milestone_id}")
def delete_milestone(project_id: int, milestone_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    milestone = _milestone(db, principal, project_id, milestone_id)
    _rule(repo.delete_milestone, db, principal, milestone)
    return {"detail": f"Milestone '{milestone.name}' deleted"}


@router.post("/projects/{project_id}/milestones/{milestone_id}/status")
def change_milestone_status(
    project_id: int, milestone_id: int, body: MilestoneStatusIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)
):
    milestone = _milestone(db, principal, project_id, milestone_id)
    if body.status in ("Accepted", "Changes Requested"):
        # Accepting is the client's decision (client portal); the project's manager, a Director or an Admin may record it for them.
        access.check(principal, "deliverables", "approve", what="accept milestones or ask for changes")
        _rule(approvals.require_manager, db, principal, project_id, "accept this milestone")
    milestone = _rule(repo.change_status, db, principal, milestone, body.status, body.feedback)
    if body.status in ("Accepted", "Changes Requested"):
        approvals.log(db, principal, "milestone", milestone.id, body.status, project_id=project_id, remarks=body.feedback)
        db.commit()
    return {"detail": f"'{milestone.name}' is now {milestone.status}", "data": _one(db, milestone)}


@router.post("/projects/{project_id}/milestones/{milestone_id}/deliverables", status_code=201)
def add_deliverable(
    project_id: int, milestone_id: int, body: DeliverableIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)
):
    _rule(repo.add_deliverable, db, principal, _milestone(db, principal, project_id, milestone_id), body.name)
    return {"detail": "Deliverable added"}


@router.put("/projects/{project_id}/milestones/{milestone_id}/deliverables/{deliverable_id}")
def rename_deliverable(
    project_id: int,
    milestone_id: int,
    deliverable_id: int,
    body: DeliverableIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    _rule(repo.rename_deliverable, db, principal, _milestone(db, principal, project_id, milestone_id), deliverable_id, body.name)
    return {"detail": "Deliverable renamed"}


@router.post("/projects/{project_id}/milestones/{milestone_id}/deliverables/{deliverable_id}/done")
def set_deliverable_done(
    project_id: int,
    milestone_id: int,
    deliverable_id: int,
    body: DeliverableDoneIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    _rule(repo.set_deliverable_done, db, principal, _milestone(db, principal, project_id, milestone_id), deliverable_id, body.is_done)
    return {"detail": "Deliverable done" if body.is_done else "Deliverable reopened"}


@router.delete("/projects/{project_id}/milestones/{milestone_id}/deliverables/{deliverable_id}")
def delete_deliverable(
    project_id: int, milestone_id: int, deliverable_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)
):
    _rule(repo.delete_deliverable, db, principal, _milestone(db, principal, project_id, milestone_id), deliverable_id)
    return {"detail": "Deliverable removed"}
