"""Project expenses (Draft -> Submitted -> Approved / Rejected) and the cost views built on them:
Actual Cost (labour + expenses) and Variance (earned value: are we over budget, are we late)."""
from collections import defaultdict
from datetime import date, datetime, timezone

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.expenses import EDITABLE_EXPENSE_STATUSES, SPENDING_PROJECT_STATUSES, Expense
from app.models.billing import Invoice
from app.models.documents import Document
from app.models.milestones import Milestone
from app.models.projects import Project
from app.models.tasks import Task
from app.models.timesheets import TimeEntry
from app.repositories import notifications as notification_repo
from app.repositories import documents as document_repo
from app.repositories import project_settings as project_settings_repo
from app.repositories import projects as project_repo
from app.repositories.risks import _next_key
from app.schemas.expenses import expense_out
from app.core.access import project_scope


class ExpenseError(Exception):
    """An expense rule was broken; the message is safe to show to the user."""


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _fmt(d):
    return d.strftime("%d %b %Y")


def _live(db: Session, principal):
    return (
        db.query(Expense)
        .join(Project, Project.id == Expense.project_id)
        .filter(Expense.client_id == principal.client_id, Expense.is_deleted == False, Project.is_deleted == False, project_scope(db, principal))  # noqa: E712
    )


def get_expense(db, principal, expense_id):
    return _live(db, principal).filter(Expense.id == expense_id).one_or_none()


def _serialize(db, rows) -> list:
    projects = {p.id: p for p in db.query(Project).filter(Project.id.in_({e.project_id for e in rows} or {-1}))}
    milestones = dict(db.query(Milestone.id, Milestone.name).filter(Milestone.id.in_({e.milestone_id for e in rows if e.milestone_id} or {-1})).all())
    tasks = dict(db.query(Task.id, Task.task_key).filter(Task.id.in_({e.task_id for e in rows if e.task_id} or {-1})).all())
    invoices = dict(db.query(Invoice.id, Invoice.invoice_no).filter(Invoice.id.in_({e.invoice_id for e in rows if e.invoice_id} or {-1})).all())
    receipts = dict(db.query(Document.id, Document.file_name).filter(Document.id.in_({e.receipt_document_id for e in rows if e.receipt_document_id} or {-1}), Document.is_deleted == False).all())  # noqa: E712
    out = [expense_out(e, projects.get(e.project_id), milestones.get(e.milestone_id), tasks.get(e.task_id), invoices.get(e.invoice_id), receipts.get(e.receipt_document_id)) for e in rows]
    for row in out:
        # A receipt deleted from the Documents page is gone: show the expense without one, so it can be attached again.
        if row["receipt_document_id"] not in receipts:
            row["receipt_document_id"] = None
    return out


def list_expenses(db, principal, *, project_id=None, status=None, category=None, search=None, mine=False, offset=0, limit=5):
    base = _live(db, principal)
    if project_id:
        base = base.filter(Expense.project_id == project_id)
    if mine:
        base = base.filter(Expense.spent_by == principal.user_id) if principal.user_id else base.filter(Expense.id == -1)
    if category:
        base = base.filter(Expense.category == category)
    if search:
        like = f"%{search}%"
        base = base.filter(or_(Expense.description.ilike(like), Expense.vendor.ilike(like), Expense.expense_key.ilike(like), Project.project_name.ilike(like)))
    counts = dict(base.with_entities(Expense.status, func.count()).group_by(Expense.status).all())
    sums = dict(base.with_entities(Expense.status, func.coalesce(func.sum(Expense.amount), 0)).group_by(Expense.status).all())
    query = base.filter(Expense.status == status) if status else base
    total = query.count()
    rows = query.order_by(Expense.expense_date.desc(), Expense.id.desc()).offset(offset).limit(limit).all()
    out = _serialize(db, rows)
    # Whether this person may decide each waiting expense (the approval limits), so the screen offers Approve
    # only where it would work - the same rule review() applies.
    from app.repositories import approvals  # local import: approvals reads these models

    for e, row in zip(rows, out):
        can = e.status == "Submitted" and bool(principal.user_id) and e.spent_by != principal.user_id
        if can:
            try:
                approvals.check_expense_authority(db, principal, [e])
            except approvals.ApprovalError:
                can = False
        row["can_approve"] = can
    return out, total, counts, {k: float(v) for k, v in sums.items()}


