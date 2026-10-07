"""Task Details features: comments, dependencies, watchers and history. Every function receives a
task that was already loaded through repositories.tasks.get_task, so it belongs to the caller's company."""
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.tasks import Task, TaskActivity, TaskComment, TaskDependency, TaskWatcher
from app.repositories import notifications as notification_repo
from app.repositories import tasks as task_repo
from app.repositories.task_activity import log_activity
from app.schemas.rules import utc_iso


class CollabError(Exception):
    """A rule was broken; the message is safe to show to the user."""


def _iso(value):
    return utc_iso(value)


# ------------------------------------------------------------------ comments


def list_comments(db: Session, task: Task) -> list:
    rows = (
        db.query(TaskComment)
        .filter(TaskComment.task_id == task.id, TaskComment.is_deleted == False)  # noqa: E712
        .order_by(TaskComment.created_at.asc(), TaskComment.id.asc())
        .all()
    )
    return [comment_out(c) for c in rows]


def comment_out(c: TaskComment) -> dict:
    return {"id": c.id, "body": c.body, "author_id": c.author_id, "author_name": c.author_name, "created_at": _iso(c.created_at)}


def add_comment(db: Session, principal, task: Task, body: str) -> TaskComment:
    comment = TaskComment(task_id=task.id, body=body, author_id=principal.user_id, author_name=principal.user_name)
    db.add(comment)
    db.flush()
    snippet = body[:120] + ("..." if len(body) > 120 else "")
    log_activity(db, principal, task.id, "comment", snippet)
    # @mentioned members hear about it as a mention; everyone else following the task as a comment.
    who = notification_repo.person_name(principal.user_name) or "Someone"
    common = {"body": snippet, "link": notification_repo.task_link(task.id), "project_id": task.project_id, "task_id": task.id, "comment_id": comment.id}
    mentioned = notification_repo.mentioned_members(db, task, body)
    notification_repo.notify(db, principal, mentioned, "mention", f"{who} mentioned you on {task.task_key}: {task.title}", **common)
    mentioned_keys = {(uid, (name or "").lower()) for uid, name in mentioned}
    followers = [(uid, name) for uid, name in notification_repo.task_audience(db, task)
                 if not any((uid and uid == m_uid) or (name or "").lower() == m_name for m_uid, m_name in mentioned_keys)]
    notification_repo.notify(db, principal, followers, "comment", f"{who} commented on {task.task_key}: {task.title}", **common)
    # Commenting on a task means you want to follow it.
    _ensure_watcher(db, principal, task)
    db.commit()
    db.refresh(comment)
    return comment


def delete_comment(db: Session, principal, task: Task, comment_id: int) -> None:
    comment = (
        db.query(TaskComment)
        .filter(TaskComment.id == comment_id, TaskComment.task_id == task.id, TaskComment.is_deleted == False)  # noqa: E712
        .one_or_none()
    )
    if comment is None:
        raise LookupError("Comment not found")
    if (comment.author_id is None or comment.author_id != principal.user_id) and not principal.is_superadmin:
        raise CollabError("You can only delete your own comments")
    comment.is_deleted = True
    log_activity(db, principal, task.id, "comment_deleted", "A comment was deleted")
    db.commit()


# -------------------------------------------------------------- dependencies


def _brief(t: Task) -> dict:
    return {"id": t.id, "task_key": t.task_key, "title": t.title, "status": t.status, "assignee_name": t.assignee_name}


def list_dependencies(db: Session, task: Task) -> dict:
    live = Task.is_deleted == False  # noqa: E712
    blocked_by = (
        db.query(TaskDependency.id, Task)
        .join(Task, Task.id == TaskDependency.depends_on_id)
        .filter(TaskDependency.task_id == task.id, live)
        .order_by(Task.task_key)
        .all()
    )
    blocking = (
        db.query(TaskDependency.id, Task)
        .join(Task, Task.id == TaskDependency.task_id)
        .filter(TaskDependency.depends_on_id == task.id, live)
        .order_by(Task.task_key)
        .all()
    )
    return {
        "blocked_by": [{"dependency_id": dep_id, **_brief(t)} for dep_id, t in blocked_by],
        "blocking": [{"dependency_id": dep_id, **_brief(t)} for dep_id, t in blocking],
        "open_blockers": sum(1 for _, t in blocked_by if t.status != "Done"),
    }


