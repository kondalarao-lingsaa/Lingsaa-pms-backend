from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import Principal, get_current_principal
from app.db.session import get_db
from app.models.tasks import TASK_PRIORITIES, TASK_STATUSES, TASK_TYPES
from app.repositories import task_collab as collab
from app.repositories import tasks as repo
from app.schemas.tasks import CommentIn, DependencyIn, TaskIn, TaskMove, TaskStatusChange, WatchIn

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _found(db, principal, task_id):
    task = repo.get_task(db, principal, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/meta")
def task_meta(principal: Principal = Depends(get_current_principal)):
    return {"detail": {"statuses": TASK_STATUSES, "priorities": TASK_PRIORITIES, "types": TASK_TYPES}}


@router.get("/list")
def list_tasks(
    offset: int = Query(0, ge=0),
    # Up to 1000 so one project's task pickers (parent, dependency, sprint) see every task, not just the first 100.
    page_size: int = Query(10, ge=1, le=1000),
    search: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    project_id: Optional[int] = None,
    mine: bool = False,
    top_level: bool = False,
    sprint_id: Optional[int] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    rows, total, counts, overdue = repo.list_tasks(
        db, principal, page=offset // page_size + 1, page_size=page_size, search=search, status=status, priority=priority,
        project_id=project_id, mine=mine, top_level=top_level, sprint_id=sprint_id, sort_by=sort_by, sort_order=sort_order,
    )
    return {"detail": rows, "stack_values": {"count_pg": total, "status_counts": counts, "all_count": sum(counts.values()), "overdue": overdue}}


@router.get("/board")
def task_board(
    project_id: Optional[int] = None,
    mine: bool = False,
    search: Optional[str] = None,
    priority: Optional[str] = None,
    assignee: Optional[str] = None,
    sprint_id: Optional[int] = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    columns, total, truncated = repo.board(db, principal, project_id=project_id, mine=mine, search=search, priority=priority, assignee=assignee, sprint_id=sprint_id)
    return {
        "detail": [{"status": status, "tasks": tasks} for status, tasks in columns.items()],
        "stack_values": {"count_pg": total, "truncated": truncated, "limit": repo.BOARD_LIMIT},
    }


@router.get("/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    detail = repo.get_detail(db, principal, task_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"detail": detail}


@router.post("/create", status_code=201)
def create_task(body: TaskIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    try:
        task = repo.create_task(db, principal, body.model_dump())
    except repo.TaskError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"detail": f"Task {task.task_key} created successfully", "data": repo.row_for(db, principal, task.id)}


@router.put("/{task_id}")
def update_task(task_id: int, body: TaskIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    task = _found(db, principal, task_id)
    try:
        task = repo.update_task(db, principal, task, body.model_dump())
    except repo.TaskConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except repo.TaskError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"detail": f"Task {task.task_key} updated successfully", "data": repo.row_for(db, principal, task.id)}


@router.post("/{task_id}/status")
def change_task_status(task_id: int, body: TaskStatusChange, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    try:
        task = repo.change_status(db, principal, _found(db, principal, task_id), body.status)
    except repo.TaskError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"detail": f"{task.task_key} moved to {task.status}", "data": repo.row_for(db, principal, task.id)}


@router.delete("/{task_id}")
def delete_task(task_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    task = _found(db, principal, task_id)
    try:
        repo.delete_task(db, principal, task)
    except repo.TaskError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"detail": f"Task {task.task_key} deleted successfully"}


@router.post("/{task_id}/move")
def move_task(task_id: int, body: TaskMove, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    try:
        task = repo.move_task(db, principal, _found(db, principal, task_id), body.status, body.prev_id, body.next_id)
    except repo.TaskError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"detail": f"{task.task_key} moved to {task.status}", "data": repo.row_for(db, principal, task.id)}


# ---------------------------------------------------------------- Task Details: comments


@router.get("/{task_id}/comments")
def list_comments(task_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return {"detail": collab.list_comments(db, _found(db, principal, task_id))}


@router.post("/{task_id}/comments", status_code=201)
def add_comment(task_id: int, body: CommentIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    comment = collab.add_comment(db, principal, _found(db, principal, task_id), body.body)
    return {"detail": "Comment added", "data": collab.comment_out(comment)}


@router.delete("/{task_id}/comments/{comment_id}")
def delete_comment(task_id: int, comment_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    try:
        collab.delete_comment(db, principal, _found(db, principal, task_id), comment_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except collab.CollabError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return {"detail": "Comment deleted"}


# ------------------------------------------------------------ Task Details: dependencies


@router.get("/{task_id}/dependencies")
def list_dependencies(task_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return {"detail": collab.list_dependencies(db, _found(db, principal, task_id))}


@router.post("/{task_id}/dependencies", status_code=201)
def add_dependency(task_id: int, body: DependencyIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    task = _found(db, principal, task_id)
    try:
        collab.add_dependency(db, principal, task, body.depends_on_id)
    except collab.CollabError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"detail": "Dependency added"}


@router.delete("/{task_id}/dependencies/{dependency_id}")
def remove_dependency(task_id: int, dependency_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    try:
        collab.remove_dependency(db, principal, _found(db, principal, task_id), dependency_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except collab.CollabError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"detail": "Dependency removed"}


# -------------------------------------------------------- Task Details: watchers, history


@router.get("/{task_id}/watchers")
def list_watchers(task_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    watchers = collab.list_watchers(db, _found(db, principal, task_id))
    return {"detail": watchers, "stack_values": {"is_watching": any(w["user_id"] == principal.user_id for w in watchers)}}


@router.post("/{task_id}/watch")
def set_watching(task_id: int, body: WatchIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    try:
        collab.set_watching(db, principal, _found(db, principal, task_id), body.watching)
    except collab.CollabError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"detail": "You are now watching this task" if body.watching else "You stopped watching this task"}


@router.get("/{task_id}/activity")
def list_activity(task_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return {"detail": collab.list_activity(db, _found(db, principal, task_id))}
