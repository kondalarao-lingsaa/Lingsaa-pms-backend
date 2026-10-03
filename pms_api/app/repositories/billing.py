"""Invoices: per accepted milestone (fixed price) or from approved, not yet billed hours (time & material)."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from app.models.expenses import Expense
from app.models.billing import Invoice, InvoiceLine
from app.models.milestones import Milestone
from app.models.projects import Project
from app.models.tasks import Task
from app.models.team import ProjectMember
from app.models.timesheets import TimeEntry
from app.schemas.billing import invoice_out
from app.core.access import project_scope

NOT_BILLABLE_TYPES = ("Internal",)
CENT = Decimal("0.01")


class BillingError(Exception):
    """A billing rule was broken; the message is safe to show to the user."""


def _money(value) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _live(db: Session, principal):
    return (
        db.query(Invoice)
        .join(Project, Project.id == Invoice.project_id)
        .filter(Invoice.client_id == principal.client_id, Invoice.is_deleted == False, Project.is_deleted == False, project_scope(db, principal))  # noqa: E712
    )


def get_invoice(db, principal, invoice_id):
    return _live(db, principal).filter(Invoice.id == invoice_id).one_or_none()


def _next_invoice_no(db, client_id) -> str:
    year = date.today().year
    # UPDLOCK/HOLDLOCK: two people creating invoices at once never get the same number.
    row = db.execute(
        text("SELECT last_no FROM projectmanagement.invoice_counters WITH (UPDLOCK, HOLDLOCK) WHERE client_id = :c AND year = :y"),
        {"c": client_id, "y": year},
    ).first()
    if row is None:
        next_no = 1
        db.execute(text("INSERT INTO projectmanagement.invoice_counters (client_id, year, last_no) VALUES (:c, :y, 1)"), {"c": client_id, "y": year})
    else:
        next_no = row[0] + 1
        db.execute(text("UPDATE projectmanagement.invoice_counters SET last_no = :n WHERE client_id = :c AND year = :y"), {"n": next_no, "c": client_id, "y": year})
    return f"INV-{year}-{next_no:04d}"


def _unbilled_hours(db, project_id, period_from=None, period_to=None):
    """Approved hours of live tasks not on any active invoice yet."""
    query = (
        db.query(TimeEntry, ProjectMember.role)
        .join(Task, Task.id == TimeEntry.task_id)
        .join(ProjectMember, ProjectMember.id == TimeEntry.member_id)
        .filter(
            TimeEntry.project_id == project_id,
            TimeEntry.status == "Approved",
            TimeEntry.is_deleted == False,  # noqa: E712
            Task.is_deleted == False,  # noqa: E712
            TimeEntry.invoice_id == None,  # noqa: E711
        )
    )
    if period_from:
        query = query.filter(TimeEntry.work_date >= period_from)
    if period_to:
        query = query.filter(TimeEntry.work_date <= period_to)
    return query.order_by(TimeEntry.work_date).all()


def _unbilled_expenses(db, project_id, period_from=None, period_to=None):
    """Approved expenses marked billable that are not on any active invoice yet."""
    query = db.query(Expense).filter(
        Expense.project_id == project_id, Expense.status == "Approved", Expense.billable == True,  # noqa: E712
        Expense.is_deleted == False, Expense.invoice_id == None,  # noqa: E711,E712
    )
    if period_from:
        query = query.filter(Expense.expense_date >= period_from)
    if period_to:
        query = query.filter(Expense.expense_date <= period_to)
    return query.order_by(Expense.expense_date, Expense.id).all()


def _active_invoice_for_milestone(db, milestone_id):
    return db.query(Invoice).filter(Invoice.milestone_id == milestone_id, Invoice.status != "Cancelled", Invoice.is_deleted == False).first()  # noqa: E712


def billable_summary(db, principal, project) -> dict:
    """What can be invoiced for a project right now - drives the Create Invoice form."""
    milestones = (
        db.query(Milestone)
        .filter(Milestone.project_id == project.id, Milestone.is_deleted == False, Milestone.status == "Accepted")  # noqa: E712
        .order_by(Milestone.due_date, Milestone.id)
        .all()
    )
    ready = [
        {"id": m.id, "name": m.name, "amount": float(m.amount) if m.amount is not None else None}
        for m in milestones
        if not _active_invoice_for_milestone(db, m.id)
    ]
    hours = _unbilled_hours(db, project.id)
    unrated = sorted({e.member_name for e, _ in hours if e.hourly_rate is None})
    expenses = _unbilled_expenses(db, project.id)
    dates = [e.work_date for e, _ in hours] + [x.expense_date for x in expenses]
    return {
        "billable": project.project_type not in NOT_BILLABLE_TYPES,
        "project_type": project.project_type,
        "customer_name": project.customer_name,
        "customer_gstin": project.customer_gstin,
        "milestones": ready,
        "unbilled_hours": round(sum(float(e.hours) for e, _ in hours), 2),
        "unbilled_amount": round(sum(float(e.hours) * float(e.hourly_rate) for e, _ in hours if e.hourly_rate is not None), 2),
        "unbilled_from": min(dates).isoformat() if dates else None,
        "unbilled_to": max(dates).isoformat() if dates else None,
        "unbilled_expenses": len(expenses),
        "unbilled_expense_amount": round(sum(float(x.amount) for x in expenses), 2),
        "unbilled_expense_list": [{"id": x.id, "expense_key": x.expense_key, "category": x.category, "description": x.description,
                                   "expense_date": x.expense_date.isoformat(), "amount": float(x.amount)} for x in expenses],
        "unrated_members": unrated,
    }


def create_invoice(db, principal, project, data) -> Invoice:
    if project.project_type in NOT_BILLABLE_TYPES:
        raise BillingError(f"{project.project_code} is an Internal project, so it is not billed to a client")
    if project.status in ("Draft", "Pending Approval"):
        raise BillingError(f"{project.project_code} is {project.status}. Only approved projects can be billed")
    # Lock the project row until commit: two people invoicing the same project at once are handled one
    # after the other, so the second one sees the hours/expenses/milestone the first one already billed.
    db.execute(text("SELECT id FROM projectmanagement.projects WITH (UPDLOCK, HOLDLOCK) WHERE id = :p"), {"p": project.id})

    lines = []
    entries = []
    expenses = []
    milestone = None
    if data["invoice_type"] == "Milestone":
        milestone = db.query(Milestone).filter(Milestone.id == data["milestone_id"], Milestone.project_id == project.id, Milestone.is_deleted == False).one_or_none()  # noqa: E712
        if milestone is None:
            raise BillingError("The milestone was not found in this project")
        if milestone.status != "Accepted":
            raise BillingError(f"'{milestone.name}' is {milestone.status}. Only Accepted milestones can be billed")
        existing = _active_invoice_for_milestone(db, milestone.id)
        if existing:
            raise BillingError(f"'{milestone.name}' is already billed on {existing.invoice_no}")
        if not milestone.amount:
            raise BillingError(f"'{milestone.name}' has no amount. Set its amount first")
        lines.append({"description": f"Milestone: {milestone.name}", "quantity": Decimal("1"), "unit": "item", "rate": _money(milestone.amount)})
    else:
        rows = _unbilled_hours(db, project.id, data["period_from"], data["period_to"])
        expenses = _unbilled_expenses(db, project.id, data["period_from"], data["period_to"]) if data.get("include_expenses", True) else []
        if not rows and not expenses:
            raise BillingError("There are no approved, unbilled hours or billable expenses in this period")
        unrated = sorted({e.member_name for e, _ in rows if e.hourly_rate is None})
        if unrated:
            raise BillingError(f"Hours of {', '.join(unrated)} have no hourly rate. Set rates in Project > Team (they apply to newly approved hours)")
        # One line per person and rate: "Anita Rao (Developer)  12.5 hrs x 800".
        grouped = defaultdict(Decimal)
        for e, role in rows:
            grouped[(e.member_name, role, _money(e.hourly_rate))] += Decimal(e.hours)
        for (name, role, rate), hours in sorted(grouped.items()):
            lines.append({"description": f"{name} ({role})", "quantity": hours, "unit": "hrs", "rate": rate})
        entries = [e for e, _ in rows]
        # Billable expenses are charged at cost, one line each, so the client sees what they pay for.
        for x in expenses:
            lines.append({"description": f"Expense {x.expense_key}: {x.category} - {x.description}"[:500], "quantity": Decimal("1"), "unit": "item", "rate": _money(x.amount)})

    subtotal = sum((_money(line["quantity"] * line["rate"]) for line in lines), Decimal("0"))
    tax = _money(subtotal * Decimal(data["tax_pct"]) / 100)
    invoice = Invoice(
        client_id=principal.client_id,
        project_id=project.id,
        invoice_no=_next_invoice_no(db, principal.client_id),
        invoice_type=data["invoice_type"],
        milestone_id=milestone.id if milestone else None,
        period_from=data.get("period_from") if not milestone else None,
        period_to=data.get("period_to") if not milestone else None,
        customer_name=project.customer_name,
        customer_gstin=project.customer_gstin,
        subtotal=subtotal,
        tax_pct=data["tax_pct"],
        tax_amount=tax,
        total=subtotal + tax,
        status="Draft",
        # Kept as "days after issue" until the invoice is issued; see change_status.
        due_date=date.today() + timedelta(days=data["payment_terms_days"]),
        notes=data.get("notes"),
        created_by=principal.user_id,
        created_by_name=principal.user_name,
    )
    db.add(invoice)
    db.flush()
    for line in lines:
        db.add(InvoiceLine(invoice_id=invoice.id, amount=_money(line["quantity"] * line["rate"]), **line))
    for e in entries:
        e.invoice_id = invoice.id
    for x in expenses:
        x.invoice_id = invoice.id
    db.commit()
    db.refresh(invoice)
    return invoice


def change_status(db, principal, invoice, action, paid_date=None) -> Invoice:
    today = date.today()
    if action == "issue":
        if invoice.status != "Draft":
            raise BillingError(f"{invoice.invoice_no} is {invoice.status}. Only Draft invoices can be issued")
        terms = (invoice.due_date - invoice.created_at.date()).days if invoice.due_date and invoice.created_at else 30
        invoice.issue_date = today
        invoice.due_date = today + timedelta(days=max(0, terms))
        invoice.status = "Issued"
    elif action == "pay":
        if invoice.status != "Issued":
            raise BillingError(f"{invoice.invoice_no} is {invoice.status}. Only Issued invoices can be marked paid")
        paid = paid_date or today
        if paid > today:
            raise BillingError("The payment date cannot be in the future")
        if invoice.issue_date and paid < invoice.issue_date:
            raise BillingError("The payment date cannot be before the invoice was issued")
        invoice.paid_date = paid
        invoice.status = "Paid"
    else:  # cancel
        if invoice.status not in ("Draft", "Issued"):
            raise BillingError(f"{invoice.invoice_no} is {invoice.status} and cannot be cancelled")
        invoice.status = "Cancelled"
        # The hours and expenses can be billed again on a new invoice.
        db.query(TimeEntry).filter(TimeEntry.invoice_id == invoice.id).update({TimeEntry.invoice_id: None}, synchronize_session=False)
        db.query(Expense).filter(Expense.invoice_id == invoice.id).update({Expense.invoice_id: None}, synchronize_session=False)
    db.commit()
    db.refresh(invoice)
    return invoice


def _serialize(db, invoices, with_lines=False):
    project_ids = {i.project_id for i in invoices}
    projects = {p.id: p for p in db.query(Project).filter(Project.id.in_(project_ids))} if project_ids else {}
    milestone_ids = {i.milestone_id for i in invoices if i.milestone_id}
    names = dict(db.query(Milestone.id, Milestone.name).filter(Milestone.id.in_(milestone_ids)).all()) if milestone_ids else {}
    lines = defaultdict(list)
    if with_lines and invoices:
        for line in db.query(InvoiceLine).filter(InvoiceLine.invoice_id.in_([i.id for i in invoices])).order_by(InvoiceLine.id):
            lines[line.invoice_id].append(line)
    return [invoice_out(i, lines=lines.get(i.id), project=projects.get(i.project_id), milestone_name=names.get(i.milestone_id)) for i in invoices]


def invoice_detail(db, principal, invoice) -> dict:
    return _serialize(db, [invoice], with_lines=True)[0]


def list_invoices(db, principal, *, page=1, page_size=10, project_id=None, status=None, invoice_type=None, search=None):
    query = _live(db, principal)
    if project_id:
        query = query.filter(Invoice.project_id == project_id)
    if invoice_type:
        query = query.filter(Invoice.invoice_type == invoice_type)
    if search:
        like = f"%{search}%"
        query = query.filter(or_(Invoice.invoice_no.ilike(like), Invoice.customer_name.ilike(like), Project.project_name.ilike(like), Project.project_code.ilike(like)))

    everything = query.all()
    today = date.today()
    stats = {
        "draft": round(sum(float(i.total) for i in everything if i.status == "Draft"), 2),
        "outstanding": round(sum(float(i.total) for i in everything if i.status == "Issued"), 2),
        "overdue": sum(1 for i in everything if i.status == "Issued" and i.due_date and i.due_date < today),
        "paid": round(sum(float(i.total) for i in everything if i.status == "Paid"), 2),
        "status_counts": {s: sum(1 for i in everything if i.status == s) for s in ("Draft", "Issued", "Paid", "Cancelled")},
    }
    if status:
        query = query.filter(Invoice.status == status)
    total = query.count()
    rows = query.order_by(Invoice.created_at.desc(), Invoice.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return _serialize(db, rows), total, stats


def project_revenue(db, project_id) -> dict:
    """Billed (issued + paid, before tax) and collected amounts - the income side of the budget."""
    rows = db.query(Invoice.status, Invoice.subtotal).filter(Invoice.project_id == project_id, Invoice.is_deleted == False, Invoice.status.in_(("Issued", "Paid"))).all()  # noqa: E712
    return {
        "billed": round(sum(float(s) for _, s in rows), 2),
        "collected": round(sum(float(s) for st, s in rows if st == "Paid"), 2),
    }
