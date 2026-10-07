"""Client portal: what a Client user sees of their own company's projects.

A Client only reaches these routes (access.ROUTE_POLICY), and only for projects of their customer that are past
approval (access.project_scope). They see progress, milestones, shared documents, issued invoices and messages;
never hours, pay rates, internal costs, other clients or internal comments.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.security import Principal, get_current_principal
from app.db.session import get_db
from app.models.access import ClientMessage
from app.models.billing import Invoice
from app.models.documents import Document
from app.repositories import approvals
from app.repositories import billing as billing_repo
from app.repositories import documents as document_repo
from app.repositories import milestones as milestone_repo
from app.repositories import notifications as notification_repo
from app.repositories import projects as project_repo
from app.schemas.rules import utc_iso

router = APIRouter(tags=["portal"])

CLIENT_INVOICE_STATUSES = ("Issued", "Paid")


def _project(db, principal, project_id):
    project = project_repo.get_project(db, principal, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _summary(project, progress) -> dict:
    p = progress.get(project.id, {"task_count": 0, "progress": 0})
    return {
        "id": project.id, "project_code": project.project_code, "project_name": project.project_name, "description": project.description,
        "status": project.status, "start_date": project.start_date.isoformat() if project.start_date else None,
        "end_date": project.end_date.isoformat() if project.end_date else None, "progress": p["progress"],
        "project_manager_name": project.project_manager_name, "customer_name": project.customer_name,
    }


def message_out(m: ClientMessage) -> dict:
    return {"id": m.id, "author_name": m.author_name, "from_client": m.from_client, "body": m.body, "created_at": utc_iso(m.created_at)}


def project_messages(db, principal, project_id) -> list:
    rows = (
        db.query(ClientMessage)
        .filter(ClientMessage.client_id == principal.client_id, ClientMessage.project_id == project_id)
        .order_by(ClientMessage.created_at, ClientMessage.id)
        .all()
    )
    return [message_out(m) for m in rows]


@router.get("/portal/projects")
def portal_projects(db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    projects = project_repo.all_projects(db, principal)
    progress = project_repo.progress_for(db, [p.id for p in projects])
    return {"detail": {"customer_name": principal.customer_name, "projects": [_summary(p, progress) for p in projects]}}


@router.get("/portal/projects/{project_id}")
def portal_project(project_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    project = _project(db, principal, project_id)
    progress = project_repo.progress_for(db, [project.id])
    milestones = [
        {k: m[k] for k in ("id", "name", "description", "due_date", "amount", "status", "feedback", "accepted_at", "accepted_by_name") if k in m}
        | {"deliverables": [{"name": d["name"], "is_done": d["is_done"]} for d in m.get("deliverables", [])]}
        for m in milestone_repo.list_for_project(db, principal, project.id)
    ]
    shared = [
        d for d in document_repo.list_documents(db, principal, project_id=project.id) if d.get("client_visible")
    ]
    documents = [{k: d[k] for k in ("id", "title", "category", "file_name", "version", "size_bytes", "created_at")} for d in shared]
    invoices = (
        db.query(Invoice)
        .filter(Invoice.client_id == principal.client_id, Invoice.project_id == project.id, Invoice.is_deleted == False,  # noqa: E712
                Invoice.status.in_(CLIENT_INVOICE_STATUSES))
        .order_by(Invoice.issue_date.desc(), Invoice.id.desc())
        .all()
    )
    invoice_rows = [
        {k: i[k] for k in ("id", "invoice_no", "milestone_name", "total", "status", "issue_date", "due_date", "paid_date", "is_overdue")}
        for i in billing_repo._serialize(db, invoices)
    ]
    return {
        "detail": {
            **_summary(project, progress),
            "milestones": milestones,
            "documents": documents,
            "invoices": invoice_rows,
            "messages": project_messages(db, principal, project.id),
        }
    }


class MilestoneDecisionIn(BaseModel):
    decision: str
    feedback: Optional[str] = Field(None, max_length=1000)

    @field_validator("decision")
    @classmethod
    def _decision(cls, v):
        if v not in ("accept", "changes"):
            raise ValueError("Choose Accept or Ask for changes")
        return v


@router.post("/portal/projects/{project_id}/milestones/{milestone_id}/decision")
def portal_milestone_decision(
    project_id: int, milestone_id: int, body: MilestoneDecisionIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)
):
    project = _project(db, principal, project_id)
    milestone = milestone_repo.get_milestone(db, principal, milestone_id, project.id)
    if milestone is None:
        raise HTTPException(status_code=404, detail="Milestone not found")
    if milestone.status != "Ready for Review":
        raise HTTPException(status_code=409, detail=f"'{milestone.name}' is {milestone.status}, not waiting for your review")
    new_status = "Accepted" if body.decision == "accept" else "Changes Requested"
    try:
        milestone = milestone_repo.change_status(db, principal, milestone, new_status, body.feedback)
    except milestone_repo.MilestoneError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    approvals.log(db, principal, "milestone", milestone.id, new_status, project_id=project.id, remarks=body.feedback)
    who = notification_repo.person_name(principal.user_name) or principal.user_name
    notification_repo.notify(
        db, principal, [(project.project_manager_id, project.project_manager_name)], "approval",
        f"{who} ({project.customer_name}) {'accepted' if new_status == 'Accepted' else 'asked for changes on'} '{milestone.name}' "
        f"of {project.project_code} {project.project_name}",
        body=body.feedback, link=f"projects/projectDetails/?id={project.id}&tab=milestones", project_id=project.id,
    )
    db.commit()
    return {"detail": f"'{milestone.name}' {'accepted. Thank you' if new_status == 'Accepted' else 'sent back to the team with your feedback'}"}


class MessageIn(BaseModel):
    body: str = Field(min_length=2, max_length=2000)

    @field_validator("body")
    @classmethod
    def _body(cls, v):
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Please Enter a Message")
        return v


def add_message(db, principal, project, body: str, from_client: bool) -> ClientMessage:
    name = notification_repo.person_name(principal.user_name) or principal.user_name or "User"
    m = ClientMessage(client_id=principal.client_id, project_id=project.id, author_user_id=principal.user_id, author_name=name,
                      from_client=from_client, body=body)
    db.add(m)
    if from_client:
        recipients = [(project.project_manager_id, project.project_manager_name)]
        link = f"projects/projectDetails/?id={project.id}&tab=client"
    else:
        from app.models.access import UserRole

        rows = db.query(UserRole).filter(UserRole.client_id == principal.client_id, UserRole.role == "client", UserRole.is_active == True,  # noqa: E712
                                         UserRole.customer_name == project.customer_name).all()
        recipients = [(r.user_id, r.user_name) for r in rows]
        link = "portal/"
    notification_repo.notify(db, principal, recipients, "message", f"{name} wrote on {project.project_code} {project.project_name}",
                             body=body[:300], link=link, project_id=project.id)
    db.commit()
    db.refresh(m)
    return m


@router.post("/portal/projects/{project_id}/messages", status_code=201)
def portal_message(project_id: int, body: MessageIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    project = _project(db, principal, project_id)
    m = add_message(db, principal, project, body.body, from_client=True)
    return {"detail": "Message sent to the project team", "data": message_out(m)}


@router.get("/portal/documents/{document_id}/download")
def portal_document(document_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    doc = db.query(Document).filter(Document.id == document_id, Document.client_id == principal.client_id, Document.is_deleted == False,  # noqa: E712
                                    Document.is_latest == True, Document.client_visible == True).one_or_none()  # noqa: E712
    if doc is None or project_repo.get_project(db, principal, doc.project_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        path = document_repo.file_path(doc)
    except (LookupError, document_repo.DocumentError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return FileResponse(path, media_type=doc.content_type, filename=doc.file_name, headers={"X-Content-Type-Options": "nosniff"})


@router.get("/portal/invoices/{invoice_id}")
def portal_invoice(invoice_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    invoice = billing_repo.get_invoice(db, principal, invoice_id)
    if invoice is None or invoice.status not in CLIENT_INVOICE_STATUSES:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return {"detail": billing_repo.invoice_detail(db, principal, invoice)}


# ------------------------------------------------------------------------------ the team's side of the conversation


@router.get("/projects/{project_id}/client-messages")
def team_messages(project_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    project = _project(db, principal, project_id)
    return {"detail": project_messages(db, principal, project.id)}


@router.post("/projects/{project_id}/client-messages", status_code=201)
def team_reply(project_id: int, body: MessageIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    project = _project(db, principal, project_id)
    m = add_message(db, principal, project, body.body, from_client=False)
    return {"detail": "Reply sent to the client", "data": message_out(m)}
