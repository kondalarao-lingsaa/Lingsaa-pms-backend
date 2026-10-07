"""Company-wide conversation views: every task comment, my @mentions, and the activity feed of all tasks."""
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.notifications import Notification
from app.models.projects import Project
from app.models.tasks import Task, TaskActivity, TaskComment
from app.repositories import notifications as notification_repo
from app.repositories.search import ESC, escape_like
from app.schemas.rules import utc_iso
from app.core.access import project_scope

# Activity actions grouped the way people filter them.
ACTION_GROUPS = {
    "created": ["created"],
    "status": ["status"],
    "updated": ["updated"],
    "comment": ["comment", "comment_deleted"],
    "dependency": ["dependency", "dependency_removed"],
    "time": ["time"],
    "sprint": ["sprint"],
    "deleted": ["deleted"],
}


def comments(db: Session, principal, *, project_id=None, search=None, involving_me=False, offset=0, limit=10):
    query = (
        db.query(TaskComment, Task.task_key, Task.title, Task.project_id, Project.project_code, Project.project_name)
        .join(Task, Task.id == TaskComment.task_id)
        .join(Project, Project.id == Task.project_id)
        .filter(Task.client_id == principal.client_id, Task.is_deleted == False, Project.is_deleted == False, project_scope(db, principal), TaskComment.is_deleted == False)  # noqa: E712
    )
    if project_id:
        query = query.filter(Task.project_id == project_id)
    if search:
        like = f"%{escape_like(search)}%"
        query = query.filter(or_(TaskComment.body.ilike(like, escape=ESC), Task.title.ilike(like, escape=ESC), Task.task_key.ilike(like, escape=ESC),
                                 TaskComment.author_name.ilike(like, escape=ESC)))
    if involving_me:
        # Comments I wrote, on tasks assigned to me, or that mention me.
        mentioned_ids = [cid for (cid,) in notification_repo.mine(db, principal).filter(Notification.kind == "mention", Notification.comment_id != None).with_entities(Notification.comment_id)]  # noqa: E711
        conds = [TaskComment.id.in_(mentioned_ids or [-1])]
        if principal.user_id:
            conds += [TaskComment.author_id == principal.user_id, Task.assignee_id == principal.user_id]
        query = query.filter(or_(*conds))
    total = query.count()
    rows = query.order_by(TaskComment.created_at.desc(), TaskComment.id.desc()).offset(offset).limit(limit).all()
    return [
        {"id": c.id, "body": c.body, "author_id": c.author_id, "author_name": notification_repo.person_name(c.author_name) or c.author_name,
         "created_at": utc_iso(c.created_at), "task_id": c.task_id, "task_key": key, "task_title": title, "project_id": pid,
         "project_code": code, "project_name": pname}
        for c, key, title, pid, code, pname in rows
    ], total


def mentions(db: Session, principal, *, unread_only=False, offset=0, limit=10):
    query = notification_repo.mine(db, principal).filter(Notification.kind == "mention")
    unread = query.filter(Notification.is_read == False).count()  # noqa: E712
    if unread_only:
        query = query.filter(Notification.is_read == False)  # noqa: E712
    total = query.count()
    rows = query.order_by(Notification.created_at.desc(), Notification.id.desc()).offset(offset).limit(limit).all()
    bodies = dict(db.query(TaskComment.id, TaskComment.body).filter(TaskComment.id.in_([n.comment_id for n in rows if n.comment_id] or [-1]), TaskComment.is_deleted == False).all())  # noqa: E712
    tasks = {t.id: t for t in db.query(Task).filter(Task.id.in_([n.task_id for n in rows if n.task_id] or [-1]))}
    codes = dict(db.query(Project.id, Project.project_code).filter(Project.id.in_([n.project_id for n in rows if n.project_id] or [-1])).all())
    out = []
    for n in rows:
        t = tasks.get(n.task_id)
        out.append({**notification_repo.notification_out(n), "comment": bodies.get(n.comment_id), "comment_deleted": n.comment_id not in bodies,
                    "task_key": t.task_key if t else None, "task_title": t.title if t else None, "task_status": t.status if t else None,
                    "project_code": codes.get(n.project_id)})
    return out, total, unread


def activity(db: Session, principal, *, project_id=None, action=None, actor=None, search=None, offset=0, limit=30):
    query = (
        db.query(TaskActivity, Task.task_key, Task.title, Task.project_id, Task.is_deleted, Project.project_code)
        .join(Task, Task.id == TaskActivity.task_id)
        .join(Project, Project.id == Task.project_id)
        .filter(Task.client_id == principal.client_id, Project.is_deleted == False, project_scope(db, principal))  # noqa: E712
    )
    if project_id:
        query = query.filter(Task.project_id == project_id)
    if action:
        cond = TaskActivity.action.in_(ACTION_GROUPS.get(action, [action]))
        if action == "status":
            # A status changed in the Edit Task form is logged inside an "updated" row ("Status: To Do -> Done; ...").
            cond = or_(cond, (TaskActivity.action == "updated") & TaskActivity.detail.like("%Status: %"))
        query = query.filter(cond)
    if actor:
        query = query.filter(func.lower(TaskActivity.actor_name) == actor.lower())
    if search:
        like = f"%{escape_like(search)}%"
        query = query.filter(or_(TaskActivity.detail.ilike(like, escape=ESC), Task.title.ilike(like, escape=ESC), Task.task_key.ilike(like, escape=ESC)))
    total = query.count()
    rows = query.order_by(TaskActivity.created_at.desc(), TaskActivity.id.desc()).offset(offset).limit(limit).all()
    return [
        {"id": a.id, "action": a.action, "detail": a.detail, "actor_name": notification_repo.person_name(a.actor_name) or a.actor_name or "System",
         "created_at": utc_iso(a.created_at), "task_id": a.task_id, "task_key": key, "task_title": title, "task_deleted": bool(deleted),
         "project_id": pid, "project_code": code}
        for a, key, title, pid, deleted, code in rows
    ], total


def actors(db: Session, principal) -> list:
    rows = (
        db.query(TaskActivity.actor_name)
        .join(Task, Task.id == TaskActivity.task_id)
        .filter(Task.client_id == principal.client_id, TaskActivity.actor_name != None)  # noqa: E711
        .distinct()
        .all()
    )
    # value = what is stored (login name), label = how people read it.
    return [{"value": v, "label": notification_repo.person_name(v) or v} for v in sorted({r[0] for r in rows if r[0]}, key=str.lower)]
