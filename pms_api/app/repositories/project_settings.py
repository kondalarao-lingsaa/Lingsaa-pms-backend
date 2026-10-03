"""Per-project rules (Projects > Project Settings) and the small helpers the other modules call to apply them."""
from sqlalchemy.orm import Session

from app.models.project_settings import DEFAULTS, ProjectSettings
from app.repositories.notifications import person_name
from app.schemas.rules import utc_iso


def _row(db: Session, project_id):
    return db.query(ProjectSettings).filter(ProjectSettings.project_id == project_id).one_or_none()


def _num(v):
    return float(v) if v is not None else None


def get(db: Session, project_id) -> dict:
    """The project's settings, with defaults filled in."""
    r = _row(db, project_id)
    if r is None:
        return {**DEFAULTS, "is_default": True, "updated_by_name": None, "updated_at": None}
    return {
        "default_task_priority": r.default_task_priority,
        "default_estimate_hours": _num(r.default_estimate_hours),
        "task_labels": [x for x in (r.task_labels or "").split(",") if x],
        "timesheet_lock_days": r.timesheet_lock_days,
        "budget_alert_pct": r.budget_alert_pct,
        "receipt_required_above": _num(r.receipt_required_above),
        "default_tax_pct": _num(r.default_tax_pct),
        "default_payment_terms": r.default_payment_terms,
        "is_default": False,
        "updated_by_name": r.updated_by_name,
        "updated_at": utc_iso(r.updated_at),
    }


def save(db: Session, principal, project, data: dict) -> dict:
    r = _row(db, project.id)
    if r is None:
        r = ProjectSettings(project_id=project.id, client_id=principal.client_id)
        db.add(r)
    for key, value in data.items():
        setattr(r, key, ",".join(value) if key == "task_labels" else value)
    r.updated_by = principal.user_id
    r.updated_by_name = person_name(principal.user_name) or principal.user_name
    db.commit()
    return get(db, project.id)
