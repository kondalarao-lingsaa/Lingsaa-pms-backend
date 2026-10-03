"""Notifications: who hears about what.

- @mention in a comment      -> the mentioned team member ("mention")
- new comment on a task      -> watchers, assignee and reporter ("comment"), unless already mentioned
- task assigned              -> the new assignee ("assigned")
- task status changed        -> watchers, assignee and reporter ("status")
- timesheet approved/rejected -> the person who logged the hours ("timesheet")

Nobody is notified about their own action. Rows are added to the caller's session; the caller commits."""
import re

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.core import mailer
from app.models.notifications import Notification
from app.models.tasks import Task, TaskWatcher
from app.models.team import ProjectMember
from app.schemas.rules import utc_iso


def person_name(username) -> str:
    """"dev.user" -> "Dev User": login names as people read them."""
    return " ".join(p.capitalize() for p in re.split(r"[._\s]+", (username or "").strip()) if p)


def task_link(task_id) -> str:
    return f"tasks/taskDetails/?id={task_id}"


def _same(a, b) -> bool:
    return bool(a) and bool(b) and a.strip().lower() == b.strip().lower()


def _is_actor(principal, user_id, name) -> bool:
    if user_id and principal.user_id and user_id == principal.user_id:
        return True
    return _same(name, principal.user_name) or _same(name, person_name(principal.user_name))


def notify(db: Session, principal, recipients, kind, title, body=None, link=None, project_id=None, task_id=None, comment_id=None) -> int:
    """recipients: iterable of (user_id, name). Duplicates and the actor are skipped. Returns how many were added."""
    seen, added, emails = set(), 0, []
    for user_id, name in recipients:
        if not user_id and not name:
            continue
        key = f"u{user_id}" if user_id else f"n{name.strip().lower()}"
        if key in seen or _is_actor(principal, user_id, name):
            continue
        seen.add(key)
        db.add(Notification(
            client_id=principal.client_id, recipient_user_id=user_id, recipient_name=name, kind=kind, title=title[:300],
            body=(body or "")[:1000] or None, link=link, project_id=project_id, task_id=task_id, comment_id=comment_id,
            actor_id=principal.user_id, actor_name=person_name(principal.user_name) or principal.user_name,
        ))
        added += 1
        if user_id and kind in mailer.alert_kinds():
            emails.append((user_id, title, body, link))
    _email(db, principal, emails)
    return added


def _email(db, principal, items) -> None:
    """Emails the alert to people whose address is in Settings > Users & Roles."""
    if not items:
        return
    from app.models.access import UserRole  # local import: access models import this module's neighbours

    addresses = dict(db.query(UserRole.user_id, UserRole.email).filter(
        UserRole.client_id == principal.client_id, UserRole.user_id.in_({i[0] for i in items}), UserRole.is_active == True,  # noqa: E712
        UserRole.email != None,  # noqa: E711
    ).all())
    for user_id, title, body, link in items:
        if addresses.get(user_id):
            text = "\n\n".join(p for p in (title, body, f"Open: {mailer.app_link(link)}", "LINGSAA PMS") if p)
            mailer.send(addresses[user_id], f"[PMS] {title}", text)


def task_audience(db: Session, task: Task) -> list:
    """People following a task: its watchers, assignee and reporter."""
    people = [(w.user_id, w.user_name) for w in db.query(TaskWatcher).filter(TaskWatcher.task_id == task.id)]
    people.append((task.assignee_id, task.assignee_name))
    people.append((task.reporter_id, task.reporter_name))
    return people


def mentioned_members(db: Session, task: Task, body: str) -> list:
    """Team members of the task's project written as @Full Name in the text: [(user_id, name), ...]."""
    members = (
        db.query(ProjectMember.user_id, ProjectMember.member_name)
        .filter(ProjectMember.project_id == task.project_id, ProjectMember.is_deleted == False)  # noqa: E712
        .all()
    )
    # Longest names first, so "@Anita Rao" is not also read as a mention of a member called "Anita".
    found, text = [], body
    for user_id, name in sorted(members, key=lambda m: -len(m[1])):
        pattern = re.compile(r"@" + re.escape(name) + r"(?![\w])", re.IGNORECASE)
        if pattern.search(text):
            found.append((user_id, name))
            text = pattern.sub(" ", text)
    return found


# ------------------------------------------------------------------------------ reading


def _my_names(db: Session, principal) -> list:
    names = {n.lower() for n in (principal.user_name, person_name(principal.user_name)) if n}
    if principal.user_id:
        names |= {n.lower() for (n,) in db.query(ProjectMember.member_name).filter(ProjectMember.client_id == principal.client_id, ProjectMember.user_id == principal.user_id, ProjectMember.is_deleted == False)}  # noqa: E712
    return sorted(names)


def mine(db: Session, principal):
    by_name = and_(Notification.recipient_user_id == None, func.lower(Notification.recipient_name).in_(_my_names(db, principal) or ["-"]))  # noqa: E711
    who = or_(Notification.recipient_user_id == principal.user_id, by_name) if principal.user_id else by_name
    return db.query(Notification).filter(Notification.client_id == principal.client_id, who)


def notification_out(n: Notification) -> dict:
    return {"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "link": n.link, "project_id": n.project_id, "task_id": n.task_id,
            "comment_id": n.comment_id, "actor_name": n.actor_name, "is_read": bool(n.is_read), "created_at": utc_iso(n.created_at)}


def list_mine(db: Session, principal, *, unread_only=False, kind=None, offset=0, limit=20):
    query = mine(db, principal)
    unread = query.filter(Notification.is_read == False).count()  # noqa: E712
    if unread_only:
        query = query.filter(Notification.is_read == False)  # noqa: E712
    if kind:
        query = query.filter(Notification.kind == kind)
    total = query.count()
    rows = query.order_by(Notification.created_at.desc(), Notification.id.desc()).offset(offset).limit(limit).all()
    return rows, total, unread


def mark_read(db: Session, principal, ids=None, read=True, kind=None) -> int:
    query = mine(db, principal).filter(Notification.is_read == (not read))
    if ids:
        query = query.filter(Notification.id.in_(ids))
    if kind:
        query = query.filter(Notification.kind == kind)
    count = 0
    for n in query.all():
        n.is_read = read
        count += 1
    db.commit()
    return count
