"""The PMS dashboard: one call returns every card's numbers, for all projects or for one project."""
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import Principal
from app.models.billing import Invoice
from app.models.milestones import Deliverable, Milestone
from app.models.projects import PROJECT_PRIORITIES, PROJECT_STATUSES, Project
from app.models.risks import Issue, Risk, risk_level
from app.models.tasks import TASK_STATUSES, Task, TaskActivity
from app.models.timesheets import TimeEntry
from app.repositories import projects as project_repo
from app.repositories import team as team_repo
from app.repositories import timesheets as timesheet_repo
from app.schemas.projects import project_out
from app.schemas.rules import utc_iso
from app.core.access import project_scope, visible_project_ids

OPEN_STATUSES_EXCLUDED = ("Closed",)


def _projects(db: Session, principal: Principal):
    return db.query(Project).filter(Project.client_id == principal.client_id, Project.is_deleted == False, project_scope(db, principal))  # noqa: E712


def _tasks(db: Session, principal: Principal):
    return db.query(Task).filter(Task.client_id == principal.client_id, Task.is_deleted == False, Task.project_id.in_(visible_project_ids(db, principal)))  # noqa: E712


def _counts(query, column, keys):
    result = dict.fromkeys(keys, 0)
    for key, n in query.with_entities(column, func.count()).group_by(column):
        result[key] = n
    return result


def project_dashboard(db: Session, principal: Principal) -> dict:
    """Older summary (kept for existing callers of /dashboard/summary)."""
    today = date.today()
    soon = today + timedelta(days=30)
    projects = _projects(db, principal)
    status_counts = _counts(projects, Project.status, PROJECT_STATUSES)
    priority_counts = _counts(projects, Project.priority, PROJECT_PRIORITIES)
    open_projects = projects.filter(Project.status.notin_(OPEN_STATUSES_EXCLUDED))
    overdue_q = open_projects.filter(Project.end_date != None, Project.end_date < today)  # noqa: E711
    ending_q = open_projects.filter(Project.end_date != None, Project.end_date >= today, Project.end_date <= soon)  # noqa: E711
    budget_by_status = dict.fromkeys(PROJECT_STATUSES, 0.0)
    for status, total in projects.with_entities(Project.status, func.coalesce(func.sum(Project.budget), 0)).group_by(Project.status):
        budget_by_status[status] = float(total)
    tasks = _tasks(db, principal).join(Project, Project.id == Task.project_id).filter(Project.is_deleted == False)  # noqa: E712
    task_counts = _counts(tasks, Task.status, TASK_STATUSES)
    overdue_tasks = tasks.filter(Task.due_date != None, Task.due_date < today, Task.status != "Done").count()  # noqa: E711
    return {
        "totals": {"projects": sum(status_counts.values()), "active": status_counts["Active"], "overdue": overdue_q.count(),
                   "ending_soon": ending_q.count(), "total_budget": sum(budget_by_status.values())},
        "status_counts": status_counts,
        "priority_counts": priority_counts,
        "budget_by_status": budget_by_status,
        "overdue_projects": [project_out(p) for p in overdue_q.order_by(Project.end_date.asc()).limit(5)],
        "ending_soon_projects": [project_out(p) for p in ending_q.order_by(Project.end_date.asc()).limit(5)],
        "recent_projects": [project_out(p) for p in projects.order_by(Project.created_at.desc(), Project.id.desc()).limit(5)],
        "tasks": {"total": sum(task_counts.values()), "by_status": task_counts, "overdue": overdue_tasks},
    }


# ---------------------------------------------------------------------------- live dashboard


