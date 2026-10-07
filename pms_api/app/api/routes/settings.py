from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core import access
from app.core.security import Principal, get_current_principal
from app.db.session import get_db
from app.repositories import projects as project_repo
from app.repositories import project_settings as project_settings_repo
from app.repositories import settings as repo
from app.repositories import templates as template_repo
from app.schemas.projects import ProjectIn, project_out
from app.core.industries import template_payload
from app.schemas.settings import CalendarIn, HolidayIn, IndustryIn, ProjectSettingsIn, SaveAsTemplateIn, TemplateIn

router = APIRouter(tags=["settings"])


# ------------------------------------------------------------------------------ company settings


@router.get("/settings")
def get_settings(year: Optional[int] = Query(None, ge=2000, le=2100), db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return {"detail": repo.get_settings(db, principal, year)}


@router.put("/settings/calendar")
def save_calendar(body: CalendarIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    repo.save_calendar(db, principal, body.hours_per_day, body.working_days)
    return {"detail": "Working calendar saved. Capacity, Utilization, Sprints and Reports now use it", "data": repo.get_settings(db, principal)}


@router.put("/settings/industry")
def save_industry(body: IndustryIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    repo.save_industry(db, principal, body.industry, body.member_roles)
    return {"detail": f"Industry set to {body.industry}. Team roles saved", "data": repo.get_settings(db, principal)}


@router.post("/settings/holidays", status_code=201)
def add_holiday(body: HolidayIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    try:
        h = repo.add_holiday(db, principal, body.holiday_date, body.name)
    except repo.SettingsError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"detail": f"{h.name} added on {h.holiday_date.strftime('%d %b %Y')}", "data": repo.holiday_out(h)}


@router.delete("/settings/holidays/{holiday_id}")
def delete_holiday(holiday_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    try:
        name = repo.delete_holiday(db, principal, holiday_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"detail": f"{name} removed"}


# ------------------------------------------------------------------------------ project templates


def _template(db, principal, template_id):
    t = template_repo.get_template(db, principal, template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return t


def _rule(fn, *args):
    try:
        return fn(*args)
    except template_repo.TemplateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/templates")
def list_templates(search: Optional[str] = Query(None, max_length=100), db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    rows = template_repo.list_templates(db, principal, (search or "").strip() or None)
    return {"detail": rows, "stack_values": {"count_pg": len(rows)}}


@router.get("/templates/{template_id}")
def get_template(template_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return {"detail": template_repo.template_out(db, _template(db, principal, template_id), full=True)}


@router.post("/templates", status_code=201)
def create_template(body: TemplateIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    t = _rule(template_repo.create_template, db, principal, body.model_dump())
    return {"detail": f"Template '{t.name}' created", "data": template_repo.template_out(db, t)}


@router.post("/templates/starter", status_code=201)
def load_starter_template(industry: str = Query(...), db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    """Adds the industry's starter template to Project Templates (once; it can then be edited like any template)."""
    industry = " ".join(industry.split())
    if not industry:
        raise HTTPException(status_code=422, detail="Please Select Industry")
    body = TemplateIn(**template_payload(industry))
    t = _rule(template_repo.create_template, db, principal, body.model_dump())
    return {"detail": f"Template '{t.name}' added. Use it to create a {industry} project", "data": template_repo.template_out(db, t)}


@router.put("/templates/{template_id}")
def update_template(template_id: int, body: TemplateIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    t = _rule(template_repo.update_template, db, principal, _template(db, principal, template_id), body.model_dump())
    return {"detail": f"Template '{t.name}' updated", "data": template_repo.template_out(db, t)}


@router.delete("/templates/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    t = _template(db, principal, template_id)
    template_repo.delete_template(db, principal, t)
    return {"detail": f"Template '{t.name}' deleted. Projects already created from it are not changed"}


@router.post("/projects/{project_id}/save-as-template", status_code=201)
def save_as_template(project_id: int, body: SaveAsTemplateIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    project = project_repo.get_project(db, principal, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    t = _rule(template_repo.from_project, db, principal, project, body.name, body.description)
    out = template_repo.template_out(db, t)
    return {"detail": f"Template '{t.name}' saved with {out['milestone_count']} milestones and {out['task_count'] + out['subtask_count']} tasks", "data": out}


@router.post("/templates/{template_id}/create-project", status_code=201)
def create_project_from_template(template_id: int, body: ProjectIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    t = _template(db, principal, template_id)
    try:
        project, milestones, tasks = template_repo.create_project(db, principal, t, body.model_dump())
    except template_repo.TemplateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except project_repo.DuplicateProject as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"detail": f"Project {project.project_code} created from '{t.name}' with {milestones} milestones and {tasks} tasks", "data": project_out(project)}


# ------------------------------------------------------------------------------ project settings


@router.get("/projects/{project_id}/settings")
def get_project_settings(project_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    project = project_repo.get_project(db, principal, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"detail": project_settings_repo.get(db, project.id)}


@router.put("/projects/{project_id}/settings")
def save_project_settings(project_id: int, body: ProjectSettingsIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    project = project_repo.get_project(db, principal, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.status == "Closed":
        raise HTTPException(status_code=409, detail=f"{project.project_code} is Closed, so its settings can no longer change")
    access.require_runs_project(principal, project, "change this project's settings")
    data = project_settings_repo.save(db, principal, project, body.model_dump())
    return {"detail": f"Settings saved for {project.project_code}", "data": data}
