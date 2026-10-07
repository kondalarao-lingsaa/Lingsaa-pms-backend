"""What each automation job does (settings, schedule and run history: app/repositories/automation.py).

Scheduled jobs: RUNNERS[key](db, client_id, params, today) -> {"items": how many things it did, "summary": text}.
Event jobs: after_task_status / after_deliverable_done / after_milestone_accepted, called by the workflows.

Automation acts as "Automation" (no login, company-wide). It never bypasses a rule: an invoice, a task or a
sprint change goes through the same repository functions a person's click does, so the same checks apply.
"""
import logging
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core import roles
from app.core.access import resolve_role
from app.core.security import Principal
from app.models.access import UserRole
from app.models.automation import RecurringTask
from app.models.billing import Invoice
from app.models.milestones import Milestone
from app.models.projects import Project
from app.models.sprints import Sprint
from app.models.tasks import Task
from app.models.team import ProjectMember
from app.models.timesheets import TimeEntry
from app.repositories import automation as engine
from app.repositories import notifications as notification_repo
from app.repositories import project_settings as project_settings_repo
from app.repositories import recurring as recurring_repo
from app.repositories import work_calendar
from app.repositories.approvals import _inr
from app.repositories.automation import FINANCE_ROLES, SENIOR_ROLES, once, people_with_roles, system_principal
from app.repositories.task_activity import log_activity, open_blockers

logger = logging.getLogger("pms.automation")


def _day(d: date) -> str:
    return d.strftime("%d %b %Y")


def _plural(n, word, plural=None) -> str:
    return f"{n} {word if n == 1 else (plural or word + 's')}"


def _lines(items, limit=10) -> str:
    items = list(items)
    shown = items[:limit]
    more = len(items) - len(shown)
    return "\n".join(f"- {i}" for i in shown) + (f"\n- ... and {more} more" if more > 0 else "")


def _pm(project) -> list:
    return [(project.project_manager_id, project.project_manager_name)] if (project.project_manager_id or project.project_manager_name) else []


def _project_link(project_id, tab=None) -> str:
    return f"projects/projectDetails/?id={project_id}" + (f"&tab={tab}" if tab else "")


def _finance(db, client_id) -> list:
    """Finance logins; a company without one sends money matters to its Admins."""
    return people_with_roles(db, client_id, FINANCE_ROLES) or people_with_roles(db, client_id, (roles.ADMIN,))


def _next_working_day(cal, day: date) -> date:
    nxt = day + timedelta(days=1)
    for _ in range(14):
        if cal.is_working(nxt):
            return nxt
        nxt += timedelta(days=1)
    return day + timedelta(days=1)


# ============================================================================== reminders


def task_reminders(db: Session, client_id, params, today: date) -> dict:
    sp = system_principal(client_id)
    cal = work_calendar.for_client(db, client_id)
    soon = _next_working_day(cal, today)
    rows = (
        db.query(Task, Project)
        .join(Project, Project.id == Task.project_id)
        .filter(Task.client_id == client_id, Task.is_deleted == False, Project.is_deleted == False, Project.status == "Active",  # noqa: E712
                Task.status != "Done", Task.due_date != None, Task.due_date <= soon)  # noqa: E711
        .order_by(Task.due_date, Task.task_key)
        .all()
    )
    people = {}
    for t, p in rows:
        if not (t.assignee_id or t.assignee_name):
            continue
        key = f"u{t.assignee_id}" if t.assignee_id else f"n{t.assignee_name.strip().lower()}"
        person = people.setdefault(key, {"to": (t.assignee_id, t.assignee_name), "overdue": [], "due": []})
        (person["overdue"] if t.due_date < today else person["due"]).append(t)

    reminded = 0
    for person in people.values():
        overdue, due = person["overdue"], person["due"]
        lines = [f"{t.task_key} {t.title} - {_plural((today - t.due_date).days, 'day')} overdue" for t in overdue]
        lines += [f"{t.task_key} {t.title} - due {'today' if t.due_date == today else 'on ' + t.due_date.strftime('%a %d %b')}" for t in due]
        parts = [f"{len(overdue)} overdue" if overdue else "", f"{len(due)} due soon" if due else ""]
        reminded += notification_repo.notify(
            db, sp, [person["to"]], "reminder", f"Task reminder: {' and '.join(p for p in parts if p)}", body=_lines(lines),
            link="tasks/myTasks/",
        )

    # Escalation: once per task and due date (moving the due date starts the count again).
    limit = params["escalate_after_days"]
    by_pm = defaultdict(list)
    for t, p in rows:
        late = (today - t.due_date).days
        if late >= limit and _pm(p) and once(db, client_id, "task_reminders", f"esc:{t.id}:{t.due_date}"):
            by_pm[_pm(p)[0]].append((t, p, late))
    escalated = 0
    for pm, items in by_pm.items():
        project_ids = {p.id for _, p, _ in items}
        escalated += notification_repo.notify(
            db, sp, [pm], "reminder",
            f"Escalated: {_plural(len(items), 'task')} overdue {limit}+ days on your project{'s' if len(project_ids) > 1 else ''}",
            body=_lines(f"{t.task_key} {t.title} - {t.assignee_name or 'unassigned'}, {late} days overdue" for t, _, late in items),
            link=_project_link(items[0][1].id, "tasks") if len(project_ids) == 1 else "tasks/allTasks/",
            project_id=items[0][1].id if len(project_ids) == 1 else None,
        )
    db.commit()
    return {"items": reminded + escalated,
            "summary": f"{_plural(reminded, 'person', 'people')} reminded about {_plural(len(rows), 'task')}; "
                       f"{_plural(escalated, 'project manager')} told about late tasks"}


