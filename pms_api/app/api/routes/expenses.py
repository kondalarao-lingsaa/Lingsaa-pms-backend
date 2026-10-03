from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.core.security import Principal, get_current_principal
from app.core.config import settings
from app.db.session import get_db
from app.models.expenses import EXPENSE_CATEGORIES, EXPENSE_STATUSES
from app.repositories import documents as document_repo
from app.repositories import expenses as repo
from app.repositories import projects as project_repo
from app.schemas.expenses import ExpenseIdsIn, ExpenseIn, ExpenseRejectIn, expense_out

router = APIRouter(tags=["expenses"])


def _project(db, principal, project_id):
    project = project_repo.get_project(db, principal, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _expense(db, principal, expense_id):
    e = repo.get_expense(db, principal, expense_id)
    if e is None:
        raise HTTPException(status_code=404, detail="Expense not found")
    return e


def _rule(fn, *args):
    try:
        return fn(*args)
    except repo.ExpenseError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/expenses/meta")
def expense_meta(principal: Principal = Depends(get_current_principal)):
    return {"detail": {"categories": EXPENSE_CATEGORIES, "statuses": EXPENSE_STATUSES}}


@router.get("/expenses")
def list_expenses(
    offset: int = Query(0, ge=0),
    page_size: int = Query(5, ge=1, le=100),
    project_id: Optional[int] = None,
    status: Optional[str] = Query(None, pattern="^(" + "|".join(EXPENSE_STATUSES) + ")$"),
    category: Optional[str] = Query(None, max_length=50),
    search: Optional[str] = Query(None, max_length=100),
    mine: bool = False,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    rows, total, counts, sums = repo.list_expenses(db, principal, project_id=project_id, status=status, category=category or None,
                                                   search=(search or "").strip() or None, mine=mine, offset=offset, limit=page_size)
    return {"detail": rows, "stack_values": {"count_pg": total, "status_counts": counts, "status_amounts": sums}}


@router.post("/expenses", status_code=201)
def create_expense(body: ExpenseIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    project = _project(db, principal, body.project_id)
    e = _rule(repo.create_expense, db, principal, project, body.model_dump())
    return {"detail": f"{e.expense_key} {'sent for approval' if e.status == 'Submitted' else 'saved as draft'}", "data": expense_out(e, project)}


@router.put("/expenses/{expense_id}")
def update_expense(expense_id: int, body: ExpenseIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    e = _expense(db, principal, expense_id)
    project = _project(db, principal, e.project_id)
    e = _rule(repo.update_expense, db, principal, project, e, body.model_dump())
    return {"detail": f"{e.expense_key} {'sent for approval' if e.status == 'Submitted' else 'updated'}", "data": expense_out(e, project)}


@router.delete("/expenses/{expense_id}")
def delete_expense(expense_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    e = _expense(db, principal, expense_id)
    _rule(repo.delete_expense, db, principal, e)
    return {"detail": f"{e.expense_key} deleted"}


@router.post("/expenses/{expense_id}/submit")
def submit_expense(expense_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    e = _expense(db, principal, expense_id)
    project = _project(db, principal, e.project_id)
    e = _rule(repo.submit_expense, db, principal, project, e)
    return {"detail": f"{e.expense_key} sent for approval", "data": expense_out(e, project)}


@router.post("/expenses/approve")
def approve_expenses(body: ExpenseIdsIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    r = _rule(repo.review, db, principal, body.ids, True)
    msg = f"{r['count']} expense{'' if r['count'] == 1 else 's'} approved"
    if r["over_budget"]:
        msg += f". Note: {', '.join(r['over_budget'])} {'is' if len(r['over_budget']) == 1 else 'are'} now over budget"
    return {"detail": msg, **r}


@router.post("/expenses/reject")
def reject_expenses(body: ExpenseRejectIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    r = _rule(repo.review, db, principal, body.ids, False, body.reason)
    return {"detail": f"{r['count']} expense{'' if r['count'] == 1 else 's'} rejected", **r}


@router.get("/budget/actual-cost")
def actual_cost(project_id: Optional[int] = None, months: int = Query(6, ge=1, le=24), db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return {"detail": repo.actual_cost(db, principal, project_id, months)}


@router.get("/budget/variance")
def budget_variance(project_id: Optional[int] = None, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return {"detail": repo.variance(db, principal, project_id)}


@router.post("/expenses/{expense_id}/receipt")
def attach_receipt(expense_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    e = _expense(db, principal, expense_id)
    project = _project(db, principal, e.project_id)
    data = file.file.read(settings.MAX_UPLOAD_MB * 1024 * 1024 + 1)
    try:
        e = repo.attach_receipt(db, principal, project, e, file.filename, data)
    except document_repo.FileRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except (repo.ExpenseError, document_repo.DocumentError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"detail": f"Receipt attached to {e.expense_key}", "data": repo._serialize(db, [e])[0]}


@router.delete("/expenses/{expense_id}/receipt")
def remove_receipt(expense_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    e = _expense(db, principal, expense_id)
    project = _project(db, principal, e.project_id)
    _rule(repo.remove_receipt, db, principal, project, e)
    return {"detail": f"Receipt removed from {e.expense_key}"}