def _check(db, principal, project, data):
    if project.status not in SPENDING_PROJECT_STATUSES:
        raise ExpenseError(f"{project.project_code} is {project.status}. Expenses can be recorded once the project is Approved (and until it is Closed)")
    d = data["expense_date"]
    if project.start_date and d < project.start_date:
        raise ExpenseError(f"The expense date is before the project starts ({_fmt(project.start_date)})")
    if project.end_date and d > project.end_date:
        raise ExpenseError(f"The expense date is after the project ends ({_fmt(project.end_date)})")
    if data.get("milestone_id"):
        m = db.query(Milestone).filter(Milestone.id == data["milestone_id"], Milestone.project_id == project.id, Milestone.is_deleted == False).one_or_none()  # noqa: E712
        if m is None:
            raise ExpenseError("The milestone you picked is not part of this project")
    if data.get("task_id"):
        t = db.query(Task).filter(Task.id == data["task_id"], Task.project_id == project.id, Task.is_deleted == False).one_or_none()  # noqa: E712
        if t is None:
            raise ExpenseError("The task you picked is not part of this project")


def _own_editable(principal, e: Expense):
    if e.status not in EDITABLE_EXPENSE_STATUSES:
        raise ExpenseError(f"{e.expense_key} is {e.status}, so it can no longer be changed")
    if e.spent_by and e.spent_by != principal.user_id and not principal.is_superadmin:
        raise ExpenseError(f"{e.expense_key} belongs to {e.spent_by_name}; only they can change it")


def create_expense(db, principal, project, data: dict) -> Expense:
    submit = data.pop("submit", False)
    data.pop("project_id", None)
    _check(db, principal, project, data)
    e = Expense(**data, client_id=principal.client_id, project_id=project.id, expense_key=_next_key(db, project, "E"),
                spent_by=principal.user_id, spent_by_name=notification_repo.person_name(principal.user_name) or principal.user_name)
    if submit:
        _check_receipt(db, project, e)
        e.status, e.submitted_at = "Submitted", _utcnow()
    db.add(e)
    db.commit()
    db.refresh(e)
    return e


def update_expense(db, principal, project, e: Expense, data: dict) -> Expense:
    _own_editable(principal, e)
    submit = data.pop("submit", False)
    if data.pop("project_id", e.project_id) != e.project_id:
        raise ExpenseError("An expense cannot be moved to another project; delete it and record it there")
    _check(db, principal, project, data)
    for k, v in data.items():
        setattr(e, k, v)
    if submit:
        _check_receipt(db, project, e)
        e.status, e.submitted_at, e.reject_reason = "Submitted", _utcnow(), None
    db.commit()
    db.refresh(e)
    return e


def _has_receipt(db, e: Expense) -> bool:
    # The receipt must still exist: one deleted from the Documents page no longer counts.
    return bool(e.receipt_document_id) and db.query(Document.id).filter(
        Document.id == e.receipt_document_id, Document.is_deleted == False  # noqa: E712
    ).first() is not None


def _check_receipt(db, project, e: Expense):
    limit = project_settings_repo.get(db, project.id)["receipt_required_above"]
    if limit is not None and float(e.amount) > limit and not _has_receipt(db, e):
        raise ExpenseError(f"{project.project_code} needs a receipt for expenses above ₹{limit:,.0f}. Save it as a draft, attach the bill, then submit")


def attach_receipt(db, principal, project, e: Expense, file_name, data) -> Expense:
    """The bill is stored in Documents (category Receipt); a new upload becomes the next version of the old one
    (a fresh document when the old one was deleted from the Documents page)."""
    _own_editable(principal, e)
    doc = document_repo.save_upload(db, principal, project, file_name=file_name, data=data, title=f"Receipt {e.expense_key}", category="Receipt",
                                    notes=f"{e.category}: {e.description}"[:1000],
                                    # On top of the newest live version (the expense may still point at an older or deleted one).
                                    replaces_id=document_repo.latest_version_id(db, principal, e.receipt_document_id))
    e.receipt_document_id = doc.id
    db.commit()
    db.refresh(e)
    return e


def remove_receipt(db, principal, project, e: Expense) -> None:
    _own_editable(principal, e)
    if not e.receipt_document_id:
        raise ExpenseError(f"{e.expense_key} has no receipt")
    doc = document_repo.get_document(db, principal, e.receipt_document_id)
    e.receipt_document_id = None
    if doc is not None:
        document_repo.delete_document(db, principal, project, doc)
    db.commit()