APPROVER_ROLES = (roles.ADMIN, roles.DIRECTOR, roles.PROJECT_MANAGER, roles.TEAM_LEAD, roles.FINANCE)


def approval_reminders(db: Session, client_id, params, today: date) -> dict:
    from app.repositories import approvals  # local import: approvals reads many repositories

    remind, escalate = params["remind_after_days"], params["escalate_after_days"]
    sp = system_principal(client_id)
    reminders = escalations = 0
    approvers = db.query(UserRole).filter(UserRole.client_id == client_id, UserRole.is_active == True,  # noqa: E712
                                          UserRole.role.in_(APPROVER_ROLES)).all()
    for row in approvers:
        person = Principal(client_id=client_id, user_id=row.user_id, user_name=row.user_name, role=None, is_superadmin=False, raw_claims={})
        resolve_role(db, person)
        waiting = [i for i in approvals.inbox(db, person)["items"] if (i.get("waiting_days") or 0) >= remind]
        if not waiting:
            continue
        oldest = max(i["waiting_days"] for i in waiting)
        reminders += notification_repo.notify(
            db, sp, [(row.user_id, row.user_name)], "reminder",
            f"{_plural(len(waiting), 'request')} waiting for your approval (oldest {oldest} days)",
            body=_lines(f"{i['project_code']} {i['title']} - {i['waiting_days']} days" for i in waiting), link="approvals/",
        )
        late = [i for i in waiting if i["waiting_days"] >= escalate]
        if late and row.role != roles.ADMIN:
            escalations += notification_repo.notify(
                db, sp, people_with_roles(db, client_id, (roles.ADMIN,)), "reminder",
                f"Escalated: {_plural(len(late), 'request')} waiting {escalate}+ days for {row.user_name}",
                body=_lines(f"{i['project_code']} {i['title']} ({i['waiting_days']} days)" for i in late), link="approvals/",
            )
    db.commit()
    return {"items": reminders + escalations, "reminders": reminders, "escalations": escalations,
            "summary": f"{_plural(reminders, 'approver')} reminded; {_plural(escalations, 'escalation')} sent to Admins"}


def _active_memberships(db, client_id, start: date, end: date, exclude_managers=False):
    """(member, project) of people with a login and a share of their time on Active projects during start..end."""
    rows = (
        db.query(ProjectMember, Project)
        .join(Project, Project.id == ProjectMember.project_id)
        .filter(ProjectMember.client_id == client_id, ProjectMember.is_deleted == False, ProjectMember.allocation_pct > 0,  # noqa: E712
                Project.is_deleted == False, Project.status == "Active")  # noqa: E712
        .all()
    )
    out = []
    for m, p in rows:
        if (m.start_date and m.start_date > end) or (m.end_date and m.end_date < start) or (p.start_date and p.start_date > end):
            continue
        if exclude_managers and ((m.user_id and m.user_id == p.project_manager_id) or
                                 (p.project_manager_name and m.member_name.lower() == p.project_manager_name.lower())):
            continue
        out.append((m, p))
    return out


