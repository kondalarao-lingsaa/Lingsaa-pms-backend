from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import Principal, get_current_principal
from app.db.session import get_db
from app.repositories import workload as repo

router = APIRouter(tags=["workload"])


def _run(fn, *args, **kwargs):
    try:
        return {"detail": fn(*args, **kwargs)}
    except repo.WorkloadError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/calendar")
def task_calendar(
    date_from: date,
    date_to: date,
    project_id: Optional[int] = None,
    mine: bool = False,
    assignee: Optional[str] = Query(None, max_length=200),
    include_done: bool = True,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return _run(repo.calendar, db, principal, date_from, date_to, project_id=project_id, mine=mine, assignee=assignee or None, include_done=include_done)


@router.get("/resources/capacity")
def resource_capacity(
    start: Optional[date] = None,
    weeks: int = 8,
    project_id: Optional[int] = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return _run(repo.capacity, db, principal, start=start, weeks=weeks, project_id=project_id)


@router.get("/resources/utilization")
def resource_utilization(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    project_id: Optional[int] = None,
    person: Optional[str] = Query(None, max_length=100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return _run(repo.utilization, db, principal, start=date_from, end=date_to, project_id=project_id, person=(person or "").strip() or None)
