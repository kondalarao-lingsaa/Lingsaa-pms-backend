from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core import access
from app.core.access import can_see_rates
from app.core.security import Principal, get_current_principal
from app.db.session import get_db
from app.repositories import projects as project_repo
from app.repositories import team as repo
from app.schemas.team import MemberIn, member_out

router = APIRouter(tags=["team"])


def _project(db, principal, project_id, *, for_change=False):
    project = project_repo.get_project(db, principal, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if for_change and project.status == "Closed":
        raise HTTPException(status_code=409, detail=f"{project.project_code} is Closed, so its team can no longer change")
    return project


def _team_change(principal, project):
    """The team is changed by the project's manager, a Director/Admin or a Resource Manager (who staffs projects)."""
    if getattr(principal, "role_key", None) != "resource_manager":
        access.require_runs_project(principal, project, "change its team")


def _member(db, principal, project_id, member_id):
    member = repo.get_member(db, principal, project_id, member_id)
    if member is None:
        raise HTTPException(status_code=404, detail="Team member not found")
    return member


@router.get("/team/meta")
def team_meta(db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    from app.repositories.settings import company_roles

    # people: the company's login users a team member can be linked to (picked in the Add Member form).
    return {"detail": {"roles": company_roles(db, principal.client_id), "people": repo.company_people(db, principal)}}


@router.get("/projects/{project_id}/members")
def list_members(project_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    _project(db, principal, project_id)
    members = repo.list_members(db, principal, project_id)
    if not can_see_rates(principal):
        # Pay rates are money: only roles that see the budget see them.
        for m in members:
            m["hourly_rate"] = m["bill_rate"] = None
    return {"detail": members, "stack_values": {"count_pg": len(members), "total_allocation": sum(m["allocation_pct"] for m in members)}}


@router.post("/projects/{project_id}/members", status_code=201)
def add_member(project_id: int, body: MemberIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    project = _project(db, principal, project_id, for_change=True)
    _team_change(principal, project)
    data = body.model_dump()
    if not can_see_rates(principal):
        data["hourly_rate"] = data["bill_rate"] = None  # a role that cannot see rates cannot set one either
    try:
        member = repo.create_member(db, principal, project, data)
    except repo.TeamError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    out = member_out(member)
    if not can_see_rates(principal):
        out["hourly_rate"] = out["bill_rate"] = None
    return {"detail": f"{member.member_name} added to {project.project_code}", "data": out}


@router.put("/projects/{project_id}/members/{member_id}")
def update_member(
    project_id: int, member_id: int, body: MemberIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)
):
    project = _project(db, principal, project_id, for_change=True)
    _team_change(principal, project)
    member = _member(db, principal, project_id, member_id)
    data = body.model_dump()
    if not can_see_rates(principal):
        # The rates are hidden from this role, so its form cannot send them: keep what is stored.
        data["hourly_rate"], data["bill_rate"] = member.hourly_rate, member.bill_rate
    try:
        member = repo.update_member(db, principal, project, member, data)
    except repo.TeamError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    out = member_out(member)
    if not can_see_rates(principal):
        out["hourly_rate"] = out["bill_rate"] = None
    return {"detail": f"{member.member_name} updated", "data": out}


@router.delete("/projects/{project_id}/members/{member_id}")
def remove_member(project_id: int, member_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    project = _project(db, principal, project_id, for_change=True)
    _team_change(principal, project)
    member = _member(db, principal, project_id, member_id)
    try:
        repo.remove_member(db, principal, member)
    except repo.TeamError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"detail": f"{member.member_name} removed from the team"}


@router.get("/resources/allocation")
def resource_allocation(
    search: Optional[str] = None,
    over_only: bool = False,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    people = repo.allocation_overview(db, principal, search=search, over_only=over_only)
    return {
        "detail": people,
        "stack_values": {
            "count_pg": len(people),
            "full": sum(1 for p in people if p["load"] == "Full"),
            "high": sum(1 for p in people if p["load"] == "High"),
            "available": sum(1 for p in people if p["load"] == "Available"),
        },
    }
