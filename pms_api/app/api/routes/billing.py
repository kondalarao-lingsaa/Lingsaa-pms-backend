from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import Principal, get_current_principal
from app.db.session import get_db
from app.models.billing import INVOICE_STATUSES, INVOICE_TYPES
from app.repositories import billing as repo
from app.repositories import projects as project_repo
from app.schemas.billing import InvoiceCreateIn, InvoiceStatusIn

router = APIRouter(prefix="/billing", tags=["billing"])


def _project(db, principal, project_id):
    project = project_repo.get_project(db, principal, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _invoice(db, principal, invoice_id):
    invoice = repo.get_invoice(db, principal, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


@router.get("/meta")
def billing_meta(principal: Principal = Depends(get_current_principal)):
    return {"detail": {"types": INVOICE_TYPES, "statuses": INVOICE_STATUSES, "tax_rates": [0, 5, 12, 18, 28], "payment_terms": [0, 7, 15, 30, 45, 60, 90]}}


@router.get("/billable")
def billable(project_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return {"detail": repo.billable_summary(db, principal, _project(db, principal, project_id))}


@router.get("/invoices")
def list_invoices(
    offset: int = Query(0, ge=0),
    page_size: int = Query(10, ge=1, le=100),
    project_id: Optional[int] = None,
    status: Optional[str] = None,
    invoice_type: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    rows, total, stats = repo.list_invoices(
        db, principal, page=offset // page_size + 1, page_size=page_size, project_id=project_id, status=status, invoice_type=invoice_type, search=search
    )
    return {"detail": rows, "stack_values": {"count_pg": total, **stats}}


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return {"detail": repo.invoice_detail(db, principal, _invoice(db, principal, invoice_id))}


@router.post("/invoices", status_code=201)
def create_invoice(body: InvoiceCreateIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    project = _project(db, principal, body.project_id)
    try:
        invoice = repo.create_invoice(db, principal, project, body.model_dump())
    except repo.BillingError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"detail": f"Invoice {invoice.invoice_no} created as Draft", "data": repo.invoice_detail(db, principal, invoice)}


@router.post("/invoices/{invoice_id}/status")
def change_invoice_status(invoice_id: int, body: InvoiceStatusIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    try:
        invoice = repo.change_status(db, principal, _invoice(db, principal, invoice_id), body.action, body.paid_date)
    except repo.BillingError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"detail": f"{invoice.invoice_no} is now {invoice.status}", "data": repo.invoice_detail(db, principal, invoice)}
