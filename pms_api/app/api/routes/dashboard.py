from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import Principal, get_current_principal
from app.db.session import get_db
from app.repositories import dashboard as repo

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
def dashboard_summary(db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return {"detail": repo.project_dashboard(db, principal)}


@router.get("/overview")
def dashboard_overview(project_id: Optional[int] = None, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    """Every dashboard card's numbers - for all projects, or one project with ?project_id=."""
    return {"detail": repo.overview(db, principal, project_id)}
