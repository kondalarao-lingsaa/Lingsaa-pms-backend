from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import Principal, get_current_principal
from app.db.session import get_db
from app.models.notifications import NOTIFICATION_KINDS
from app.repositories import communication as repo
from app.repositories import notifications as notification_repo
from app.repositories import search as search_repo

router = APIRouter(tags=["communication"])


class ReadIn(BaseModel):
    ids: Optional[List[int]] = Field(default=None, max_length=500)  # empty = all of mine
    read: bool = True
    kind: Optional[str] = Field(default=None, pattern="^(" + "|".join(NOTIFICATION_KINDS) + ")$")  # only this kind (e.g. all mentions)


@router.get("/notifications")
def my_notifications(
    offset: int = Query(0, ge=0),
    page_size: int = Query(10, ge=1, le=50),
    unread_only: bool = False,
    kind: Optional[str] = Query(None, pattern="^(" + "|".join(NOTIFICATION_KINDS) + ")$"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    rows, total, unread = notification_repo.list_mine(db, principal, unread_only=unread_only, kind=kind, offset=offset, limit=page_size)
    return {"detail": [notification_repo.notification_out(n) for n in rows], "stack_values": {"count_pg": total, "unread": unread}}


@router.post("/notifications/read")
def mark_read(body: ReadIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    count = notification_repo.mark_read(db, principal, body.ids, body.read, body.kind)
    return {"detail": f"{count} notification{'' if count == 1 else 's'} marked as {'read' if body.read else 'unread'}", "count": count}


@router.get("/communication/comments")
def all_comments(
    offset: int = Query(0, ge=0),
    page_size: int = Query(10, ge=1, le=100),
    project_id: Optional[int] = None,
    search: Optional[str] = Query(None, max_length=100),
    involving_me: bool = False,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    rows, total = repo.comments(db, principal, project_id=project_id, search=(search or "").strip() or None, involving_me=involving_me, offset=offset, limit=page_size)
    return {"detail": rows, "stack_values": {"count_pg": total}}


@router.get("/communication/mentions")
def my_mentions(
    offset: int = Query(0, ge=0),
    page_size: int = Query(10, ge=1, le=100),
    unread_only: bool = False,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    rows, total, unread = repo.mentions(db, principal, unread_only=unread_only, offset=offset, limit=page_size)
    return {"detail": rows, "stack_values": {"count_pg": total, "unread": unread}}


@router.get("/communication/activity")
def activity_feed(
    offset: int = Query(0, ge=0),
    page_size: int = Query(30, ge=1, le=500),  # the screen loads more by growing the page
    project_id: Optional[int] = None,
    action: Optional[str] = Query(None, max_length=30),
    actor: Optional[str] = Query(None, max_length=200),
    search: Optional[str] = Query(None, max_length=100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    rows, total = repo.activity(db, principal, project_id=project_id, action=action or None, actor=actor or None, search=(search or "").strip() or None, offset=offset, limit=page_size)
    return {"detail": rows, "stack_values": {"count_pg": total}}


@router.get("/communication/meta")
def communication_meta(db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return {"detail": {"actions": list(repo.ACTION_GROUPS), "actors": repo.actors(db, principal), "kinds": NOTIFICATION_KINDS}}


@router.get("/search")
def global_search(q: str = Query(min_length=2, max_length=100), db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    """Ctrl+K search across the company's projects, tasks, milestones, documents, risks, issues, expenses, invoices, people."""
    groups = search_repo.search(db, principal, q.strip())
    return {"detail": groups, "stack_values": {"count_pg": sum(len(g["items"]) for g in groups)}}
