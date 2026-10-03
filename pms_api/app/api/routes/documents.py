from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import Principal, get_current_principal
from app.db.session import get_db
from app.models.documents import DOCUMENT_CATEGORIES
from app.repositories import documents as repo
from app.repositories import projects as project_repo
from app.schemas.rules import capitalize_first

router = APIRouter(tags=["documents"])


class DocumentDetailsIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    category: str
    notes: Optional[str] = Field(default=None, max_length=1000)
    # Shared with the client in the client portal.
    client_visible: Optional[bool] = None

    @field_validator("title")
    @classmethod
    def _title(cls, v):
        v = capitalize_first(" ".join(v.split()))
        if not v or len(v) < 2:
            raise ValueError("Please Enter a Title (at least 2 characters)")
        return v

    @field_validator("category")
    @classmethod
    def _category(cls, v):
        if v not in DOCUMENT_CATEGORIES:
            raise ValueError("Please Select Category")
        return v

    @field_validator("notes")
    @classmethod
    def _notes(cls, v):
        return capitalize_first(" ".join(v.split())) if v else None


def _project(db, principal, project_id):
    project = project_repo.get_project(db, principal, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _document(db, principal, document_id):
    doc = repo.get_document(db, principal, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


def _list_response(rows):
    return {
        "detail": rows,
        "stack_values": {
            "count_pg": len(rows),
            "total_bytes": sum(r["size_bytes"] for r in rows),
            "by_category": {c: sum(1 for r in rows if r["category"] == c) for c in DOCUMENT_CATEGORIES if any(r["category"] == c for r in rows)},
        },
    }


@router.get("/documents/meta")
def document_meta(principal: Principal = Depends(get_current_principal)):
    return {"detail": {"categories": DOCUMENT_CATEGORIES, "extensions": sorted(repo.ALLOWED), "max_mb": settings.MAX_UPLOAD_MB}}


@router.get("/documents/list")
def all_documents(
    project_id: Optional[int] = None, task_id: Optional[int] = None, milestone_id: Optional[int] = None, category: Optional[str] = None, search: Optional[str] = None,
    db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal),
):
    return _list_response(repo.list_documents(db, principal, project_id=project_id, task_id=task_id, milestone_id=milestone_id, category=category, search=search))


@router.post("/projects/{project_id}/documents", status_code=201)
def upload_document(
    project_id: int,
    file: UploadFile = File(...),
    category: str = Form(...),
    title: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    task_id: Optional[int] = Form(None),
    milestone_id: Optional[int] = Form(None),
    deliverable_id: Optional[int] = Form(None),
    replaces_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    project = _project(db, principal, project_id)
    # Read one byte past the limit so an oversized file is refused without loading all of it.
    data = file.file.read(settings.MAX_UPLOAD_MB * 1024 * 1024 + 1)
    try:
        doc = repo.save_upload(
            db, principal, project, file_name=file.filename, data=data, title=title, category=category, notes=notes,
            task_id=task_id, milestone_id=milestone_id, deliverable_id=deliverable_id, replaces_id=replaces_id,
        )
    except repo.FileRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except repo.DocumentError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    label = f"version {doc.version} of '{doc.title}'" if doc.version > 1 else f"'{doc.title}'"
    return {"detail": f"Uploaded {label}", "data": repo.serialize(db, [doc])[0]}


@router.get("/documents/{document_id}/versions")
def document_versions(document_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return {"detail": repo.versions(db, principal, _document(db, principal, document_id))}


@router.get("/documents/{document_id}/download")
def download_document(document_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    doc = _document(db, principal, document_id)
    try:
        path = repo.file_path(doc)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except repo.DocumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # Always a download (never rendered in the app's origin), with the original file name.
    return FileResponse(path, media_type=doc.content_type, filename=doc.file_name, headers={"X-Content-Type-Options": "nosniff"})


@router.put("/documents/{document_id}")
def update_document(document_id: int, body: DocumentDetailsIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    doc = _document(db, principal, document_id)
    try:
        doc = repo.update_details(db, principal, _project(db, principal, doc.project_id), doc, body.title, body.category, body.notes, body.client_visible)
    except repo.DocumentError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"detail": f"'{doc.title}' updated", "data": repo.serialize(db, [doc])[0]}


@router.delete("/documents/{document_id}")
def delete_document(document_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    doc = _document(db, principal, document_id)
    try:
        repo.delete_document(db, principal, _project(db, principal, doc.project_id), doc)
    except repo.DocumentError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"detail": f"Version {doc.version} of '{doc.title}' deleted" if doc.version > 1 else f"'{doc.title}' deleted"}
