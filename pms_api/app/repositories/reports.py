"""Business reports. Each report returns the same shape - title, columns (with a type for formatting), rows,
totals, summary cards and a chart - so one screen and one CSV export serve all of them."""
import csv
import io
from collections import defaultdict
from datetime import date

from sqlalchemy.orm import Session

from app.core.access import visible_project_ids
from app.models.billing import Invoice
from app.models.projects import Project
from app.models.risks import Issue, Risk, risk_level
from app.models.tasks import Task
from app.models.team import ProjectMember
from app.models.timesheets import TimeEntry
from app.repositories import dashboard as dashboard_repo
from app.repositories import projects as project_repo
from app.repositories.search import ESC, escape_like
from app.repositories import team as team_repo
from app.repositories import timesheets as timesheet_repo
from app.repositories import work_calendar


class ReportError(Exception):
    """Bad report filters; the message is safe to show to the user."""


def _col(key, label, kind="text"):
    return {"key": key, "label": label, "type": kind}


def _range(date_from, date_to):
    today = date.today()
    start = date_from or today.replace(day=1)
    end = date_to or today
    if end < start:
        raise ReportError("To date cannot be before From date")
    if (end - start).days > 366:
        raise ReportError("Pick a period of at most one year")
    return start, end


def _projects(db, principal, project_id=None):
    projects = project_repo.all_projects(db, principal)
    return [p for p in projects if not project_id or p.id == project_id]


# ------------------------------------------------------------------------------ reports


def project_status(db: Session, principal, project_id=None, **_):
    today = date.today()
    projects = _projects(db, principal, project_id)
    progress = project_repo.progress_for(db, [p.id for p in projects])
    budgets = timesheet_repo.project_budgets(db, principal, projects, progress, with_revenue=True)
    rows = []
    for p in projects:
        tasks = db.query(Task.status, Task.due_date).filter(Task.project_id == p.id, Task.is_deleted == False).all()  # noqa: E712
        pr = progress.get(p.id, {}).get("progress", 0)
        overdue = sum(1 for s, d in tasks if d and d < today and s != "Done")
        b = budgets[p.id]
        high = sum(1 for r in db.query(Risk).filter(Risk.project_id == p.id, Risk.is_deleted == False, Risk.status.in_(("Open", "Monitoring")))  # noqa: E712
                   if risk_level(r.probability * r.impact) == "High")
        health, reason = dashboard_repo._health(p, pr, overdue, b["health"], today, high)
        rows.append({
            "code": p.project_code, "project": p.project_name, "client": p.customer_name or "Internal", "manager": p.project_manager_name,
            "status": p.status, "health": health, "health_reason": reason, "progress": pr, "tasks": len(tasks),
            "done": sum(1 for s, _ in tasks if s == "Done"), "overdue": overdue, "start": p.start_date, "end": p.end_date,
            "budget": b["budget"], "actual": b["actual_cost"],
        })
    return {
        "title": "Project Status",
        "description": "Where every project stands: progress, health, overdue work and spend.",
        "columns": [_col("code", "Code"), _col("project", "Project"), _col("client", "Client"), _col("manager", "Manager"), _col("status", "Status", "chip"),
                    _col("health", "Health", "chip"), _col("progress", "Progress", "percent"), _col("tasks", "Tasks", "number"), _col("done", "Done", "number"),
                    _col("overdue", "Overdue", "number"), _col("start", "Start", "date"), _col("end", "End", "date"), _col("budget", "Budget", "money"), _col("actual", "Actual Cost", "money")],
        "rows": rows,
        "totals": {"tasks": sum(r["tasks"] for r in rows), "done": sum(r["done"] for r in rows), "overdue": sum(r["overdue"] for r in rows),
                   "budget": sum(r["budget"] or 0 for r in rows), "actual": sum(r["actual"] for r in rows)},
        "summary": [
            {"label": "Projects", "value": len(rows), "type": "number"},
            {"label": "On Track", "value": sum(1 for r in rows if r["health"] == "On Track"), "type": "number"},
            {"label": "At Risk / Delayed", "value": sum(1 for r in rows if r["health"] != "On Track"), "type": "number"},
            {"label": "Overdue Tasks", "value": sum(r["overdue"] for r in rows), "type": "number"},
        ],
        "chart": {"x": "code", "series": [{"key": "progress", "label": "Progress %"}]},
    }