def timesheet_reminders(db: Session, client_id, params, today: date) -> dict:
    sp = system_principal(client_id)
    week_start = today - timedelta(days=today.weekday())
    people = {m.user_id: m.member_name for m, _ in _active_memberships(db, client_id, week_start, today) if m.user_id}
    if not people:
        return {"items": 0, "summary": "Nobody with a login is on an Active project this week"}
    hours = defaultdict(lambda: defaultdict(float))
    for uid, status, h in (
        db.query(TimeEntry.user_id, TimeEntry.status, func.sum(TimeEntry.hours))
        .join(Task, Task.id == TimeEntry.task_id)
        .join(Project, Project.id == TimeEntry.project_id)
        .filter(TimeEntry.client_id == client_id, TimeEntry.is_deleted == False, TimeEntry.user_id.in_(list(people)),  # noqa: E712
                Task.is_deleted == False, Project.is_deleted == False,  # noqa: E712
                TimeEntry.work_date >= week_start, TimeEntry.work_date <= today)
        .group_by(TimeEntry.user_id, TimeEntry.status)
    ):
        hours[uid][status] = float(h or 0)
    sent = 0
    for uid, name in people.items():
        logged = sum(hours[uid].values())
        unsent = hours[uid]["Draft"] + hours[uid]["Rejected"]
        if not logged:
            title = "Timesheet reminder: no hours logged this week"
        elif unsent:
            title = f"Timesheet reminder: {unsent:g} h of this week's {logged:g} h not submitted yet"
        else:
            continue
        sent += notification_repo.notify(
            db, sp, [(uid, name)], "reminder", title,
            body=f"Log your hours for {week_start.strftime('%d %b')} - {today.strftime('%d %b')} and press Submit, so they can be approved.",
            link="timesheets/myTimesheets/",
        )
    db.commit()
    return {"items": sent, "summary": f"{_plural(sent, 'person', 'people')} reminded to log or submit hours"}


def timesheet_missing(db: Session, client_id, params, today: date) -> dict:
    sp = system_principal(client_id)
    start = today - timedelta(days=today.weekday() + 7)
    end = start + timedelta(days=6)
    memberships = _active_memberships(db, client_id, start, end, exclude_managers=True)
    if not memberships:
        return {"items": 0, "summary": "No team members on Active projects last week"}
    stats = defaultdict(lambda: defaultdict(float))
    for member_id, status, h in (
        db.query(TimeEntry.member_id, TimeEntry.status, func.sum(TimeEntry.hours))
        .filter(TimeEntry.client_id == client_id, TimeEntry.is_deleted == False, TimeEntry.member_id.in_([m.id for m, _ in memberships]),  # noqa: E712
                TimeEntry.work_date >= start, TimeEntry.work_date <= end)
        .group_by(TimeEntry.member_id, TimeEntry.status)
    ):
        stats[member_id][status] = float(h or 0)
    by_project = defaultdict(list)
    projects = {}
    for m, p in memberships:
        logged = sum(stats[m.id].values())
        unsent = stats[m.id]["Draft"] + stats[m.id]["Rejected"]
        if not logged:
            by_project[p.id].append(f"{m.member_name} (nothing logged)")
        elif unsent:
            by_project[p.id].append(f"{m.member_name} ({unsent:g} h not submitted)")
        projects[p.id] = p
    by_pm = defaultdict(list)
    for pid, names in by_project.items():
        if _pm(projects[pid]):
            by_pm[_pm(projects[pid])[0]].append((projects[pid], names))
    sent = people_missing = 0
    for pm, items in by_pm.items():
        count = sum(len(n) for _, n in items)
        people_missing += count
        sent += notification_repo.notify(
            db, sp, [pm], "reminder",
            f"Missing timesheets for {start.strftime('%d %b')} - {end.strftime('%d %b')}: {_plural(count, 'person', 'people')}",
            body=_lines(f"{p.project_code} {p.project_name}: {', '.join(n)}" for p, n in items), link="timesheets/teamTimesheets/",
        )
    db.commit()
    return {"items": sent, "summary": f"{_plural(sent, 'project manager')} told about {_plural(people_missing, 'missing timesheet')}"}


# ============================================================================== reports and alerts


