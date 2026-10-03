"""Project documents and attachments: checked uploads, version history, links to tasks / milestones / deliverables."""
import os
import re
import uuid
from pathlib import Path

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.documents import DOCUMENT_CATEGORIES, Document
from app.models.milestones import Deliverable, Milestone
from app.models.projects import Project
from app.models.tasks import Task
from app.schemas.rules import utc_iso
from app.core.access import project_scope

# Allowed file types, with the bytes a real file of that type starts with (None = text/zip-based, checked loosely).
ALLOWED = {
    "pdf": ("application/pdf", [b"%PDF"]),
    "png": ("image/png", [b"\x89PNG"]),
    "jpg": ("image/jpeg", [b"\xff\xd8\xff"]),
    "jpeg": ("image/jpeg", [b"\xff\xd8\xff"]),
    "gif": ("image/gif", [b"GIF87a", b"GIF89a"]),
    "webp": ("image/webp", [b"RIFF"]),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", [b"PK\x03\x04"]),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", [b"PK\x03\x04"]),
    "pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", [b"PK\x03\x04"]),
    "zip": ("application/zip", [b"PK\x03\x04", b"PK\x05\x06"]),
    "doc": ("application/msword", [b"\xd0\xcf\x11\xe0"]),
    "xls": ("application/vnd.ms-excel", [b"\xd0\xcf\x11\xe0"]),
    "ppt": ("application/vnd.ms-powerpoint", [b"\xd0\xcf\x11\xe0"]),
    "csv": ("text/csv", None),
    "txt": ("text/plain", None),
    "md": ("text/markdown", None),
}
# Executables and scripts are refused even if renamed: their first bytes give them away.
EXECUTABLE_SIGNATURES = (b"MZ", b"\x7fELF", b"#!")


class DocumentError(Exception):
    """An upload / document rule was broken; the message is safe to show to the user."""


class FileRejected(DocumentError):
    """The file itself is not acceptable (type, size, content)."""


def storage_root() -> Path:
    root = Path(settings.UPLOAD_DIR)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[2] / root
    return root


def _safe_name(name: str) -> str:
    name = os.path.basename((name or "").replace("\\", "/")).strip()
    name = re.sub(r"[^\w.\- ()]+", "_", name)[:200]
    return name or "file"