def delete_expense(db, principal, e: Expense) -> None:
    _own_editable(principal, e)
    e.is_deleted = True
    db.commit()


def submit_expense(db, principal, project, e: Expense) -> Expense:
    _own_editable(principal, e)
    if project.status not in SPENDING_PROJECT_STATUSES:
        raise ExpenseError(f"{project.project_code} is {project.status}, so expenses cannot be sent for approval")
    _check_receipt(db, project, e)
    e.status, e.submitted_at, e.reject_reason = "Submitted", _utcnow(), None
    db.commit()
    db.refresh(e)
    return e


def review(db, principal, ids, approve: bool, reason=None) -> dict:
    rows = _live(db, principal).filter(Expense.id.in_(ids)).all()
    if len(rows) != len(set(ids)):
        raise LookupError("Some of these expenses were not found")
    waiting = [e for e in rows if e.status != "Submitted"]
    if waiting:
        raise ExpenseError(f"{', '.join(e.expense_key for e in waiting[:3])} {'is' if len(waiting) == 1 else 'are'} not waiting for approval. Refresh and try again")
    if not principal.user_id:
        raise ExpenseError("Your login has no user id, so it cannot approve or reject. Please sign in again")
    if any(e.spent_by == principal.user_id for e in rows):
        raise ExpenseError("You cannot approve or reject your own expense. Another manager has to review it")
    # A Closed project's cost is final.
    closed = db.query(Project.project_code).filter(Project.id.in_({e.project_id for e in rows}), Project.status == "Closed").first()
    if closed:
        raise ExpenseError(f"{closed[0]} is Closed, so its expenses can no longer be approved or rejected")
    from app.repositories import approvals  # local import: approvals reads these models

    try:
        approvals.check_expense_authority(db, principal, rows)
    except approvals.ApprovalError as exc:
        raise ExpenseError(str(exc)) from exc
    now = _utcnow()
    reviewer = notification_repo.person_name(principal.user_name) or principal.user_name
    for e in rows:
        e.status = "Approved" if approve else "Rejected"
        e.reviewed_by, e.reviewed_by_name, e.reviewed_at = principal.user_id, reviewer, now
        e.reject_reason = None if approve else reason
        approvals.log(db, principal, "expense", e.id, e.status, project_id=e.project_id, remarks=reason)
        notification_repo.notify(
            db, principal, [(e.spent_by, e.spent_by_name)], "expense",
            f"{reviewer} {'approved' if approve else 'rejected'} {e.expense_key}: ₹{float(e.amount):,.2f} {e.category}",
            body=e.description if approve else f"Reason: {reason}. Edit it and submit again.", link="budget/expenses/", project_id=e.project_id,
        )
    db.flush()
    # Warn when approving pushes a project past its budget (approval still goes through; the manager decided).
    over = []
    if approve:
        for pid in {e.project_id for e in rows}:
            project = db.query(Project).filter(Project.id == pid).one()
            if project.budget is not None:
                from app.repositories import timesheets as timesheet_repo  # local import: timesheets imports this module

                if timesheet_repo.labour_cost(db, pid) + totals(db, pid)["approved"] > float(project.budget):
                    over.append(project.project_code)
    db.commit()
    return {"count": len(rows), "over_budget": over}


def totals(db, project_id) -> dict:
    return totals_for(db, [project_id])[project_id]


def totals_for(db, project_ids) -> dict:
    """{project_id: approved / submitted / draft / billable approved amounts} in one grouped query."""
    rows = (
        db.query(Expense.project_id, Expense.status, Expense.billable, func.coalesce(func.sum(Expense.amount), 0))
        .filter(Expense.project_id.in_(list(project_ids) or [-1]), Expense.is_deleted == False)  # noqa: E712
        .group_by(Expense.project_id, Expense.status, Expense.billable)
        .all()
    )
    out = {pid: {"approved": 0.0, "submitted": 0.0, "draft": 0.0, "billable_approved": 0.0} for pid in project_ids}
    for pid, status, billable, amount in rows:
        t = out[pid]
        if status == "Approved":
            t["approved"] += float(amount)
            if billable:
                t["billable_approved"] += float(amount)
        elif status == "Submitted":
            t["submitted"] += float(amount)
        elif status == "Draft":
            t["draft"] += float(amount)
    return {pid: {k: round(v, 2) for k, v in t.items()} for pid, t in out.items()}