def weekly_status_report(db: Session, client_id, params, today: date) -> dict:
    from app.repositories import dashboard as dashboard_repo  # local import: the dashboard reads most repositories

    sp = system_principal(client_id)
    data = dashboard_repo.overview(db, sp)
    rows = [r for r in data["projects"] if r["status"] in ("Approved", "Active", "On Hold")]
    if not rows:
        return {"items": 0, "summary": "No open projects to report on"}
    overdue = defaultdict(int)
    for t in data["delayedTasks"]:
        overdue[t["projectId"]] += 1
    next_milestone = {}
    for m in data["milestones"]:
        if m["status"] != "Accepted" and m["due"] and m["projectId"] not in next_milestone:
            next_milestone[m["projectId"]] = m
    managers = {p.id: _pm(p) for p in db.query(Project).filter(Project.id.in_([r["id"] for r in rows]))}
    order = {"Delayed": 0, "At Risk": 1, "On Track": 2}
    rows.sort(key=lambda r: (order.get(r["health"], 3), r["code"]))

    def line(r) -> str:
        used = f"{round(r['budgetActual'] / r['budgetPlanned'] * 100)}% of {_inr(r['budgetPlanned'])}" if r["budgetPlanned"] else "no budget set"
        m = next_milestone.get(r["id"])
        parts = [f"{r['code']} {r['name']} ({r['status']}) - {r['health']}: {r['health_reason']}",
                 f"  {r['progress']}% done, {_plural(overdue[r['id']], 'overdue task')}, budget used {used}"]
        if m:
            parts.append(f"  Next milestone: {m['title']} on {date.fromisoformat(m['due']).strftime('%d %b')}" + (" (overdue)" if m["isOverdue"] else ""))
        return "\n".join(parts)

    def send(to, items) -> int:
        counts = {h: sum(1 for r in items if r["health"] == h) for h in order}
        title = (f"Weekly status, {today.strftime('%d %b')}: {_plural(len(items), 'project')} - {counts['On Track']} on track, "
                 f"{counts['At Risk']} at risk, {counts['Delayed']} delayed")
        short = _lines((f"{r['code']} {r['name']}: {r['health']}, {r['progress']}% done" for r in items), limit=8)
        full = "\n\n".join(line(r) for r in items)
        return notification_repo.notify(db, sp, to, "report", title, body=short, link="dashboard/", email_body=full)

    seniors = people_with_roles(db, client_id, SENIOR_ROLES)
    sent = send(seniors, rows) if seniors else 0
    senior_ids = {uid for uid, _ in seniors}
    by_pm = defaultdict(list)
    for r in rows:
        for pm in managers.get(r["id"], []):
            if not pm[0] or pm[0] not in senior_ids:
                by_pm[pm].append(r)
    for pm, items in by_pm.items():
        sent += send([pm], items)
    db.commit()
    return {"items": sent, "summary": f"Status of {_plural(len(rows), 'project')} sent to {_plural(sent, 'person', 'people')}"}


def budget_alerts(db: Session, client_id, params, today: date) -> dict:
    from app.repositories import projects as project_repo
    from app.repositories import timesheets as timesheet_repo

    sp = system_principal(client_id)
    projects = db.query(Project).filter(Project.client_id == client_id, Project.is_deleted == False,  # noqa: E712
                                        Project.status.in_(("Active", "On Hold")), Project.budget > 0).all()
    if not projects:
        return {"items": 0, "summary": "No Active projects with a budget"}
    budgets = timesheet_repo.project_budgets(db, sp, projects, project_repo.progress_for(db, [p.id for p in projects]))
    watchers = _finance(db, client_id) + people_with_roles(db, client_id, (roles.DIRECTOR,))
    alerted = []
    for p in projects:
        b = budgets[p.id]
        alert_pct = project_settings_repo.get(db, p.id)["budget_alert_pct"]
        level = "over" if b["actual_cost"] > b["budget"] else "alert" if (b["used_pct"] or 0) >= alert_pct else None
        if level is None:
            continue
        ref = f"{p.id}:{{}}:{int(b['budget'])}"
        if not once(db, client_id, "budget_alerts", ref.format(level)):
            continue
        if level == "over":
            once(db, client_id, "budget_alerts", ref.format("alert"))  # the lower warning would come too late now
            title = f"{p.project_code} {p.project_name} is over budget: {_inr(b['actual_cost'])} spent of {_inr(b['budget'])}"
        else:
            title = f"{p.project_code} {p.project_name} has used {b['used_pct']:.0f}% of its budget (alert at {alert_pct}%)"
        body = (f"Approved cost {_inr(b['actual_cost'])} of {_inr(b['budget'])}; {_inr(b['pending_cost'])} more is waiting for approval."
                + (f" At this rate it will cost about {_inr(b['forecast'])}." if b["forecast"] else "")
                + " Review the spending, or raise a change request for more budget.")
        notification_repo.notify(db, sp, _pm(p) + watchers, "automation", title, body=body, link=_project_link(p.id, "budget"), project_id=p.id)
        alerted.append(f"{p.project_code} ({'over budget' if level == 'over' else f'{b['used_pct']:.0f}%'})")
    db.commit()
    return {"items": len(alerted), "summary": ("Alerts sent for " + ", ".join(alerted)) if alerted else "No project newly crossed its alert level"}


