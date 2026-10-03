from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.security import Principal, get_current_principal
from app.db.session import get_db
from app.repositories import projects as project_repo
from app.repositories import sprints as repo
from app.schemas.rules import capitalize_first, title_text

router = APIRouter(tags=["sprints"])


class SprintIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    goal: Optional[str] = Field(default=None, max_length=1000)
    start_date: date
    end_date: date

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        return title_text(v, "Sprint name", required=True, min_len=2)

    @field_validator("goal")
    @classmethod
    def _goal(cls, v):
        return capitalize_first(" ".join(v.split())) if v else None


class TaskIdsIn(BaseModel):
    task_ids: List[int] = Field(min_length=1, max_length=200)


class CompleteIn(BaseModel):
    move_to_sprint_id: Optional[int] = None


def _project(db, principal, project_id):
    project = project_repo.get_project(db, principal, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _sprint(db, principal, sprint_id):
    sprint = repo.get_sprint(db, principal, sprint_id)
    if sprint is None:
        raise HTTPException(status_code=404, detail="Sprint not found")
    return sprint


def _rule(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except repo.SprintError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/projects/{project_id}/sprints")
def project_sprints(project_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    _project(db, principal, project_id)
    rows = repo.list_sprints(db, principal, project_id)
    history = repo.velocity(db, principal, project_id)
    return {
        "detail": rows,
        "stack_values": {
            "count_pg": len(rows),
            "active_id": next((s["id"] for s in rows if s["status"] == "Active"), None),
            "velocity": history,
            "average_velocity": round(sum(v["completed"] for v in history) / len(history), 1) if history else None,
        },
    }


@router.post("/projects/{project_id}/sprints", status_code=201)
def create_sprint(project_id: int, body: SprintIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    sprint = _rule(repo.create_sprint, db, principal, _project(db, principal, project_id), body.model_dump())
    return {"detail": f"{sprint.name} created", "data": repo.sprint_out(db, sprint)}


@router.put("/sprints/{sprint_id}")
def update_sprint(sprint_id: int, body: SprintIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    sprint = _sprint(db, principal, sprint_id)
    sprint = _rule(repo.update_sprint, db, principal, _project(db, principal, sprint.project_id), sprint, body.model_dump())
    return {"detail": f"{sprint.name} updated", "data": repo.sprint_out(db, sprint)}


@router.delete("/sprints/{sprint_id}")
def delete_sprint(sprint_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    sprint = _sprint(db, principal, sprint_id)
    _rule(repo.delete_sprint, db, principal, sprint)
    return {"detail": f"{sprint.name} deleted; its tasks are back in the backlog"}


@router.post("/sprints/{sprint_id}/tasks")
def add_tasks(sprint_id: int, body: TaskIdsIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    sprint = _sprint(db, principal, sprint_id)
    moved = _rule(repo.add_tasks, db, principal, sprint, body.task_ids)
    return {"detail": f"{moved} task{'s' if moved != 1 else ''} added to {sprint.name}", "data": repo.sprint_out(db, sprint)}


@router.delete("/sprints/{sprint_id}/tasks/{task_id}")
def remove_task(sprint_id: int, task_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    sprint = _sprint(db, principal, sprint_id)
    _rule(repo.remove_task, db, principal, sprint, task_id)
    return {"detail": "Task moved back to the backlog", "data": repo.sprint_out(db, sprint)}


@router.post("/sprints/{sprint_id}/start")
def start_sprint(sprint_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    sprint = _sprint(db, principal, sprint_id)
    sprint = _rule(repo.start_sprint, db, principal, _project(db, principal, sprint.project_id), sprint)
    return {"detail": f"{sprint.name} started", "data": repo.sprint_out(db, sprint)}


@router.post("/sprints/{sprint_id}/complete")
def complete_sprint(sprint_id: int, body: CompleteIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    sprint = _sprint(db, principal, sprint_id)
    result = _rule(repo.complete_sprint, db, principal, _project(db, principal, sprint.project_id), sprint, body.move_to_sprint_id)
    moved = f" {result['moved']} unfinished task{'s' if result['moved'] != 1 else ''} moved to {result['to']}." if result["moved"] else ""
    return {"detail": f"{sprint.name} completed: {result['done']} of {result['committed']} tasks done.{moved}", "data": repo.sprint_out(db, sprint)}


@router.get("/sprints/{sprint_id}/burndown")
def burndown(sprint_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return {"detail": repo.burndown(db, principal, _sprint(db, principal, sprint_id))}


@router.get("/projects/{project_id}/backlog")
def project_backlog(project_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    _project(db, principal, project_id)
    rows = repo.backlog(db, principal, project_id)
    return {"detail": rows, "stack_values": {"count_pg": len(rows), "estimated_hours": round(sum(t["estimated_hours"] or 0 for t in rows), 2),
                                             "unestimated": sum(1 for t in rows if not t["estimated_hours"])}}