def timesheet_hours(db: Session, principal, project_id=None, date_from=None, date_to=None, person=None, **_):
    start, end = _range(date_from, date_to)
    ids = [p.id for p in _projects(db, principal, project_id)] or [-1]
    query = (
        db.query(TimeEntry, Project.project_code, Project.project_name, ProjectMember.hourly_rate)
        .join(Task, Task.id == TimeEntry.task_id).join(Project, Project.id == TimeEntry.project_id).join(ProjectMember, ProjectMember.id == TimeEntry.member_id)
        .filter(TimeEntry.client_id == principal.client_id, TimeEntry.is_deleted == False, Task.is_deleted == False,  # noqa: E712
                TimeEntry.project_id.in_(ids), TimeEntry.work_date >= start, TimeEntry.work_date <= end)
    )
    if person:
        query = query.filter(TimeEntry.member_name.ilike(f"%{escape_like(person)}%", escape=ESC))
    groups = {}
    for e, code, name, rate in query:
        g = groups.setdefault((e.member_name, code), {"person": e.member_name, "code": code, "project": name, "approved": 0.0, "submitted": 0.0, "draft": 0.0, "rejected": 0.0, "cost": 0.0})
        hours = float(e.hours)
        g[{"Approved": "approved", "Submitted": "submitted", "Draft": "draft", "Rejected": "rejected"}[e.status]] += hours
        if e.status == "Approved":
            used_rate = e.hourly_rate if e.hourly_rate is not None else rate
            g["cost"] += hours * float(used_rate or 0)
    rows = sorted(groups.values(), key=lambda r: (r["person"].lower(), r["code"]))
    for r in rows:
        r["total"] = r["approved"] + r["submitted"] + r["draft"]
    totals = {k: round(sum(r[k] for r in rows), 2) for k in ("approved", "submitted", "draft", "rejected", "total", "cost")}
    return {
        "title": "Timesheet Hours",
        "description": f"Hours logged per person and project, {start.strftime('%d %b %Y')} to {end.strftime('%d %b %Y')}.",
        "columns": [_col("person", "Person"), _col("code", "Code"), _col("project", "Project"), _col("approved", "Approved", "hours"), _col("submitted", "Waiting", "hours"),
                    _col("draft", "Draft", "hours"), _col("rejected", "Rejected", "hours"), _col("total", "Total", "hours"), _col("cost", "Approved Cost", "money")],
        "rows": rows,
        "totals": totals,
        "summary": [
            {"label": "Total Hours", "value": totals["total"], "type": "hours"},
            {"label": "Approved", "value": totals["approved"], "type": "hours"},
            {"label": "Waiting for Approval", "value": totals["submitted"], "type": "hours"},
            {"label": "Approved Cost", "value": totals["cost"], "type": "money"},
        ],
        "chart": {"x": "person", "series": [{"key": "approved", "label": "Approved"}, {"key": "submitted", "label": "Waiting"}], "stacked": True},
        "period": {"from": start.isoformat(), "to": end.isoformat()},
    }


def budget_vs_actual(db: Session, principal, project_id=None, **_):
    projects = _projects(db, principal, project_id)
    progress = project_repo.progress_for(db, [p.id for p in projects])
    budgets = timesheet_repo.project_budgets(db, principal, projects, progress, with_revenue=True)
    rows = []
    for p in projects:
        b = budgets[p.id]
        rows.append({"code": p.project_code, "project": p.project_name, "status": p.status, "budget": b["budget"], "actual": b["actual_cost"],
                     "pending": b["pending_cost"], "remaining": b["remaining"], "used_pct": b["used_pct"], "forecast": b["forecast"],
                     "billed": b["billed"], "collected": b["collected"], "margin": b["margin"], "health": b["health"]})
    money = ("budget", "actual", "pending", "remaining", "billed", "collected", "margin")
    totals = {k: round(sum(r[k] or 0 for r in rows), 2) for k in money}
    return {
        "title": "Budget vs Actual",
        "description": "Planned budget against the cost of approved hours, plus what was billed and collected.",
        "columns": [_col("code", "Code"), _col("project", "Project"), _col("status", "Status", "chip"), _col("budget", "Budget", "money"), _col("actual", "Actual", "money"),
                    _col("pending", "Waiting", "money"), _col("remaining", "Remaining", "money"), _col("used_pct", "Used", "percent"), _col("forecast", "Forecast", "money"),
                    _col("billed", "Billed", "money"), _col("collected", "Collected", "money"), _col("margin", "Margin", "money"), _col("health", "Budget Health", "chip")],
        "rows": rows,
        "totals": totals,
        "summary": [
            {"label": "Total Budget", "value": totals["budget"], "type": "money"},
            {"label": "Actual Cost", "value": totals["actual"], "type": "money"},
            {"label": "Billed", "value": totals["billed"], "type": "money"},
            {"label": "Margin", "value": totals["margin"], "type": "money"},
        ],
        "chart": {"x": "code", "series": [{"key": "budget", "label": "Budget"}, {"key": "actual", "label": "Actual"}, {"key": "billed", "label": "Billed"}]},
    }


