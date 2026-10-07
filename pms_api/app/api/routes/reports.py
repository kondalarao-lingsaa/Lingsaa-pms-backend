from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.access import allowed, can_see_rates
from app.core.security import Principal, get_current_principal
from app.db.session import get_db
from app.repositories import reports as repo

router = APIRouter(prefix="/reports", tags=["reports"])


# A report shows a module's data, so it needs that module's right as well as Reports.
REPORT_RIGHTS = {"budget": "budget", "billing": "billing", "risks": "risks", "utilization": "resources"}


def _may_run(principal, key) -> bool:
    group = REPORT_RIGHTS.get(key)
    return group is None or allowed(principal, group, "view")


def _without_money(result) -> dict:
    """Removes money columns, totals and summary cards for roles that cannot see the budget."""
    money = {c["key"] for c in result.get("columns", []) if c.get("type") == "money"}
    if not money:
        return result
    result["columns"] = [c for c in result["columns"] if c["key"] not in money]
    result["rows"] = [{k: v for k, v in r.items() if k not in money} for r in result.get("rows", [])]
    result["totals"] = {k: v for k, v in (result.get("totals") or {}).items() if k not in money}
    result["summary"] = [s for s in result.get("summary", []) if s.get("type") != "money"]
    if result.get("chart"):
        result["chart"]["series"] = [s for s in result["chart"]["series"] if s["key"] not in money]
        if not result["chart"]["series"]:
            result.pop("chart")  # nothing left to draw (e.g. the billing chart is only money)
    return result


@router.get("/catalog")
def catalog(principal: Principal = Depends(get_current_principal)):
    return {"detail": [{"key": key, "title": title, "description": desc, "filters": filters}
                       for key, (_, title, desc, filters) in repo.REPORTS.items() if _may_run(principal, key)]}


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
    if report in repo.REPORTS and not _may_run(principal, report):
        raise HTTPException(status_code=403, detail=f"Your role ({principal.role_title}) cannot run this report")
    try:
        result = repo.run(db, principal, report, project_id=project_id, date_from=date_from, date_to=date_to, person=(person or "").strip() or None, status=status or None)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except repo.ReportError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not can_see_rates(principal):
        result = _without_money(result)
    if format == "csv":
        name = f"{report}-{date.today().isoformat()}.csv"
        return Response(repo.to_csv(result), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"'})
    return {"detail": jsonable_encoder(result)}
