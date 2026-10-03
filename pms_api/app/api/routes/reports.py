from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.security import Principal, get_current_principal
from app.db.session import get_db
from app.repositories import reports as repo

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/catalog")
def catalog(principal: Principal = Depends(get_current_principal)):
    return {"detail": [{"key": key, "title": title, "description": desc, "filters": filters} for key, (_, title, desc, filters) in repo.REPORTS.items()]}


@router.get("/{report}")
def run_report(
    report: str,
    format: str = Query("json", pattern="^(json|csv)$"),
    project_id: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    person: Optional[str] = Query(None, max_length=100),
    status: Optional[str] = Query(None, max_length=30),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    try:
        result = repo.run(db, principal, report, project_id=project_id, date_from=date_from, date_to=date_to, person=(person or "").strip() or None, status=status or None)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except repo.ReportError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if format == "csv":
        name = f"{report}-{date.today().isoformat()}.csv"
        return Response(repo.to_csv(result), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"'})
    return {"detail": jsonable_encoder(result)}