def deadline_alerts(db: Session, client_id, params, today: date) -> dict:
    from app.repositories import projects as project_repo

    sp = system_principal(client_id)
    horizon = today + timedelta(days=params["days_before"])
    projects = db.query(Project).filter(Project.client_id == client_id, Project.is_deleted == False, Project.status == "Active",  # noqa: E712
                                        Project.end_date != None, Project.end_date <= horizon).all()  # noqa: E711
    progress = project_repo.progress_for(db, [p.id for p in projects])
    sent = []
    for p in projects:
        done = progress.get(p.id, {}).get("progress", 0)
        if done >= 100 and progress.get(p.id, {}).get("task_count"):
            continue
        past = p.end_date < today
        if not once(db, client_id, "deadline_alerts", f"{p.id}:{p.end_date}:{'past' if past else 'soon'}"):
            continue
        open_tasks = db.query(func.count(Task.id)).filter(Task.project_id == p.id, Task.is_deleted == False, Task.status != "Done").scalar()  # noqa: E712
        late_tasks = db.query(func.count(Task.id)).filter(Task.project_id == p.id, Task.is_deleted == False, Task.status != "Done",  # noqa: E712
                                                          Task.due_date < today).scalar()
        if past:
            title = f"{p.project_code} {p.project_name} is past its end date ({_day(p.end_date)}) with {done}% done"
        else:
            days = (p.end_date - today).days
            title = f"{p.project_code} {p.project_name} ends {'today' if not days else f'in {_plural(days, 'day')}'} ({_day(p.end_date)}) with {done}% done"
        body = (f"{_plural(open_tasks, 'open task')} ({late_tasks} overdue). Finish the remaining work, close the project when it is "
                "delivered, or raise a change request to move the end date.")
        notification_repo.notify(db, sp, _pm(p), "reminder", title, body=body, link=_project_link(p.id), project_id=p.id)
        sent.append(p.project_code)
    db.commit()
    return {"items": len(sent), "summary": ("Deadline alerts for " + ", ".join(sent)) if sent else "No project newly near or past its end date"}


# ============================================================================== billing


def _invoice_terms(db, project_id) -> dict:
    s = project_settings_repo.get(db, project_id)
    return {"tax_pct": Decimal(str(s["default_tax_pct"])), "payment_terms_days": int(s["default_payment_terms"])}


def monthly_invoices(db: Session, client_id, params, today: date) -> dict:
    from app.repositories import billing as billing_repo

    sp = system_principal(client_id)
    period_to = today.replace(day=1) - timedelta(days=1)
    period_from = period_to.replace(day=1)
    month = period_from.strftime("%B %Y")
    projects = (
        db.query(Project)
        .filter(Project.client_id == client_id, Project.is_deleted == False, Project.status.in_(("Approved", "Active", "On Hold", "Closed")),  # noqa: E712
                or_(Project.project_type == None, Project.project_type.notin_(billing_repo.NOT_BILLABLE_TYPES)))  # noqa: E711
        .order_by(Project.project_code)
        .all()
    )
    created, problems = [], []
    for p in projects:
        data = {"invoice_type": "Time & Material", "period_from": period_from, "period_to": period_to, "include_expenses": True,
                "notes": f"Work and billable expenses of {month}. Drafted by Automation", **_invoice_terms(db, p.id)}
        try:
            invoice = billing_repo.create_invoice(db, sp, p, data)
        except billing_repo.BillingError as exc:
            db.rollback()
            reason = str(exc)
            if "no approved, unbilled" in reason or "no billable expenses" in reason:
                continue  # nothing to bill this month
            problems.append(f"{p.project_code}: {reason}")
            notification_repo.notify(db, sp, _pm(p), "automation", f"The {month} invoice for {p.project_code} {p.project_name} could not be drafted",
                                     body=reason, link="billing/", project_id=p.id)
            db.commit()
            continue
        created.append((p, invoice))
        notification_repo.notify(db, sp, _pm(p), "automation", f"Draft invoice {invoice.invoice_no} ({_inr(invoice.total)}) created for {p.project_code} - {month}",
                                 body="Finance will review and issue it.", link="billing/", project_id=p.id)
        db.commit()
    if created:
        notification_repo.notify(
            db, sp, _finance(db, client_id), "automation", f"{_plural(len(created), 'draft invoice')} for {month} ready to review",
            body=_lines(f"{i.invoice_no} {p.project_code} {p.project_name} ({p.customer_name or '-'}): {_inr(i.total)}" for p, i in created)
            + (f"\nNot drafted: {'; '.join(problems)}" if problems else ""),
            link="billing/",
        )
        db.commit()
    summary = f"{_plural(len(created), 'draft invoice')} for {month}" + (f" ({', '.join(i.invoice_no for _, i in created)})" if created else "")
    if problems:
        summary += f"; not drafted: {'; '.join(problems)}"
    return {"items": len(created) + len(problems), "summary": summary}