def _depends_on_path(db: Session, start_id: int, target_id: int) -> bool:
    """True if start_id already (directly or indirectly) depends on target_id."""
    seen, frontier = set(), [start_id]
    while frontier:
        current = frontier.pop()
        if current == target_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        frontier.extend(row[0] for row in db.query(TaskDependency.depends_on_id).filter(TaskDependency.task_id == current))
    return False


def add_dependency(db: Session, principal, task: Task, depends_on_id: int) -> None:
    try:
        task_repo._ensure_open(db, task.project_id)
    except task_repo.TaskError as exc:
        raise CollabError(str(exc)) from exc
    if depends_on_id == task.id:
        raise CollabError("A task cannot depend on itself")
    other = task_repo.get_task(db, principal, depends_on_id)
    if other is None:
        raise CollabError("The task you picked was not found")
    if other.project_id != task.project_id:
        raise CollabError("Dependencies can only link tasks of the same project")
    # Held until commit: two links added at the same moment are checked one after the other, so they cannot
    # close a loop between them (A waits for B while B waits for A).
    db.execute(
        text("EXEC sp_getapplock @Resource = :r, @LockMode = 'Exclusive', @LockOwner = 'Transaction', @LockTimeout = 15000"),
        {"r": f"pms_deps_{task.project_id}"},
    )
    exists = db.query(TaskDependency).filter(TaskDependency.task_id == task.id, TaskDependency.depends_on_id == other.id).first()
    if exists:
        raise CollabError(f"{task.task_key} already depends on {other.task_key}")
    # Would the new link close a loop (A waits for B, B waits for A)?
    if _depends_on_path(db, other.id, task.id):
        raise CollabError(f"{other.task_key} already waits for {task.task_key}, so this would create a loop")
    db.add(TaskDependency(task_id=task.id, depends_on_id=other.id, dependency_type="blocks"))
    log_activity(db, principal, task.id, "dependency", f"Now blocked by {other.task_key}")
    db.commit()


def remove_dependency(db: Session, principal, task: Task, dependency_id: int) -> None:
    try:
        task_repo._ensure_open(db, task.project_id)
    except task_repo.TaskError as exc:
        raise CollabError(str(exc)) from exc
    dep = (
        db.query(TaskDependency)
        .filter(TaskDependency.id == dependency_id)
        .filter((TaskDependency.task_id == task.id) | (TaskDependency.depends_on_id == task.id))
        .one_or_none()
    )
    if dep is None:
        raise LookupError("Dependency not found")
    other_id = dep.depends_on_id if dep.task_id == task.id else dep.task_id
    other_key = db.query(Task.task_key).filter(Task.id == other_id).scalar()
    db.delete(dep)
    log_activity(db, principal, task.id, "dependency_removed", f"Link with {other_key} removed")
    db.commit()


# ------------------------------------------------------------------ watchers


def list_watchers(db: Session, task: Task) -> list:
    rows = db.query(TaskWatcher).filter(TaskWatcher.task_id == task.id).order_by(TaskWatcher.id).all()
    return [{"user_id": w.user_id, "user_name": w.user_name} for w in rows]


def _ensure_watcher(db: Session, principal, task: Task) -> bool:
    if principal.user_id is None:
        return False
    exists = db.query(TaskWatcher).filter(TaskWatcher.task_id == task.id, TaskWatcher.user_id == principal.user_id).first()
    if exists:
        return False
    db.add(TaskWatcher(task_id=task.id, user_id=principal.user_id, user_name=principal.user_name))
    return True


def set_watching(db: Session, principal, task: Task, watching: bool) -> None:
    if principal.user_id is None:
        raise CollabError("Your session has no user id, so you cannot watch tasks")
    if watching:
        _ensure_watcher(db, principal, task)
    else:
        db.query(TaskWatcher).filter(TaskWatcher.task_id == task.id, TaskWatcher.user_id == principal.user_id).delete()
    db.commit()


# ------------------------------------------------------------------- history


def list_activity(db: Session, task: Task, limit: int = 200) -> list:
    rows = (
        db.query(TaskActivity)
        .filter(TaskActivity.task_id == task.id)
        .order_by(TaskActivity.created_at.desc(), TaskActivity.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {"id": a.id, "action": a.action, "detail": a.detail, "actor_name": a.actor_name, "created_at": _iso(a.created_at)}
        for a in rows
    ]
