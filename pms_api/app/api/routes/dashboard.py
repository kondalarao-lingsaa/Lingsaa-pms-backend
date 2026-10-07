from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.access import allowed
from app.core.security import Principal, get_current_principal
from app.db.session import get_db
from app.repositories import dashboard as repo

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
def dashboard_summary(db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    data = repo.project_dashboard(db, principal)
    if not allowed(principal, "budget", "view"):
        data.pop("budget_by_status", None)
    return {"detail": data}


@router.get("/overview")
def dashboard_overview(project_id: Optional[int] = None, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    """Every dashboard card's numbers - for all projects, or one project with ?project_id=.
    Each section needs the role's view right on its module (budget, billing, tasks, risks, resources, deliverables,
    timesheets); without it the section is left out (None) and the screen hides that card."""
    data = repo.overview(db, principal, project_id)
    if not allowed(principal, "budget", "view"):
        data["budgetPlanned"] = data["budgetActual"] = data["budgetUsedPct"] = None
        for p in data["projects"]:
            p["budgetPlanned"] = p["budgetActual"] = p["billed"] = p["margin"] = None
    if not allowed(principal, "billing", "view"):
        data["billing"] = None
        for m in data["milestones"]:
            m["amount"] = None
    if not allowed(principal, "tasks", "view"):
        data["taskTotals"] = data["taskCount"] = data["delayedTasks"] = data["trend"] = data["activity"] = None
    if not allowed(principal, "risks", "view"):
        data["risks"] = data["riskCounts"] = data["openIssues"] = data["criticalIssues"] = None
    if not allowed(principal, "resources", "view"):
        data["team"] = data["teamSize"] = None
    if not allowed(principal, "deliverables", "view"):
        data["milestones"] = data["deliverables"] = None
    if not allowed(principal, "timesheets", "view"):
        data["timesheets"] = None
    return {"detail": data}