def _health(project, progress, overdue_tasks, budget_health, today, high_risks=0):
    """On Track / At Risk / Delayed, with the reason, from dates, work done, overdue tasks and money."""
    if project.status == "Closed":
        return "On Track", "Closed"
    if project.end_date and project.end_date < today:
        return "Delayed", "Past its end date"
    if budget_health == "Over budget":
        return "Delayed", "Over budget"
    expected = None
    if project.start_date and project.end_date and project.end_date > project.start_date and today > project.start_date:
        expected = min(100, round((today - project.start_date).days / (project.end_date - project.start_date).days * 100))
    if expected is not None and expected - progress >= 25:
        return "Delayed", f"{progress}% done with {expected}% of the time used"
    if budget_health == "At risk":
        return "At Risk", "Spending ahead of progress"
    if expected is not None and expected - progress >= 10:
        return "At Risk", f"{progress}% done with {expected}% of the time used"
    if high_risks:
        return "At Risk", f"{high_risks} high risk{'s' if high_risks > 1 else ''} open"
    if overdue_tasks:
        return "At Risk", f"{overdue_tasks} overdue task{'s' if overdue_tasks > 1 else ''}"
    return "On Track", "On schedule"


def _week_label(d):
    return d.strftime("%d %b")


def overview(db: Session, principal: Principal, project_id=None) -> dict:
    today = date.today()
    all_projects = project_repo.all_projects(db, principal)
    options = [{"id": p.id, "code": p.project_code, "name": p.project_name} for p in all_projects]
    projects = [p for p in all_projects if not project_id or p.id == project_id]
    ids = [p.id for p in projects] or [-1]

    tasks = _tasks(db, principal).filter(Task.project_id.in_(ids)).all()
    by_project = defaultdict(list)
    for t in tasks:
        by_project[t.project_id].append(t)
    progress = project_repo.progress_for(db, ids)

    # ---- open risks and issues
    open_risks = (
        db.query(Risk)
        .filter(Risk.client_id == principal.client_id, Risk.project_id.in_(ids), Risk.is_deleted == False, Risk.status.in_(("Open", "Monitoring")))  # noqa: E712
        .all()
    )
    high_by_project = defaultdict(int)
    for r in open_risks:
        if risk_level(r.probability * r.impact) == "High":
            high_by_project[r.project_id] += 1
    open_issues = (
        db.query(Issue.severity)
        .filter(Issue.client_id == principal.client_id, Issue.project_id.in_(ids), Issue.is_deleted == False, Issue.status.in_(("Open", "In Progress")))  # noqa: E712
        .all()
    )

    # ---- projects (health, progress, money)
    project_rows = []
    budget_planned = budget_actual = 0.0
    for p in projects:
        pr = progress.get(p.id, {}).get("progress", 0)
        overdue = sum(1 for t in by_project[p.id] if t.due_date and t.due_date < today and t.status != "Done")
        b = timesheet_repo.project_budget(db, principal, p, pr)
        health, reason = _health(p, pr, overdue, b["health"], today, high_by_project[p.id])
        budget_planned += b["budget"] or 0
        budget_actual += b["actual_cost"]
        project_rows.append({
            "id": p.id, "code": p.project_code, "name": p.project_name, "short": p.project_name if len(p.project_name) <= 14 else p.project_name[:13] + "…",
            "client": p.customer_name or "Internal", "manager": p.project_manager_name or "-", "status": p.status, "health": health, "health_reason": reason,
            "progress": pr, "end": p.end_date.isoformat() if p.end_date else None, "budgetPlanned": b["budget"] or 0, "budgetActual": b["actual_cost"],
            "billed": b["billed"], "margin": b["margin"],
        })
    # Open work first, then by end date.
    project_rows.sort(key=lambda r: (r["status"] == "Closed", r["end"] or "9999"))

    # ---- tasks
    totals = {"todo": 0, "inProgress": 0, "testing": 0, "done": 0}
    key = {"To Do": "todo", "In Progress": "inProgress", "Testing": "testing", "Done": "done"}
    for t in tasks:
        if t.status in key:
            totals[key[t.status]] += 1
    names = {p.id: p.project_name for p in projects}
    delayed = sorted(
        [
            {"id": t.id, "key": t.task_key, "title": t.title, "projectId": t.project_id, "projectName": names.get(t.project_id), "assignee": t.assignee_name or "Unassigned",
             "due": t.due_date.isoformat(), "daysLate": (today - t.due_date).days, "priority": t.priority}
            for t in tasks if t.due_date and t.due_date < today and t.status != "Done"
        ],
        key=lambda t: -t["daysLate"],
    )

    # ---- throughput: created vs completed per week, last 8 weeks
    this_week = today - timedelta(days=today.weekday())
    weeks = [this_week - timedelta(weeks=i) for i in range(7, -1, -1)]
    created = defaultdict(int)
    for t in tasks:
        if t.created_at:
            created[t.created_at.date() - timedelta(days=t.created_at.date().weekday())] += 1
    completed = defaultdict(int)
    task_ids = [t.id for t in tasks] or [-1]
    for (when,) in (
        db.query(TaskActivity.created_at)
        .filter(TaskActivity.task_id.in_(task_ids), TaskActivity.action == "status", TaskActivity.detail.like("%-> Done%"), TaskActivity.created_at >= weeks[0])
    ):
        completed[when.date() - timedelta(days=when.date().weekday())] += 1
    trend = [{"week": _week_label(w), "created": created[w], "completed": completed[w]} for w in weeks]

    # ---- team (people on these projects, with their load across all projects)
    people = team_repo.allocation_overview(db, principal)
    project_set = set(ids)
    team = [
        {"id": p["key"], "name": p["member_name"], "role": ", ".join(p["roles"]), "allocated": p["total_allocation"], "openTasks": p["open_tasks"]}
        for p in people if any(pr["project_id"] in project_set for pr in p["projects"])
    ]

    # ---- timesheets this week
    entries = (
        db.query(TimeEntry.status, TimeEntry.hours, TimeEntry.work_date, TimeEntry.user_id, TimeEntry.member_name)
        .join(Task, Task.id == TimeEntry.task_id)
        .filter(TimeEntry.client_id == principal.client_id, TimeEntry.is_deleted == False, Task.is_deleted == False, TimeEntry.project_id.in_(ids))  # noqa: E712
        .all()
    )
    week_hours = sum(float(e.hours) for e in entries if e.work_date >= this_week)
    week_approved = sum(float(e.hours) for e in entries if e.work_date >= this_week and e.status == "Approved")
    pending_groups = {(e.user_id or e.member_name, e.work_date - timedelta(days=e.work_date.weekday())) for e in entries if e.status == "Submitted"}

    # ---- milestones + deliverables
    milestones = db.query(Milestone).filter(Milestone.project_id.in_(ids), Milestone.is_deleted == False).order_by(Milestone.due_date).all()  # noqa: E712
    m_ids = [m.id for m in milestones] or [-1]
    invoices = {i.milestone_id: i for i in db.query(Invoice).filter(Invoice.milestone_id.in_(m_ids), Invoice.status != "Cancelled", Invoice.is_deleted == False)}  # noqa: E712
    billable_project = {p.id: p.project_type != "Internal" for p in projects}

    def invoice_label(m):
        inv = invoices.get(m.id)
        if inv:
            return "Paid" if inv.status == "Paid" else "Invoiced"
        if not billable_project.get(m.project_id) or not m.amount:
            return "Not billable"
        return "Ready to invoice" if m.status == "Accepted" else "Not due"

    milestone_rows = [
        {"id": m.id, "title": m.name, "projectId": m.project_id, "projectName": names.get(m.project_id), "due": m.due_date.isoformat() if m.due_date else None,
         "status": m.status, "isOverdue": bool(m.due_date and m.due_date < today and m.status != "Accepted"), "invoice": invoice_label(m), "amount": float(m.amount or 0)}
        for m in milestones
    ]
    milestone_rows.sort(key=lambda m: (m["status"] == "Accepted" and m["invoice"] in ("Paid", "Invoiced"), m["due"] or "9999"))
    m_by_id = {m.id: m for m in milestones}
    deliverables = [
        {"id": d.id, "name": d.name, "projectId": m_by_id[d.milestone_id].project_id, "projectName": names.get(m_by_id[d.milestone_id].project_id),
         "milestone": m_by_id[d.milestone_id].name, "due": m_by_id[d.milestone_id].due_date.isoformat() if m_by_id[d.milestone_id].due_date else None,
         "status": "Done" if d.is_done else "Pending"}
        for d in db.query(Deliverable).filter(Deliverable.milestone_id.in_(m_ids), Deliverable.is_deleted == False).order_by(Deliverable.is_done, Deliverable.id)  # noqa: E712
        if m_by_id[d.milestone_id].status != "Accepted"
    ]

    # ---- billing
    inv_rows = db.query(Invoice).filter(Invoice.client_id == principal.client_id, Invoice.project_id.in_(ids), Invoice.is_deleted == False, Invoice.status != "Cancelled").all()  # noqa: E712
    billing = {
        "draft": round(sum(float(i.total) for i in inv_rows if i.status == "Draft"), 2),
        "outstanding": round(sum(float(i.total) for i in inv_rows if i.status == "Issued"), 2),
        "overdue": sum(1 for i in inv_rows if i.status == "Issued" and i.due_date and i.due_date < today),
        "overdueAmount": round(sum(float(i.total) for i in inv_rows if i.status == "Issued" and i.due_date and i.due_date < today), 2),
        "paid": round(sum(float(i.total) for i in inv_rows if i.status == "Paid"), 2),
        "readyToInvoice": round(sum(m["amount"] for m in milestone_rows if m["invoice"] == "Ready to invoice"), 2),
        "recent": [
            {"id": i.id, "no": i.invoice_no, "projectName": names.get(i.project_id), "total": float(i.total), "status": i.status,
             "isOverdue": bool(i.status == "Issued" and i.due_date and i.due_date < today)}
            for i in sorted(inv_rows, key=lambda i: i.created_at, reverse=True)[:4]
        ],
    }

    # ---- recent activity (task history)
    task_by_id = {t.id: t for t in tasks}
    activity = [
        {"id": a.id, "who": a.actor_name or "Someone", "action": a.action, "detail": a.detail, "taskId": a.task_id,
         "target": f"{task_by_id[a.task_id].task_key} {task_by_id[a.task_id].title}" if a.task_id in task_by_id else "", "when": utc_iso(a.created_at)}
        for a in db.query(TaskActivity).filter(TaskActivity.task_id.in_(task_ids)).order_by(TaskActivity.created_at.desc(), TaskActivity.id.desc()).limit(8)
    ]

    return {
        "projectOptions": options,
        "projects": project_rows,
        "projectCount": len(projects),
        "activeProjects": sum(1 for p in projects if p.status == "Active"),
        "avgProgress": round(sum(r["progress"] for r in project_rows) / len(project_rows)) if project_rows else 0,
        "taskTotals": totals,
        "taskCount": sum(totals.values()),
        "delayedTasks": delayed,
        "budgetPlanned": round(budget_planned, 2),
        "budgetActual": round(budget_actual, 2),
        "budgetUsedPct": round(budget_actual / budget_planned * 100) if budget_planned else 0,
        "teamSize": len(team),
        "team": sorted(team, key=lambda m: -m["allocated"])[:8],
        "timesheets": {"pending": len(pending_groups), "hours": round(week_hours, 2), "approvedPct": round(week_approved / week_hours * 100) if week_hours else 0},
        "milestones": milestone_rows,
        "deliverables": deliverables[:8],
        "billing": billing,
        "activity": activity,
        "trend": trend,
        "riskCounts": {lvl: sum(1 for r in open_risks if risk_level(r.probability * r.impact) == lvl) for lvl in ("High", "Medium", "Low")},
        "risks": [
            {"id": r.id, "key": r.risk_key, "title": r.title, "projectId": r.project_id, "projectName": names.get(r.project_id), "owner": r.owner_name or "No owner",
             "score": r.probability * r.impact, "level": risk_level(r.probability * r.impact)}
            for r in sorted(open_risks, key=lambda r: -(r.probability * r.impact))[:5]
        ],
        "openIssues": len(open_issues),
        "criticalIssues": sum(1 for (sev,) in open_issues if sev in ("Critical", "High")),
        "healthCounts": {h: sum(1 for r in project_rows if r["health"] == h and r["status"] != "Closed") for h in ("On Track", "At Risk", "Delayed")},
    }