def billing(db: Session, principal, project_id=None, date_from=None, date_to=None, status=None, **_):
    start, end = _range(date_from, date_to)
    today = date.today()
    ids = [p.id for p in _projects(db, principal, project_id)] or [-1]
    query = db.query(Invoice, Project.project_code).join(Project, Project.id == Invoice.project_id).filter(
        Invoice.client_id == principal.client_id, Invoice.is_deleted == False, Invoice.project_id.in_(ids)  # noqa: E712
    )
    if status:
        query = query.filter(Invoice.status == status)
    rows = []
    for inv, code in query.order_by(Invoice.created_at):
        on = inv.issue_date or inv.created_at.date()
        if not start <= on <= end:
            continue
        late = (today - inv.due_date).days if inv.status == "Issued" and inv.due_date and inv.due_date < today else 0
        rows.append({"invoice_no": inv.invoice_no, "code": code, "client": inv.customer_name, "type": inv.invoice_type, "status": inv.status,
                     "issue_date": inv.issue_date, "due_date": inv.due_date if inv.status != "Draft" else None, "paid_date": inv.paid_date,
                     "subtotal": float(inv.subtotal), "tax": float(inv.tax_amount), "total": float(inv.total), "days_overdue": late})
    live = [r for r in rows if r["status"] != "Cancelled"]
    totals = {"subtotal": round(sum(r["subtotal"] for r in live), 2), "tax": round(sum(r["tax"] for r in live), 2), "total": round(sum(r["total"] for r in live), 2)}
    # Drafts are not sent yet, so "Invoiced" counts only Issued and Paid (= Collected + Outstanding).
    sent = [r for r in live if r["status"] in ("Issued", "Paid")]
    return {
        "title": "Billing & Collections",
        "description": f"Invoices issued (or drafted) {start.strftime('%d %b %Y')} to {end.strftime('%d %b %Y')}. "
                       "Invoiced = Issued + Paid; drafts are shown on their own. Table totals include drafts; cancelled invoices are listed but not totalled.",
        "columns": [_col("invoice_no", "Invoice"), _col("code", "Project"), _col("client", "Client"), _col("type", "Type"), _col("status", "Status", "chip"),
                    _col("issue_date", "Issued", "date"), _col("due_date", "Due", "date"), _col("paid_date", "Paid", "date"), _col("subtotal", "Subtotal", "money"),
                    _col("tax", "GST", "money"), _col("total", "Total", "money"), _col("days_overdue", "Days Overdue", "number")],
        "rows": rows,
        "totals": totals,
        "summary": [
            {"label": "Invoiced", "value": round(sum(r["total"] for r in sent), 2), "type": "money"},
            {"label": "Collected", "value": round(sum(r["total"] for r in live if r["status"] == "Paid"), 2), "type": "money"},
            {"label": "Outstanding", "value": round(sum(r["total"] for r in live if r["status"] == "Issued"), 2), "type": "money"},
            {"label": "Draft (not sent)", "value": round(sum(r["total"] for r in live if r["status"] == "Draft"), 2), "type": "money"},
            {"label": "Overdue Invoices", "value": sum(1 for r in live if r["days_overdue"]), "type": "number"},
        ],
        "chart": {"x": "invoice_no", "series": [{"key": "total", "label": "Total"}]},
        "period": {"from": start.isoformat(), "to": end.isoformat()},
    }