def invoice_reminders(db: Session, client_id, params, today: date) -> dict:
    sp = system_principal(client_id)
    soon_days, repeat = params["due_soon_days"], params["repeat_every_days"]
    rows = (
        db.query(Invoice, Project)
        .join(Project, Project.id == Invoice.project_id)
        .filter(Invoice.client_id == client_id, Invoice.is_deleted == False, Invoice.status == "Issued", Invoice.due_date != None,  # noqa: E711,E712
                Project.is_deleted == False)  # noqa: E712
        .order_by(Invoice.due_date)
        .all()
    )
    finance = _finance(db, client_id)
    sent = []
    for inv, p in rows:
        who = p.customer_name or p.project_name
        if inv.due_date >= today:
            if not soon_days or (inv.due_date - today).days > soon_days or not once(db, client_id, "invoice_reminders", f"soon:{inv.id}:{inv.due_date}"):
                continue
            title = f"{inv.invoice_no} ({_inr(inv.total)}) from {who} is due {'today' if inv.due_date == today else 'on ' + _day(inv.due_date)}"
        else:
            late = (today - inv.due_date).days
            if not once(db, client_id, "invoice_reminders", f"late:{inv.id}:{inv.due_date}:{(late - 1) // repeat}"):
                continue
            title = f"{inv.invoice_no} ({_inr(inv.total)}) from {who} is {_plural(late, 'day')} overdue"
        contact = ", ".join(x for x in (p.customer_contact_name, p.customer_mobile, p.customer_email) if x)
        body = (f"{p.project_code} {p.project_name}. Issued {_day(inv.issue_date) if inv.issue_date else '-'}, due {_day(inv.due_date)}."
                + (f" Contact: {contact}." if contact else "") + " Mark it Paid in Billing when the money arrives.")
        notification_repo.notify(db, sp, finance + _pm(p), "reminder", title, body=body, link="billing/", project_id=p.id)
        sent.append(inv.invoice_no)
    db.commit()
    return {"items": len(sent), "summary": ("Reminders for " + ", ".join(sent)) if sent else "No invoice newly due or overdue"}


# ============================================================================== work


def recurring_tasks(db: Session, client_id, params, today: date) -> dict:
    from app.repositories import tasks as task_repo

    sp = system_principal(client_id)
    cal = work_calendar.for_client(db, client_id)
    rules = db.query(RecurringTask).filter(RecurringTask.client_id == client_id, RecurringTask.is_deleted == False,  # noqa: E712
                                           RecurringTask.is_active == True, RecurringTask.next_run_on != None,  # noqa: E711,E712
                                           RecurringTask.next_run_on <= today).order_by(RecurringTask.id).all()
    created, skipped = [], []
    for rule_id in [r.id for r in rules]:
        rule = db.query(RecurringTask).filter(RecurringTask.id == rule_id).one()
        # Days missed while the server was off: only the latest one gets a task.
        day = rule.next_run_on
        while True:
            nxt = recurring_repo.next_occurrence(rule, cal, day + timedelta(days=1))
            if nxt is None or nxt > today:
                break
            day = nxt
        project = recurring_repo.project_of(db, rule)
        note, task = None, None
        if project.is_deleted or project.status == "Closed":
            note = f"Stopped: {project.project_code} is {'deleted' if project.is_deleted else 'Closed'}"
            rule.is_active = False
        elif project.status != "Active":
            note = f"Not created on {_day(day)}: {project.project_code} is {project.status} (tasks repeat on Active projects only)"
        else:
            data = {"project_id": project.id, "title": f"{rule.title} - {day.strftime('%d %b %Y')}", "description": rule.description,
                    "task_type": "Task", "priority": rule.priority, "status": "To Do", "assignee_id": rule.assignee_id,
                    "assignee_name": rule.assignee_name, "start_date": day, "due_date": day + timedelta(days=rule.due_in_days),
                    "estimated_hours": rule.estimated_hours, "labels": ["recurring"]}
            if project.end_date and data["due_date"] > project.end_date:
                data["due_date"] = max(day, project.end_date)
            try:
                task = task_repo.create_task(db, sp, data)
            except task_repo.TaskError as exc:
                db.rollback()
                rule = db.query(RecurringTask).filter(RecurringTask.id == rule_id).one()
                note = f"Not created on {_day(day)}: {exc}"
        if task is not None:
            rule.created_count = (rule.created_count or 0) + 1
            rule.last_task_id = task.id
            rule.last_created_on = day
            created.append(f"{task.task_key} {task.title}")
        else:
            skipped.append(f"{rule.title}: {note}")
            notification_repo.notify(db, sp, [(rule.created_by, rule.created_by_name)], "automation",
                                     f"Recurring task '{rule.title}' was not created", body=note, link="tasks/recurring/", project_id=rule.project_id)
        rule.last_note = note
        rule.next_run_on = recurring_repo.next_occurrence(rule, cal, day + timedelta(days=1)) if rule.is_active else None
        if rule.next_run_on is None:
            rule.is_active = False
        db.commit()
    summary = f"{_plural(len(created), 'task')} created" + (f": {', '.join(created[:10])}" if created else "")
    if skipped:
        summary += f"; {_plural(len(skipped), 'skipped')}: {'; '.join(skipped[:5])}"
    return {"items": len(created) + len(skipped), "summary": summary}