def _extension(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def check_file(file_name: str, data: bytes) -> tuple:
    """Returns (safe_name, extension, content_type) or raises DocumentError with a clear reason."""
    name = _safe_name(file_name)
    ext = _extension(name)
    if ext not in ALLOWED:
        raise FileRejected(f"'.{ext or '?'}' files are not allowed. Allowed: {', '.join(sorted(ALLOWED))}")
    if not data:
        raise FileRejected("The file is empty")
    limit = settings.MAX_UPLOAD_MB * 1024 * 1024
    if len(data) > limit:
        raise FileRejected(f"The file is {len(data) / 1024 / 1024:.1f} MB. The largest allowed is {settings.MAX_UPLOAD_MB} MB")
    if data.startswith(EXECUTABLE_SIGNATURES):
        raise FileRejected("This looks like a program or script, which cannot be uploaded")
    content_type, signatures = ALLOWED[ext]
    if signatures and not any(data.startswith(sig) for sig in signatures):
        raise FileRejected(f"The file's content does not match '.{ext}'. It may be renamed or damaged")
    if signatures is None and b"\x00" in data[:4096]:
        raise FileRejected(f"A '.{ext}' file must be plain text")
    return name, ext, content_type


def _live(db: Session, principal):
    return db.query(Document).join(Project, Project.id == Document.project_id).filter(
        Document.client_id == principal.client_id, Document.is_deleted == False, Project.is_deleted == False, project_scope(db, principal)  # noqa: E712
    )


def get_document(db, principal, document_id):
    return _live(db, principal).filter(Document.id == document_id).one_or_none()


def _check_links(db, project, task_id, milestone_id, deliverable_id):
    if task_id and not db.query(Task).filter(Task.id == task_id, Task.project_id == project.id, Task.is_deleted == False).first():  # noqa: E712
        raise DocumentError("The task must belong to this project")
    if milestone_id and not db.query(Milestone).filter(Milestone.id == milestone_id, Milestone.project_id == project.id, Milestone.is_deleted == False).first():  # noqa: E712
        raise DocumentError("The milestone must belong to this project")
    if deliverable_id:
        deliverable = db.query(Deliverable).filter(Deliverable.id == deliverable_id, Deliverable.is_deleted == False).one_or_none()  # noqa: E712
        milestone = db.query(Milestone).filter(Milestone.id == deliverable.milestone_id).one_or_none() if deliverable else None
        if not milestone or milestone.project_id != project.id:
            raise DocumentError("The deliverable must belong to a milestone of this project")
        if milestone_id and milestone.id != milestone_id:
            raise DocumentError("The deliverable must belong to the chosen milestone")
        return milestone.id
    return milestone_id


def save_upload(db, principal, project, *, file_name, data, title, category, notes=None, task_id=None, milestone_id=None, deliverable_id=None, replaces_id=None) -> Document:
    if project.status == "Closed":
        raise DocumentError(f"{project.project_code} is Closed, so files can no longer be added")
    if category not in DOCUMENT_CATEGORIES:
        raise DocumentError("Please Select Category")
    name, ext, content_type = check_file(file_name, data)

    group_key, version, previous = str(uuid.uuid4()), 1, None
    if replaces_id:
        previous = get_document(db, principal, replaces_id)
        if previous is None or previous.project_id != project.id:
            raise DocumentError("The document to replace was not found in this project")
        if not previous.is_latest:
            raise DocumentError("Upload the new version on top of the latest one")
        group_key, version = previous.group_key, previous.version + 1
        # A new version keeps the document's place (links) unless new ones are given.
        task_id, milestone_id, deliverable_id = task_id or previous.task_id, milestone_id or previous.milestone_id, deliverable_id or previous.deliverable_id
    milestone_id = _check_links(db, project, task_id, milestone_id, deliverable_id)

    title = " ".join((title or "").split()) or name.rsplit(".", 1)[0]
    if len(title) < 2:
        raise DocumentError("Please Enter a Title (at least 2 characters)")

    relative = Path(str(principal.client_id)) / str(project.id) / f"{uuid.uuid4().hex}.{ext}"
    target = storage_root() / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    try:
        if previous is not None:
            previous.is_latest = False
        doc = Document(
            client_id=principal.client_id, project_id=project.id, task_id=task_id, milestone_id=milestone_id, deliverable_id=deliverable_id,
            group_key=group_key, version=version, is_latest=True, title=title[:1].upper() + title[1:200], category=category,
            notes=(notes or "").strip()[:1000] or None, file_name=name, extension=ext, content_type=content_type, size_bytes=len(data),
            stored_path=str(relative).replace("\\", "/"), uploaded_by=principal.user_id, uploaded_by_name=principal.user_name,
            client_visible=previous.client_visible if previous is not None else None,
        )
        db.add(doc)
        db.commit()
    except Exception:
        target.unlink(missing_ok=True)  # never leave an orphan file behind a failed save
        raise
    db.refresh(doc)
    return doc


def file_path(doc) -> Path:
    path = (storage_root() / doc.stored_path).resolve()
    if storage_root().resolve() not in path.parents:
        raise DocumentError("Invalid file location")
    if not path.exists():
        raise LookupError("The file is missing from storage")
    return path


def update_details(db, principal, project, doc, title, category, notes, client_visible=None) -> Document:
    if project.status == "Closed":
        raise DocumentError(f"{project.project_code} is Closed")
    if category not in DOCUMENT_CATEGORIES:
        raise DocumentError("Please Select Category")
    # Details belong to the document, so every version gets them.
    for version in db.query(Document).filter(Document.group_key == doc.group_key, Document.is_deleted == False):  # noqa: E712
        version.title, version.category, version.notes = title, category, notes
        if client_visible is not None:
            version.client_visible = client_visible
    db.commit()
    db.refresh(doc)
    return doc


def delete_document(db, principal, project, doc) -> None:
    """Deletes one version; if it was the latest, the previous version becomes the latest again."""
    if project.status == "Closed":
        raise DocumentError(f"{project.project_code} is Closed")
    doc.is_deleted = True
    if doc.is_latest:
        doc.is_latest = False
        previous = (
            db.query(Document)
            .filter(Document.group_key == doc.group_key, Document.is_deleted == False, Document.id != doc.id)  # noqa: E712
            .order_by(Document.version.desc())
            .first()
        )
        if previous is not None:
            previous.is_latest = True
    db.commit()


def _names(db, docs):
    def lookup(model, attr, ids, label):
        ids = {i for i in ids if i}
        return {row[0]: row[1] for row in db.query(model.id, label).filter(model.id.in_(ids)).all()} if ids else {}

    return (
        lookup(Project, "project", [d.project_id for d in docs], Project.project_code),
        lookup(Project, "project", [d.project_id for d in docs], Project.project_name),
        lookup(Task, "task", [d.task_id for d in docs], Task.task_key),
        lookup(Task, "task", [d.task_id for d in docs], Task.title),
        lookup(Milestone, "milestone", [d.milestone_id for d in docs], Milestone.name),
        lookup(Deliverable, "deliverable", [d.deliverable_id for d in docs], Deliverable.name),
    )


def serialize(db, docs) -> list:
    codes, pnames, tkeys, ttitles, mnames, dnames = _names(db, docs)
    groups = {d.group_key for d in docs}
    counts = dict(db.query(Document.group_key, func.count()).filter(Document.group_key.in_(groups), Document.is_deleted == False).group_by(Document.group_key).all()) if groups else {}  # noqa: E712
    return [
        {
            "id": d.id, "project_id": d.project_id, "project_code": codes.get(d.project_id), "project_name": pnames.get(d.project_id),
            "task_id": d.task_id, "task_key": tkeys.get(d.task_id), "task_title": ttitles.get(d.task_id),
            "milestone_id": d.milestone_id, "milestone_name": mnames.get(d.milestone_id),
            "deliverable_id": d.deliverable_id, "deliverable_name": dnames.get(d.deliverable_id),
            "group_key": d.group_key, "version": d.version, "is_latest": d.is_latest, "version_count": counts.get(d.group_key, 1),
            "title": d.title, "category": d.category, "notes": d.notes, "file_name": d.file_name, "extension": d.extension,
            "content_type": d.content_type, "size_bytes": d.size_bytes, "uploaded_by_name": d.uploaded_by_name, "created_at": utc_iso(d.created_at),
            "client_visible": bool(d.client_visible),
        }
        for d in docs
    ]


def list_documents(db, principal, *, project_id=None, task_id=None, milestone_id=None, category=None, search=None) -> list:
    query = _live(db, principal).filter(Document.is_latest == True)  # noqa: E712
    if project_id:
        query = query.filter(Document.project_id == project_id)
    if task_id:
        query = query.filter(Document.task_id == task_id)
    if milestone_id:
        query = query.filter(Document.milestone_id == milestone_id)
    if category:
        query = query.filter(Document.category == category)
    if search:
        like = f"%{search}%"
        query = query.filter(or_(Document.title.ilike(like), Document.file_name.ilike(like), Project.project_name.ilike(like), Project.project_code.ilike(like)))
    return serialize(db, query.order_by(Document.created_at.desc(), Document.id.desc()).all())


def versions(db, principal, doc) -> list:
    rows = _live(db, principal).filter(Document.group_key == doc.group_key).order_by(Document.version.desc()).all()
    return serialize(db, rows)