# ------------------------------------------------------------------------------ actual cost


def _month(d):
    return d.strftime("%Y-%m")


def actual_cost(db, principal, project_id=None, months=6) -> dict:
    """Where the money went: labour (approved hours x locked rate) and approved expenses, per project, per category
    and per month."""
    projects = [p for p in project_repo.all_projects(db, principal) if not project_id or p.id == project_id]
    ids = [p.id for p in projects] or [-1]
    today = date.today()
    month_keys = []
    y, m = today.year, today.month
    for _ in range(months):
        month_keys.insert(0, f"{y:04d}-{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)

    labour = defaultdict(float)
    by_month = {k: {"month": k, "labour": 0.0, "expenses": 0.0} for k in month_keys}
    entries = (
        db.query(TimeEntry.project_id, TimeEntry.work_date, TimeEntry.hours, TimeEntry.hourly_rate, TimeEntry.status)
        .join(Task, Task.id == TimeEntry.task_id)
        .filter(TimeEntry.project_id.in_(ids), TimeEntry.is_deleted == False, Task.is_deleted == False, TimeEntry.status == "Approved")  # noqa: E712
    )
    for pid, wd, hours, rate, status in entries:
        cost = float(hours) * float(rate or 0)
        # Only approved hours cost money: their rate is locked when they are approved.
        if status == "Approved":
            labour[pid] += cost
            if _month(wd) in by_month:
                by_month[_month(wd)]["labour"] += cost

    exp_approved = defaultdict(float)
    exp_pending = defaultdict(float)
    by_category = defaultdict(float)
    for pid, cat, amount, status, d in (
        db.query(Expense.project_id, Expense.category, Expense.amount, Expense.status, Expense.expense_date)
        .filter(Expense.project_id.in_(ids), Expense.is_deleted == False, Expense.status.in_(("Approved", "Submitted")))  # noqa: E712
    ):
        if status == "Approved":
            exp_approved[pid] += float(amount)
            by_category[cat] += float(amount)
            if _month(d) in by_month:
                by_month[_month(d)]["expenses"] += float(amount)
        else:
            exp_pending[pid] += float(amount)

    rows = []
    for p in projects:
        total = labour[p.id] + exp_approved[p.id]
        budget = float(p.budget) if p.budget is not None else None
        rows.append({
            "project_id": p.id, "project_code": p.project_code, "project_name": p.project_name, "status": p.status,
            "labour": round(labour[p.id], 2), "expenses": round(exp_approved[p.id], 2), "total": round(total, 2),
            "pending_expenses": round(exp_pending[p.id], 2), "budget": budget,
            "used_pct": round(total / budget * 100, 1) if budget else None,
            "remaining": round(budget - total, 2) if budget is not None else None,
        })
    rows.sort(key=lambda r: -r["total"])
    for v in by_month.values():
        v["labour"], v["expenses"] = round(v["labour"], 2), round(v["expenses"], 2)
    labour_total = round(sum(r["labour"] for r in rows), 2)
    expense_total = round(sum(r["expenses"] for r in rows), 2)
    return {
        "projects": rows,
        "by_category": [{"category": k, "amount": round(v, 2)} for k, v in sorted(by_category.items(), key=lambda kv: -kv[1])],
        "by_month": list(by_month.values()),
        "summary": {
            "labour": labour_total, "expenses": expense_total, "total": round(labour_total + expense_total, 2),
            "pending_expenses": round(sum(r["pending_expenses"] for r in rows), 2),
            "budget": round(sum(r["budget"] for r in rows if r["budget"] is not None), 2),
            # Cost of the projects that have a budget: compare this (not total) with budget for "Budget Used".
            "budgeted_total": round(sum(r["total"] for r in rows if r["budget"] is not None), 2),
        },
    }


# ------------------------------------------------------------------------------ variance (earned value)


def _ratio(a, b):
    return round(a / b, 2) if b else None


def variance(db, principal, project_id=None) -> dict:
    """Earned value per project. BAC = budget, EV = budget x % work done, PV = budget x % of time gone,
    AC = actual cost. CPI = EV / AC (below 1 = over budget), SPI = EV / PV (below 1 = behind schedule),
    EAC = BAC / CPI (expected final cost), VAC = BAC - EAC (expected saving or overrun)."""
    today = date.today()
    cost = {r["project_id"]: r for r in actual_cost(db, principal, project_id)["projects"]}
    projects = [p for p in project_repo.all_projects(db, principal) if not project_id or p.id == project_id]
    progress = project_repo.progress_for(db, [p.id for p in projects])
    rows = []
    for p in projects:
        c = cost.get(p.id, {})
        bac = float(p.budget) if p.budget is not None else None
        pr = progress.get(p.id, {}).get("progress", 0)
        ac = c.get("total", 0.0)
        planned_pct = None
        if p.start_date and p.end_date and p.end_date >= p.start_date:
            span = (p.end_date - p.start_date).days + 1
            planned_pct = max(0.0, min(1.0, ((today - p.start_date).days + 1) / span))
        row = {"project_id": p.id, "project_code": p.project_code, "project_name": p.project_name, "status": p.status,
               "budget": bac, "progress": pr, "planned_pct": round(planned_pct * 100) if planned_pct is not None else None,
               "actual": ac, "labour": c.get("labour", 0.0), "expenses": c.get("expenses", 0.0)}
        if bac is None:
            row.update({"ev": None, "pv": None, "cv": None, "sv": None, "cpi": None, "spi": None, "eac": None, "vac": None,
                        "cost_state": "No budget", "schedule_state": "No budget"})
        else:
            ev = round(bac * pr / 100, 2)
            pv = round(bac * planned_pct, 2) if planned_pct is not None else None
            cpi = _ratio(ev, ac) if ac else None  # rounded, for display only
            spi = _ratio(ev, pv) if pv else None
            # EAC = BAC / CPI = BAC x AC / EV, from the unrounded numbers.
            eac = round(bac * ac / ev, 2) if ac and ev else (round(ac, 2) if pr >= 100 else None)
            row.update({
                "ev": ev, "pv": pv, "cv": round(ev - ac, 2), "sv": round(ev - pv, 2) if pv is not None else None, "cpi": cpi, "spi": spi,
                "eac": eac, "vac": round(bac - eac, 2) if eac is not None else None,
                "cost_state": "Not started" if not ac and not pr else ("Over budget" if cpi is not None and cpi < 0.9 else "Slightly over" if cpi is not None and cpi < 1 else "Under budget" if cpi is not None else "No cost yet"),
                "schedule_state": "No dates" if spi is None and pv is None else ("Behind" if spi is not None and spi < 0.9 else "Slightly behind" if spi is not None and spi < 1 else "On schedule"),
            })
        rows.append(row)
    rows.sort(key=lambda r: (r["cpi"] is None, r["cpi"] if r["cpi"] is not None else 9, r["project_code"]))
    with_budget = [r for r in rows if r["budget"] is not None]
    ev_sum = sum(r["ev"] for r in with_budget)
    ac_sum = sum(r["actual"] for r in with_budget)
    pv_sum = sum(r["pv"] or 0 for r in with_budget)
    # Each portfolio figure compares one set of projects: CPI only over projects that have a cost (EV of work with
    # no cost recorded would inflate it), SPI only over projects with dates, and the forecast over every budgeted
    # project (no forecast yet: the budget, or cost so far + the work left once there is cost but no progress).
    costed = [r for r in with_budget if r["actual"]]
    ev_costed, ac_costed = sum(r["ev"] for r in costed), sum(r["actual"] for r in costed)
    dated = [r for r in with_budget if r["pv"] is not None]
    ev_dated, pv_dated = sum(r["ev"] for r in dated), sum(r["pv"] for r in dated)

    def forecast(r):
        if r["eac"] is not None:
            return r["eac"]
        return r["actual"] + r["budget"] - r["ev"] if r["actual"] else r["budget"]

    return {
        "projects": rows,
        "summary": {
            "budget": round(sum(r["budget"] for r in with_budget), 2), "ev": round(ev_sum, 2), "ac": round(ac_sum, 2), "pv": round(pv_sum, 2),
            "cpi": _ratio(ev_costed, ac_costed) if ac_costed else None, "spi": _ratio(ev_dated, pv_dated) if pv_dated else None,
            "eac": round(sum(forecast(r) for r in with_budget), 2),
            "over_budget": sum(1 for r in rows if r["cost_state"] in ("Over budget", "Slightly over")),
            "behind": sum(1 for r in rows if r["schedule_state"] in ("Behind", "Slightly behind")),
        },
    }
