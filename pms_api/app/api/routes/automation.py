from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core import scheduler
from app.core.security import Principal, get_current_principal
from app.db.session import get_db
from app.repositories import automation as repo
from app.repositories import recurring as recurring_repo
from app.schemas.automation import AutomationRuleIn, RecurringTaskIn

router = APIRouter(tags=["automation"])


# ------------------------------------------------------------------------------ Settings > Automation


@router.get("/automation")
def automation_overview(db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return {"detail": {**repo.overview(db, principal), "scheduler_running": scheduler.is_running()}}


@router.get("/automation/runs")
def automation_runs(
    job_key: Optional[str] = Query(None, max_length=40),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return {"detail": repo.runs(db, principal, job_key=job_key, limit=limit)}


@router.put("/automation/{job_key}")
def save_automation(job_key: str, body: AutomationRuleIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    try:
        repo.save_rule(db, principal, job_key, body.model_dump(exclude_unset=True))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except repo.AutomationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    job = next(j for j in repo.overview(db, principal)["jobs"] if j["key"] == job_key)
    state = "on" if job["enabled"] else "off"
    return {"detail": f"{job['title']} is {state}" + (f": {job['schedule_text']}" if job["enabled"] else ""), "data": job}


@router.post("/automation/{job_key}/run")
def run_automation(job_key: str, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    try:
        result = repo.run_job(db, principal.client_id, job_key, trigger="Manual", by_name=principal.user_name)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"detail": f"{repo.JOBS[job_key]['title']}: {result['summary']}", "data": result}


# ------------------------------------------------------------------------------ Tasks > Recurring Tasks


def _rule_or_404(db, principal, rule_id):
    rule = recurring_repo.get(db, principal, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Recurring task not found")
    return rule


def _out(db, principal, rule_id):
    return next(r for r in recurring_repo.list_rules(db, principal) if r["id"] == rule_id)


@router.get("/recurring-tasks")
def list_recurring(
    project_id: Optional[int] = None,
    search: Optional[str] = Query(None, max_length=100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return {"detail": recurring_repo.list_rules(db, principal, project_id=project_id, search=(search or "").strip() or None)}


@router.post("/recurring-tasks", status_code=201)
def create_recurring(body: RecurringTaskIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    try:
        rule = recurring_repo.create(db, principal, body.model_dump())
    except recurring_repo.RecurringError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    out = _out(db, principal, rule.id)
    return {"detail": f"'{rule.title}' saved: {out['schedule_text'].lower()}, first on {rule.next_run_on.strftime('%d %b %Y')}", "data": out}


@router.put("/recurring-tasks/{rule_id}")
def update_recurring(rule_id: int, body: RecurringTaskIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    rule = _rule_or_404(db, principal, rule_id)
    try:
        rule = recurring_repo.update(db, principal, rule, body.model_dump())
    except recurring_repo.RecurringError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    out = _out(db, principal, rule.id)
    when = f"next on {rule.next_run_on.strftime('%d %b %Y')}" if rule.next_run_on else "paused"
    return {"detail": f"'{rule.title}' saved ({when})", "data": out}


@router.delete("/recurring-tasks/{rule_id}")
def delete_recurring(rule_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    rule = _rule_or_404(db, principal, rule_id)
    recurring_repo.delete(db, principal, rule)
    return {"detail": f"'{rule.title}' no longer repeats. Tasks already created stay"}