def risk_register(db: Session, principal, project_id=None, status=None, **_):
    ids = [p.id for p in _projects(db, principal, project_id)] or [-1]
    codes = dict(db.query(Project.id, Project.project_code).filter(Project.id.in_(ids)).all())
    query = db.query(Risk).filter(Risk.client_id == principal.client_id, Risk.is_deleted == False, Risk.project_id.in_(ids))  # noqa: E712
    if status:
        query = query.filter(Risk.status == status)
    issue_counts = defaultdict(int)
    for (rid,) in db.query(Issue.risk_id).filter(Issue.risk_id != None, Issue.is_deleted == False):  # noqa: E711,E712
        issue_counts[rid] += 1
    rows = []
    for r in query:
        score = r.probability * r.impact
        rows.append({"key": r.risk_key, "code": codes.get(r.project_id), "title": r.title, "category": r.category, "probability": r.probability, "impact": r.impact,
                     "score": score, "level": risk_level(score), "status": r.status, "owner": r.owner_name, "review_date": r.review_date,
                     "mitigation": r.mitigation, "issues": issue_counts[r.id]})
    rows.sort(key=lambda r: (r["status"] in ("Closed", "Mitigated", "Occurred"), -r["score"]))
    open_rows = [r for r in rows if r["status"] in ("Open", "Monitoring")]
    return {
        "title": "Risk Register",
        "description": "Every risk with its score (probability x impact), owner and response plan.",
        "columns": [_col("key", "Risk"), _col("code", "Project"), _col("title", "Title"), _col("category", "Category"), _col("probability", "P", "number"), _col("impact", "I", "number"),
                    _col("score", "Score", "number"), _col("level", "Level", "chip"), _col("status", "Status", "chip"), _col("owner", "Owner"),
                    _col("review_date", "Review", "date"), _col("mitigation", "Mitigation"), _col("issues", "Issues", "number")],
        "rows": rows,
        "totals": {"issues": sum(r["issues"] for r in rows)},
        "summary": [
            {"label": "Open Risks", "value": len(open_rows), "type": "number"},
            {"label": "High", "value": sum(1 for r in open_rows if r["level"] == "High"), "type": "number"},
            {"label": "Without Owner", "value": sum(1 for r in open_rows if not r["owner"]), "type": "number"},
            {"label": "Became Issues", "value": sum(1 for r in rows if r["status"] == "Occurred"), "type": "number"},
        ],
        "chart": {"x": "key", "series": [{"key": "score", "label": "Score"}]},
    }


def utilization(db: Session, principal, date_from=None, date_to=None, person=None, **_):
    start, end = _range(date_from, date_to)
    cal = work_calendar.for_client(db, principal.client_id)
    days = cal.count(start, end)
    HOURS_PER_DAY = cal.hours_per_day  # noqa: N806
    people = team_repo.allocation_overview(db, principal)
    if person:
        # "Person" filters on the person's name only (not their role or project names).
        people = [p for p in people if person.lower() in p["member_name"].lower()]
    hours = defaultdict(float)
    # Hours on deleted projects, and on projects this login cannot see, are not counted.
    entries = (
        db.query(TimeEntry.user_id, TimeEntry.member_name, TimeEntry.hours)
        .join(Task, Task.id == TimeEntry.task_id).join(Project, Project.id == TimeEntry.project_id)
        .filter(TimeEntry.client_id == principal.client_id, TimeEntry.is_deleted == False, Task.is_deleted == False, Project.is_deleted == False,  # noqa: E712
                TimeEntry.project_id.in_(visible_project_ids(db, principal)),
                TimeEntry.status == "Approved", TimeEntry.work_date >= start, TimeEntry.work_date <= end)
    )
    for uid, name, h in entries:
        hours[f"u{uid}" if uid else f"n{name.lower()}"] += float(h)
    rows = []
    for p in people:
        planned = round(days * HOURS_PER_DAY * p["total_allocation"] / 100, 2)
        logged = round(hours.get(p["key"], 0.0), 2)
        rows.append({"person": p["member_name"], "roles": ", ".join(p["roles"]), "projects": len(p["projects"]), "allocation": p["total_allocation"],
                     "capacity": days * HOURS_PER_DAY, "planned": planned, "logged": logged,
                     "utilization": round(logged / (days * HOURS_PER_DAY) * 100, 1) if days else 0,
                     "vs_plan": round(logged / planned * 100, 1) if planned else None, "open_tasks": p["open_tasks"]})
    rows.sort(key=lambda r: -r["utilization"])
    return {
        "title": "Resource Utilization",
        "description": f"Approved hours against capacity ({days} working days x {HOURS_PER_DAY} h) and against planned allocation, {start.strftime('%d %b')} to {end.strftime('%d %b %Y')}.",
        "columns": [_col("person", "Person"), _col("roles", "Roles"), _col("projects", "Projects", "number"), _col("allocation", "Allocation", "percent"),
                    _col("capacity", "Capacity", "hours"), _col("planned", "Planned", "hours"), _col("logged", "Logged (approved)", "hours"),
                    _col("utilization", "Utilization", "percent"), _col("vs_plan", "vs Plan", "percent"), _col("open_tasks", "Open Tasks", "number")],
        "rows": rows,
        "totals": {"planned": round(sum(r["planned"] for r in rows), 2), "logged": round(sum(r["logged"] for r in rows), 2), "open_tasks": sum(r["open_tasks"] for r in rows)},
        "summary": [
            {"label": "People", "value": len(rows), "type": "number"},
            {"label": "Working Days", "value": days, "type": "number"},
            {"label": "Hours Logged", "value": round(sum(r["logged"] for r in rows), 2), "type": "hours"},
            {"label": "Average Utilization", "value": round(sum(r["utilization"] for r in rows) / len(rows), 1) if rows else 0, "type": "percent"},
        ],
        "chart": {"x": "person", "series": [{"key": "planned", "label": "Planned"}, {"key": "logged", "label": "Logged"}]},
        "period": {"from": start.isoformat(), "to": end.isoformat()},
    }