def sprint_auto_complete(db: Session, client_id, params, today: date) -> dict:
    from app.repositories import sprints as sprint_repo

    sp = system_principal(client_id)
    rows = (
        db.query(Sprint.id, Project.id)
        .join(Project, Project.id == Sprint.project_id)
        .filter(Sprint.client_id == client_id, Sprint.is_deleted == False, Sprint.status == "Active", Sprint.end_date < today,  # noqa: E712
                Project.is_deleted == False)  # noqa: E712
        .all()
    )
    done, problems = [], []
    for sprint_id, project_id in rows:
        sprint = db.query(Sprint).filter(Sprint.id == sprint_id).one()
        project = db.query(Project).filter(Project.id == project_id).one()
        target = None
        if project.status != "Closed":
            target = (db.query(Sprint).filter(Sprint.project_id == project.id, Sprint.is_deleted == False, Sprint.status == "Planned")  # noqa: E712
                      .order_by(Sprint.start_date, Sprint.id).first())
        try:
            result = sprint_repo.complete_sprint(db, sp, project, sprint, target.id if target else None)
        except sprint_repo.SprintError as exc:
            db.rollback()
            problems.append(f"{sprint.name}: {exc}")
            continue
        notification_repo.notify(
            db, sp, _pm(project), "automation",
            f"{sprint.name} ({project.project_code}) was completed on its end date: {result['done']} of {_plural(result['committed'], 'task')} done",
            body=(f"{_plural(result['moved'], 'unfinished task')} moved to {result['to']}." if result["moved"] else "Every task was finished.")
            + (" Start the next sprint when the team is ready." if target else ""),
            link="sprints/sprintList/", project_id=project.id,
        )
        db.commit()
        done.append(f"{sprint.name} ({project.project_code})")
    summary = (f"Completed {', '.join(done)}" if done else "No Active sprint past its end date") + (f"; failed: {'; '.join(problems)}" if problems else "")
    return {"items": len(done) + len(problems), "summary": summary}


RUNNERS = {
    "task_reminders": task_reminders,
    "approval_reminders": approval_reminders,
    "timesheet_reminders": timesheet_reminders,
    "timesheet_missing": timesheet_missing,
    "weekly_status_report": weekly_status_report,
    "budget_alerts": budget_alerts,
    "deadline_alerts": deadline_alerts,
    "monthly_invoices": monthly_invoices,
    "invoice_reminders": invoice_reminders,
    "recurring_tasks": recurring_tasks,
    "sprint_auto_complete": sprint_auto_complete,
}


# ============================================================================== event jobs


def after_task_status(db: Session, task: Task, old_status: str) -> None:
    """Called by the task workflow after a task's status changed, before it commits (one transaction)."""
    if task.status == old_status:
        return
    db.flush()
    changed = [task]
    if task.parent_task_id and engine.is_enabled(db, task.client_id, "parent_auto_done"):
        parent = _follow_subtasks(db, task, old_status)
        if parent is not None:
            changed.append(parent)
    if engine.is_enabled(db, task.client_id, "milestone_auto_review"):
        for t in changed:
            if t.status == "Done" and t.milestone_id:
                _milestone_ready(db, t.client_id, t.milestone_id, f"{t.task_key} was finished")


def _follow_subtasks(db: Session, task: Task, old_status: str):
    from app.repositories import milestones as milestone_repo

    parent = db.query(Task).filter(Task.id == task.parent_task_id, Task.is_deleted == False).one_or_none()  # noqa: E712
    if parent is None:
        return None
    sp = system_principal(task.client_id)
    if task.status == "Done":
        if parent.status == "Done":
            return None
        open_subtasks = db.query(Task.id).filter(Task.parent_task_id == parent.id, Task.is_deleted == False, Task.status != "Done").count()  # noqa: E712
        if open_subtasks or open_blockers(db, parent.id):
            return None
        new_status, why = "Done", "all its subtasks are done"
    elif old_status == "Done" and parent.status == "Done":
        new_status, why = "In Progress", f"its subtask {task.task_key} was reopened"
    else:
        return None
    old = parent.status
    parent.status = new_status
    log_activity(db, sp, parent.id, "status", f"{old} -> {new_status} ({why})")
    notification_repo.notify(db, sp, notification_repo.task_audience(db, parent), "status", f"{parent.task_key} moved to {new_status}: {parent.title}",
                             body=f"Automation moved it from {old} to {new_status}: {why}", link=notification_repo.task_link(parent.id),
                             project_id=parent.project_id, task_id=parent.id)
    milestone_repo.start_from_task(db, parent)
    engine.record_event(db, task.client_id, "parent_auto_done", f"{parent.task_key} {parent.title}: {old} -> {new_status} ({why})")
    db.flush()
    return parent


