from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session

from app.core.security import Principal, get_current_principal
from app.db.session import get_db
from app.repositories import planning as repo
from app.repositories import projects as project_repo
from app.repositories import tasks as task_repo

router = APIRouter(tags=["planning"])


class ScheduleIn(BaseModel):
    start_date: Optional[date] = None  # left empty for tasks that only have a due date (Task Calendar)
    due_date: date

    @model_validator(mode="after")
    def _order(self):
        if self.start_date and self.due_date < self.start_date:
            raise ValueError("The due date cannot be before the start date")
        return self


@router.get("/projects/{project_id}/timeline")
def project_timeline(project_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    project = project_repo.get_project(db, principal, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"detail": repo.project_timeline(db, principal, project)}


@router.post("/tasks/{task_id}/schedule")
def reschedule_task(task_id: int, body: ScheduleIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    task = task_repo.get_task(db, principal, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    try:
        task = repo.reschedule(db, principal, task, body.start_date, body.due_date)
    except repo.PlanningError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    when = f"{task.start_date.strftime('%d %b')} - {task.due_date.strftime('%d %b %Y')}" if task.start_date else f"due {task.due_date.strftime('%d %b %Y')}"
    return {"detail": f"{task.task_key} rescheduled: {when}", "data": task_repo.row_for(db, principal, task.id)}


@router.get("/planning/roadmap")
def roadmap(db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return {"detail": repo.roadmap(db, principal)}


@router.get("/planning/dependencies")
def dependencies(project_id: Optional[int] = None, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    rows = repo.all_dependencies(db, principal, project_id)
    return {
        "detail": rows,
        "stack_values": {"count_pg": len(rows), "problems": sum(1 for r in rows if r["problem"]), "waiting": sum(1 for r in rows if r["is_waiting"])},
    }
