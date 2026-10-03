from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import Principal, get_current_principal
from app.db.session import get_db
from app.models.timesheets import ENTRY_STATUSES
from app.repositories import projects as project_repo
from app.repositories import timesheets as repo
from app.schemas.timesheets import EntryIn, RejectIn, ReviewIn, WeekIn, entry_out

router = APIRouter(tags=["timesheets"])


def _rule(fn, *args, **kwargs):
    """Runs a repository call and turns its rule errors into clean HTTP answers."""
    try:
        return fn(*args, **kwargs)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except repo.TimesheetError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/timesheets/meta")
def timesheet_meta(principal: Principal = Depends(get_current_principal)):
    return {"detail": {"statuses": ENTRY_STATUSES, "max_hours_per_day": 24, "step": 0.25}}


@router.get("/timesheets/my-week")
def my_week(week_start: Optional[date] = None, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    start = repo.week_start_of(week_start or date.today())
    return {"detail": repo.my_week(db, principal, start)}


@router.post("/timesheets/entries")
def save_entry(body: EntryIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    entry = _rule(repo.save_entry, db, principal, body.model_dump())
    if entry is None:
        return {"detail": "Hours cleared", "data": None}
    return {"detail": "Hours saved", "data": entry_out(entry)}


@router.post("/timesheets/submit")
def submit_week(body: WeekIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    count = _rule(repo.submit_week, db, principal, body.week_start)
    return {"detail": f"Week submitted for approval ({count} entr{'y' if count == 1 else 'ies'})"}


@router.get("/timesheets/list")
def list_entries(
    offset: int = Query(0, ge=0),
    page_size: int = Query(20, ge=1, le=100),
    project_id: Optional[int] = None,
    member: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    rows, total, totals = repo.list_entries(
        db, principal, page=offset // page_size + 1, page_size=page_size, project_id=project_id, member=member,
        status=status, date_from=date_from, date_to=date_to,
    )
    return {"detail": rows, "stack_values": {"count_pg": total, **totals}}


@router.get("/timesheets/approvals")
def approvals(project_id: Optional[int] = None, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    groups = repo.approval_queue(db, principal, project_id)
    return {"detail": groups, "stack_values": {"count_pg": len(groups), "hours": round(sum(g["hours"] for g in groups), 2)}}


@router.post("/timesheets/approve")
def approve(body: ReviewIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    count = _rule(repo.review, db, principal, body.entry_ids, True)
    return {"detail": f"{count} entr{'y' if count == 1 else 'ies'} approved"}


@router.post("/timesheets/reject")
def reject(body: RejectIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    count = _rule(repo.review, db, principal, body.entry_ids, False, body.reason)
    return {"detail": f"{count} entr{'y' if count == 1 else 'ies'} sent back to the person"}


@router.get("/projects/{project_id}/budget")
def project_budget(project_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    project = project_repo.get_project(db, principal, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    progress = project_repo.progress_for(db, [project.id]).get(project.id, {}).get("progress", 0)
    return {"detail": repo.project_budget(db, principal, project, progress)}


@router.get("/budget/overview")
def budget_overview(db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    """Every live project's budget against the cost of its approved hours."""
    projects = project_repo.all_projects(db, principal)
    progress = project_repo.progress_for(db, [p.id for p in projects])
    rows = []
    for p in projects:
        b = repo.project_budget(db, principal, p, progress.get(p.id, {}).get("progress", 0))
        rows.append({
            "project_id": p.id, "project_code": p.project_code, "project_name": p.project_name, "status": p.status,
            "budget": b["budget"], "actual_cost": b["actual_cost"], "pending_cost": b["pending_cost"], "remaining": b["remaining"],
            "used_pct": b["used_pct"], "forecast": b["forecast"], "health": b["health"], "progress": b["progress"],
            "approved_hours": b["approved_hours"],
        })
    with_budget = [r for r in rows if r["budget"] is not None]
    return {
        "detail": rows,
        "stack_values": {
            "count_pg": len(rows),
            "total_budget": round(sum(r["budget"] for r in with_budget), 2),
            "total_actual": round(sum(r["actual_cost"] for r in rows), 2),
            "total_pending": round(sum(r["pending_cost"] for r in rows), 2),
            "at_risk": sum(1 for r in rows if r["health"] in ("At risk", "Over budget")),
        },
    }