def _milestone_ready(db: Session, client_id, milestone_id, reason) -> None:
    from app.repositories import milestones as milestone_repo

    milestone = db.query(Milestone).filter(Milestone.id == milestone_id, Milestone.is_deleted == False).populate_existing().one_or_none()  # noqa: E712
    if milestone is None or milestone.status != "In Progress":
        return
    try:
        milestone_repo._check_complete(db, milestone, "review")
    except milestone_repo.MilestoneError:
        return
    project = db.query(Project).filter(Project.id == milestone.project_id).one()
    milestone.status = "Ready for Review"
    sp = system_principal(client_id)
    title = f"Milestone '{milestone.name}' of {project.project_code} {project.project_name} is ready for review"
    body = f"All its tasks and deliverables are done ({reason}). Accept it, or request changes with feedback."
    notification_repo.notify(db, sp, _pm(project), "approval", title, body=body, link=_project_link(project.id, "milestones"), project_id=project.id)
    if project.customer_name:
        clients = db.query(UserRole).filter(UserRole.client_id == client_id, UserRole.role == roles.CLIENT, UserRole.is_active == True,  # noqa: E712
                                            func.lower(UserRole.customer_name) == project.customer_name.lower()).all()
        notification_repo.notify(db, sp, [(c.user_id, c.user_name) for c in clients], "approval", title, body=body,
                                 link=f"portal/project/?id={project.id}", project_id=project.id)
    engine.record_event(db, client_id, "milestone_auto_review", f"{project.project_code} '{milestone.name}' -> Ready for Review ({reason})")


def after_deliverable_done(db: Session, milestone: Milestone, deliverable_name: str) -> None:
    """Called when a deliverable is ticked done, before the commit."""
    if engine.is_enabled(db, milestone.client_id, "milestone_auto_review"):
        db.flush()
        _milestone_ready(db, milestone.client_id, milestone.id, f"'{deliverable_name}' was delivered")


def after_milestone_accepted(db: Session, milestone: Milestone) -> None:
    """Called after a milestone was accepted and saved. Drafts its invoice; a failure here never undoes the acceptance."""
    from app.repositories import billing as billing_repo

    client_id = milestone.client_id
    try:
        if not engine.is_enabled(db, client_id, "milestone_invoice") or not milestone.amount:
            return
        project = db.query(Project).filter(Project.id == milestone.project_id).one()
        if project.project_type in billing_repo.NOT_BILLABLE_TYPES:
            return
        sp = system_principal(client_id)
        data = {"invoice_type": "Milestone", "milestone_id": milestone.id, "notes": None, **_invoice_terms(db, project.id)}
        try:
            invoice = billing_repo.create_invoice(db, sp, project, data)
        except billing_repo.BillingError as exc:
            db.rollback()
            if "already billed" in str(exc):
                return
            notification_repo.notify(db, sp, _pm(project), "automation", f"The invoice for milestone '{milestone.name}' could not be drafted",
                                     body=f"{exc}. Create it in Billing when ready.", link="billing/", project_id=project.id)
            engine.record_event(db, client_id, "milestone_invoice", f"{project.project_code} '{milestone.name}': not drafted - {exc}", items=0)
            db.commit()
            return
        notification_repo.notify(
            db, sp, _finance(db, client_id) + _pm(project), "automation",
            f"Draft invoice {invoice.invoice_no} ({_inr(invoice.total)}) created for milestone '{milestone.name}' of {project.project_code}",
            body=f"{project.customer_name or project.project_name} accepted the milestone. Review the draft in Billing and Issue it.",
            link="billing/", project_id=project.id,
        )
        engine.record_event(db, client_id, "milestone_invoice", f"{invoice.invoice_no} drafted for {project.project_code} '{milestone.name}' ({_inr(invoice.total)})")
        db.commit()
    except Exception:  # noqa: BLE001 - the milestone is already accepted; a billing hiccup is logged, never shown as a failed acceptance
        db.rollback()
        logger.exception("Automatic invoice for milestone %s failed", milestone.id)
