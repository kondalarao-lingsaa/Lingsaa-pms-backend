"""Task history and dependency blockers. Kept apart from repositories/tasks.py so both the task
workflow and the collaboration features (comments, dependencies, watchers) can use it."""
from sqlalchemy.orm import Session

from app.models.tasks import Task, TaskActivity, TaskDependency


def log_activity(db: Session, principal, task_id: int, action: str, detail: str = None) -> None:
    """Adds a history row. The caller commits, so the row is saved together with the change it describes."""
    db.add(
        TaskActivity(
            task_id=task_id,
            action=action,
            detail=(detail or "")[:1000] or None,
            actor_id=principal.user_id,
            actor_name=principal.user_name,
        )
    )


def open_blockers(db: Session, task_id: int) -> list:
    """Tasks this task depends on that are not Done yet: [(task_key, title), ...]."""
    return (
        db.query(Task.task_key, Task.title)
        .join(TaskDependency, TaskDependency.depends_on_id == Task.id)
        .filter(TaskDependency.task_id == task_id, Task.is_deleted == False, Task.status != "Done")  # noqa: E712
        .order_by(Task.task_key)
        .all()
    )


def blocked_message(blockers: list) -> str:
    keys = ", ".join(key for key, _ in blockers[:3]) + (f" and {len(blockers) - 3} more" if len(blockers) > 3 else "")
    return f"This task is blocked by {keys}. Finish {'it' if len(blockers) == 1 else 'them'} first, then mark this task Done."