def overdue_tasks(db: Session, principal, project_id=None, person=None, **_):
    today = date.today()
    ids = [p.id for p in _projects(db, principal, project_id)] or [-1]
    codes = dict(db.query(Project.id, Project.project_code).filter(Project.id.in_(ids)).all())
    query = db.query(Task).filter(Task.project_id.in_(ids), Task.is_deleted == False, Task.due_date != None, Task.due_date < today, Task.status != "Done")  # noqa: E711,E712
    if person:
        query = query.filter(Task.assignee_name.ilike(f"%{escape_like(person)}%", escape=ESC))
    rows = [{"key": t.task_key, "code": codes.get(t.project_id), "title": t.title, "assignee": t.assignee_name or "Unassigned", "priority": t.priority,
             "status": t.status, "due": t.due_date, "days_late": (today - t.due_date).days} for t in query]
    rows.sort(key=lambda r: -r["days_late"])
    return {
        "title": "Overdue Tasks",
        "description": "Open tasks past their due date, most overdue first.",
        "columns": [_col("key", "Task"), _col("code", "Project"), _col("title", "Title"), _col("assignee", "Assignee"), _col("priority", "Priority", "chip"),
                    _col("status", "Status", "chip"), _col("due", "Due", "date"), _col("days_late", "Days Late", "number")],
        "rows": rows,
        "totals": {},
        "summary": [
            {"label": "Overdue Tasks", "value": len(rows), "type": "number"},
            {"label": "High / Critical", "value": sum(1 for r in rows if r["priority"] in ("High", "Critical")), "type": "number"},
            {"label": "Unassigned", "value": sum(1 for r in rows if r["assignee"] == "Unassigned"), "type": "number"},
            {"label": "Oldest (days)", "value": rows[0]["days_late"] if rows else 0, "type": "number"},
        ],
        "chart": {"x": "assignee", "series": [{"key": "days_late", "label": "Days late"}], "group_count": True},
    }


REPORTS = {
    "project-status": (project_status, "Project Status", "Progress, health and overdue work of every project", ["project"]),
    "timesheet-hours": (timesheet_hours, "Timesheet Hours", "Hours per person and project for a period", ["period", "project", "person"]),
    "budget": (budget_vs_actual, "Budget vs Actual", "Budget, actual cost, billed and margin", ["project"]),
    "billing": (billing, "Billing & Collections", "Invoices, payments and overdue amounts", ["period", "project", "invoice_status"]),
    "risks": (risk_register, "Risk Register", "Risks by score with owners and plans", ["project", "risk_status"]),
    "utilization": (utilization, "Resource Utilization", "Logged hours vs capacity and plan", ["period", "person"]),
    "overdue-tasks": (overdue_tasks, "Overdue Tasks", "Open work past its due date", ["project", "person"]),
}


def run(db, principal, report, **filters) -> dict:
    if report not in REPORTS:
        raise LookupError("Unknown report")
    result = REPORTS[report][0](db, principal, **filters)
    result["generated_at"] = date.today().isoformat()
    return result


def _csv_cell(value):
    """Text starting with = + - @ (or tab/CR) would run as a formula in Excel, so it is prefixed with '."""
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def to_csv(result) -> bytes:
    """CSV with a UTF-8 BOM so Excel shows ₹ and names correctly; dates as yyyy-mm-dd, numbers unformatted."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([_csv_cell(result["title"])])
    writer.writerow([_csv_cell(result.get("description", ""))])
    writer.writerow([])
    keys = [c["key"] for c in result["columns"]]
    writer.writerow([c["label"] for c in result["columns"]])
    for row in result["rows"]:
        writer.writerow([_csv_cell(row.get(k)) for k in keys])
    if result.get("totals"):
        writer.writerow(["Total" if i == 0 else result["totals"].get(k, "") for i, k in enumerate(keys)])
    return ("﻿" + out.getvalue()).encode("utf-8")
