"""Approval rules: who may approve what, by role and by amount (an authority matrix), plus the approvals inbox.

Projects (by budget, Settings > Approval Rules):
    Internal project, or budget up to the PM limit   -> approved when submitted (recorded as Auto-approved)
    up to the high limit                             -> 1 level: Director or Admin
    above the high limit                             -> 2 levels: Director or Admin, then an Admin
  The person who submits never approves their own project, and one person never signs both levels. A submitter
  who holds the authority for level 1 (a Director) covers that level by submitting.
Change requests (by the cost increase): up to the PM limit the project's manager may approve; up to the high
  limit a Director or Admin; above it an Admin.
Expenses: up to the expense limit the project's manager or team lead; above it Finance, a Director or Admin.
Timesheets: the project's manager or team lead, a Director or Admin.
Milestones: the client accepts them in the portal; the project's manager, a Director or Admin may accept for them.
Nobody approves their own request (checked where each item is decided).
"""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core import roles
from app.core.access import allowed, project_scope, visible_project_ids
from app.models.access import ApprovalLog
from app.models.expenses import Expense
from app.models.milestones import Milestone
from app.models.projects import Project
from app.models.risks import ChangeRequest
from app.models.settings import CompanySettings
from app.models.team import ProjectMember
from app.models.timesheets import TimeEntry
from app.models.tasks import Task
from app.repositories import notifications as notification_repo
from app.schemas.rules import utc_iso

DEFAULT_LIMITS = {"pm": Decimal("100000"), "high": Decimal("1000000"), "expense": Decimal("10000")}
LEVEL_ROLES = {1: {roles.DIRECTOR, roles.ADMIN}, 2: {roles.ADMIN}}
LEVEL_NAMES = {1: "Director or Admin", 2: "Admin"}
MANAGER_TEAM_ROLES = ("Project Manager", "Team Lead")


class ApprovalError(Exception):
    """An approval rule was broken; the message is safe to show to the user."""


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _inr(value) -> str:
    """Rupees in the Indian grouping: ₹5,00,000 / ₹10,00,000."""
    n = int(round(float(value or 0)))
    sign, digits = ("-" if n < 0 else ""), str(abs(n))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        head = ",".join([head[max(i - 2, 0):i] for i in range(len(head), 0, -2)][::-1])
        digits = f"{head},{tail}"
    return f"{sign}₹{digits}"


def limits(db: Session, client_id) -> dict:
    row = db.query(CompanySettings).filter(CompanySettings.client_id == client_id).one_or_none()
    get = lambda col, key: Decimal(getattr(row, col)) if row is not None and getattr(row, col) is not None else DEFAULT_LIMITS[key]  # noqa: E731
    return {"pm": get("pm_approval_limit", "pm"), "high": get("high_approval_limit", "high"), "expense": get("expense_approval_limit", "expense")}


def limits_out(db, client_id) -> dict:
    lim = limits(db, client_id)
    return {"pm_approval_limit": float(lim["pm"]), "high_approval_limit": float(lim["high"]), "expense_approval_limit": float(lim["expense"])}


def save_limits(db: Session, principal, pm, high, expense) -> None:
    if pm <= 0 or high <= 0 or expense <= 0:
        raise ApprovalError("Every limit must be more than zero")
    if high <= pm:
        raise ApprovalError("The high limit must be more than the PM limit")
    row = db.query(CompanySettings).filter(CompanySettings.client_id == principal.client_id).one_or_none()
    if row is None:
        row = CompanySettings(client_id=principal.client_id)
        db.add(row)
    row.pm_approval_limit, row.high_approval_limit, row.expense_approval_limit = pm, high, expense
    row.updated_by = principal.user_id
    row.updated_by_name = notification_repo.person_name(principal.user_name) or principal.user_name
    db.commit()


def log(db, principal, entity_type, entity_id, decision, project_id=None, level=1, remarks=None, auto=False):
    db.add(ApprovalLog(
        client_id=principal.client_id, project_id=project_id, entity_type=entity_type, entity_id=entity_id, level=level,
        decision=decision, decided_by=None if auto else principal.user_id,
        decided_by_name="Approval rules" if auto else (notification_repo.person_name(principal.user_name) or principal.user_name),
        decided_role=None if auto else getattr(principal, "role_title", None), remarks=(remarks or None) and remarks[:1000],
    ))


def history(db: Session, principal, entity_type, entity_id) -> list:
    rows = (
        db.query(ApprovalLog)
        .filter(ApprovalLog.client_id == principal.client_id, ApprovalLog.entity_type == entity_type, ApprovalLog.entity_id == entity_id,
                # Only items on projects this person can see (every log row carries its project).
                ApprovalLog.project_id.in_(visible_project_ids(db, principal)))
        .order_by(ApprovalLog.decided_at, ApprovalLog.id)
        .all()
    )
    return [{"id": r.id, "level": r.level, "decision": r.decision, "decided_by_name": r.decided_by_name, "decided_role": r.decided_role,
             "remarks": r.remarks, "decided_at": utc_iso(r.decided_at)} for r in rows]


# ------------------------------------------------------------------------------ who manages a project


def manages(db: Session, principal, project_id) -> bool:
    """The caller is this project's manager, or on its team as Project Manager / Team Lead."""
    uid = principal.user_id
    if not uid:
        return False
    if db.query(Project.id).filter(Project.id == project_id, Project.project_manager_id == uid).first():
        return True
    return db.query(ProjectMember.id).filter(
        ProjectMember.project_id == project_id, ProjectMember.user_id == uid, ProjectMember.is_deleted == False,  # noqa: E712
        ProjectMember.role.in_(MANAGER_TEAM_ROLES),
    ).first() is not None


def _is_senior(principal) -> bool:
    return principal.role_key in (roles.ADMIN, roles.DIRECTOR)


def require_manager(db, principal, project_id, what):
    """Directors and Admins act on any project; others only on projects they manage."""
    if getattr(principal, "role_key", None) is None or _is_senior(principal):
        return
    if not manages(db, principal, project_id):
        raise ApprovalError(f"Only this project's manager or team lead, a Director or an Admin can {what}")


# ------------------------------------------------------------------------------ projects


def project_levels(project: Project, lim: dict) -> int:
    """How many approval levels a project needs: 0 (approved on submit), 1 or 2."""
    budget = Decimal(project.budget or 0)
    if (project.project_type or "") == "Internal" or budget <= lim["pm"]:
        return 0
    return 1 if budget <= lim["high"] else 2


def rule_text(project: Project, lim: dict) -> str:
    levels = project_levels(project, lim)
    if levels == 0:
        why = "an Internal project" if (project.project_type or "") == "Internal" else f"within the PM limit of {_inr(lim['pm'])}"
        return f"No approval needed: {why}"
    if levels == 1:
        return f"Budget {_inr(project.budget)} is above {_inr(lim['pm'])}: a Director or Admin approves"
    return f"Budget {_inr(project.budget)} is above {_inr(lim['high'])}: a Director or Admin, then an Admin approve"


def _approvers(db, principal, level) -> list:
    from app.models.access import UserRole

    rows = db.query(UserRole).filter(UserRole.client_id == principal.client_id, UserRole.is_active == True, UserRole.role.in_(LEVEL_ROLES[level])).all()  # noqa: E712
    return [(r.user_id, r.user_name) for r in rows]


def _level_signers(db, project_id) -> set:
    # Only this round counts: after Send back and a new submission, earlier approvers may sign again.
    last_submit = db.query(func.max(ApprovalLog.id)).filter(
        ApprovalLog.entity_type == "project", ApprovalLog.entity_id == project_id, ApprovalLog.decision == "Submitted"
    ).scalar() or 0
    rows = db.query(ApprovalLog.decided_by).filter(
        ApprovalLog.entity_type == "project", ApprovalLog.entity_id == project_id, ApprovalLog.decision == "Approved", ApprovalLog.decided_by != None,  # noqa: E711
        ApprovalLog.id > last_submit,
    ).all()
    return {r[0] for r in rows}


def submit_project(db: Session, principal, project: Project) -> str:
    """Draft -> Pending Approval, or straight to Approved when the rules or the submitter's own authority allow."""
    lim = limits(db, principal.client_id)
    levels = project_levels(project, lim)
    now = _utcnow()
    project.submitted_by, project.submitted_at = principal.user_id, now
    project.submitted_by_name = notification_repo.person_name(principal.user_name) or principal.user_name
    project.approval_levels = levels
    log(db, principal, "project", project.id, "Submitted", project_id=project.id, level=0, remarks=rule_text(project, lim))
    if levels == 0:
        _approve_final(project, "Approval rules", None, now, rule_text(project, lim))
        log(db, principal, "project", project.id, "Auto-approved", project_id=project.id, level=0, remarks=rule_text(project, lim), auto=True)
        return f"{project.project_code} is approved: {rule_text(project, lim)[len('No approval needed: '):]}"
    level = 1
    # A Director or Admin who submits covers level 1 with their own authority (never both levels).
    if getattr(principal, "role_key", None) in LEVEL_ROLES[1] and principal.user_id:
        log(db, principal, "project", project.id, "Approved", project_id=project.id, level=1, remarks="Own authority on submit")
        if levels == 1:
            _approve_final(project, project.submitted_by_name, principal.user_id, now, "Approved on submit (own authority)")
            return f"{project.project_code} is approved with your authority"
        level = 2
    project.status = "Pending Approval"
    project.approval_level = level
    project.approval_note = None
    notification_repo.notify(
        db, principal, _approvers(db, principal, level), "approval",
        f"{project.project_code} {project.project_name} needs your approval (level {level} of {levels})",
        body=rule_text(project, lim), link=f"projects/projectDetails/?id={project.id}", project_id=project.id,
    )
    return f"{project.project_code} sent for approval: waiting for {LEVEL_NAMES[level]} (level {level} of {levels})"


def _approve_final(project, by_name, by_id, when, note):
    project.status = "Approved"
    project.approval_level = None
    project.approved_by, project.approved_by_name, project.approved_at = by_id, by_name, when
    project.approval_note = note
    freeze_baseline(project, when)


def freeze_baseline(project, when):
    """The approved plan becomes the baseline; later changes (change requests, re-planning) are measured against it."""
    from sqlalchemy.orm import object_session

    project.baseline_budget, project.baseline_start_date, project.baseline_end_date = project.budget, project.start_date, project.end_date
    project.baseline_at = when
    db = object_session(project)
    if db is not None:
        for m in db.query(Milestone).filter(Milestone.project_id == project.id, Milestone.is_deleted == False):  # noqa: E712
            m.baseline_due_date = m.due_date


def can_approve_project(db, principal, project: Project) -> str | None:
    """None when the caller may approve the project's current level, else the reason they cannot."""
    if project.status != "Pending Approval":
        return f"{project.project_code} is not waiting for approval"
    level = project.approval_level or 1
    if getattr(principal, "role_key", None) not in LEVEL_ROLES.get(level, set()):
        return f"Level {level} needs a {LEVEL_NAMES.get(level, 'Admin')}; your role is {principal.role_title}"
    if not principal.user_id:
        return "Your login has no user id. Please sign in again"
    if project.submitted_by and project.submitted_by == principal.user_id:
        return "You sent this project for approval, so someone else has to approve it"
    if principal.user_id in _level_signers(db, project.id):
        return "You already approved an earlier level; the next level needs another person"
    return None


def approve_project(db: Session, principal, project: Project, remarks=None) -> str:
    reason = can_approve_project(db, principal, project)
    if reason:
        raise ApprovalError(reason)
    level, levels = project.approval_level or 1, project.approval_levels or 1
    log(db, principal, "project", project.id, "Approved", project_id=project.id, level=level, remarks=remarks)
    name = notification_repo.person_name(principal.user_name) or principal.user_name
    if level < levels:
        project.approval_level = level + 1
        notification_repo.notify(
            db, principal, _approvers(db, principal, level + 1), "approval",
            f"{project.project_code} {project.project_name} needs your approval (level {level + 1} of {levels})",
            body=f"Level {level} approved by {name}", link=f"projects/projectDetails/?id={project.id}", project_id=project.id,
        )
        result = f"Level {level} approved. {project.project_code} now waits for an {LEVEL_NAMES[level + 1]} (level {level + 1} of {levels})"
    else:
        _approve_final(project, name, principal.user_id, _utcnow(), remarks)
        result = f"{project.project_code} is approved"
    notification_repo.notify(
        db, principal, [(project.submitted_by, project.submitted_by_name), (project.project_manager_id, project.project_manager_name)], "approval",
        f"{name} approved {project.project_code}" + ("" if project.status == "Approved" else f" (level {level} of {levels})"),
        body=remarks, link=f"projects/projectDetails/?id={project.id}", project_id=project.id,
    )
    return result


def send_back_project(db: Session, principal, project: Project, remarks=None) -> str:
    """Pending Approval -> Draft. The submitter (or the project's manager) may withdraw; an approver must give a reason."""
    own = principal.user_id and principal.user_id in (project.submitted_by, project.project_manager_id, project.created_by)
    if not own:
        reason = can_approve_project(db, principal, project)
        if reason:
            raise ApprovalError(reason.replace("approve it", "send it back"))
        if not remarks or len(remarks.strip()) < 5:
            raise ApprovalError("Please Enter a Reason (at least 5 characters) so the project manager knows what to fix")
    log(db, principal, "project", project.id, "Withdrawn" if own else "Rejected", project_id=project.id, level=project.approval_level or 1, remarks=remarks)
    project.status = "Draft"
    project.approval_level = None
    project.approval_note = None if own else remarks
    if not own:
        name = notification_repo.person_name(principal.user_name) or principal.user_name
        notification_repo.notify(
            db, principal, [(project.submitted_by, project.submitted_by_name), (project.project_manager_id, project.project_manager_name)], "approval",
            f"{name} sent {project.project_code} back to Draft", body=f"Reason: {remarks}", link=f"projects/projectDetails/?id={project.id}",
            project_id=project.id,
        )
    return f"{project.project_code} is back in Draft" + ("" if own else ". The project manager has been told why")


# ------------------------------------------------------------------------------ other items


def _change_size(project, change) -> Decimal:
    # The size of the change decides the level, whether it raises or cuts the budget. A budget change is also
    # judged by how far the budget would then be from the approved baseline, so five small changes cannot add
    # up to a raise that would have needed a Director.
    cost = abs(Decimal(change.cost_impact or 0))
    if change.cost_impact and not change.milestone_id and project.baseline_budget is not None:
        drift = abs(Decimal(project.budget or 0) + Decimal(change.cost_impact) - Decimal(project.baseline_budget))
        cost = max(cost, drift)
    return cost


def change_approvers(db, principal, project, change) -> list:
    """Who is asked to decide a new change request: the project's manager, or the Directors/Admins above the limits."""
    cost, lim = _change_size(project, change), limits(db, principal.client_id)
    if cost > lim["high"]:
        return _approvers(db, principal, 2)
    if cost > lim["pm"]:
        return _approvers(db, principal, 1)
    return [(project.project_manager_id, project.project_manager_name)]


def check_change_authority(db, principal, project, change) -> None:
    cost = _change_size(project, change)
    lim = limits(db, principal.client_id)
    if cost > lim["high"]:
        if principal.role_key != roles.ADMIN:
            raise ApprovalError(f"A change above {_inr(lim['high'])} needs an Admin")
    elif cost > lim["pm"]:
        if not _is_senior(principal):
            raise ApprovalError(f"A change above {_inr(lim['pm'])} needs a Director or Admin")
    else:
        require_manager(db, principal, project.id, "approve this change")


def check_expense_authority(db, principal, expenses) -> None:
    lim = limits(db, principal.client_id)
    for e in expenses:
        if Decimal(e.amount or 0) > lim["expense"]:
            if principal.role_key not in (roles.ADMIN, roles.DIRECTOR, roles.FINANCE):
                raise ApprovalError(f"{e.expense_key} is above {_inr(lim['expense'])}, so Finance, a Director or an Admin approves it")
        elif principal.role_key not in (roles.FINANCE,):
            require_manager(db, principal, e.project_id, f"approve {e.expense_key}")


def check_timesheet_authority(db, principal, entries) -> None:
    for pid in {e.project_id for e in entries}:
        require_manager(db, principal, pid, "approve this project's hours")


def managed_project_ids(db, principal):
    """Projects whose approvals this person handles; None = all they can see (Director/Admin)."""
    if _is_senior(principal) or principal.role_key == roles.FINANCE:
        return None
    uid = principal.user_id or -1
    team = db.query(ProjectMember.project_id).filter(
        ProjectMember.user_id == uid, ProjectMember.is_deleted == False, ProjectMember.role.in_(MANAGER_TEAM_ROLES)  # noqa: E712
    )
    return db.query(Project.id).filter(Project.client_id == principal.client_id, or_(Project.project_manager_id == uid, Project.id.in_(team)))


# ------------------------------------------------------------------------------ inbox


def inbox(db: Session, principal) -> dict:
    """Everything waiting for this person's decision, newest first, with the counts per kind."""
    uid = principal.user_id or -1
    items = []
    scope = project_scope(db, principal)
    managed = managed_project_ids(db, principal)

    def projects_q(model):
        q = db.query(model, Project).join(Project, Project.id == model.project_id).filter(
            model.client_id == principal.client_id, Project.is_deleted == False, scope  # noqa: E712
        )
        return q if managed is None else q.filter(Project.id.in_(managed))

    if allowed(principal, "projects", "approve"):
        pending = db.query(Project).filter(Project.client_id == principal.client_id, Project.is_deleted == False, scope,  # noqa: E712
                                           Project.status == "Pending Approval").all()
        lim = limits(db, principal.client_id)
        for p in pending:
            if can_approve_project(db, principal, p) is None:
                items.append({"kind": "project", "id": p.id, "project_id": p.id, "project_code": p.project_code, "title": p.project_name,
                              "detail": f"Level {p.approval_level or 1} of {p.approval_levels or 1}. {rule_text(p, lim)}", "amount": float(p.budget or 0),
                              "requested_by": p.submitted_by_name, "requested_at": utc_iso(p.submitted_at), "link": f"projects/projectDetails/?id={p.id}"})

    if allowed(principal, "risks", "approve"):
        for c, p in projects_q(ChangeRequest).filter(ChangeRequest.is_deleted == False, ChangeRequest.status == "Submitted",  # noqa: E712
                                                       ChangeRequest.raised_by != uid):
            try:
                check_change_authority(db, principal, p, c)
            except ApprovalError:
                continue
            items.append({"kind": "change", "id": c.id, "project_id": p.id, "project_code": p.project_code, "title": f"{c.cr_key} {c.title}",
                          "detail": f"Cost {'+' if (c.cost_impact or 0) > 0 else ''}{_inr(c.cost_impact)}, {c.days_impact or 0:+d} days",
                          "amount": float(c.cost_impact or 0), "requested_by": c.raised_by_name, "requested_at": utc_iso(c.created_at),
                          "link": f"projects/projectDetails/?id={p.id}&tab=risks"})

    if allowed(principal, "expenses", "approve"):
        rows = db.query(Expense, Project).join(Project, Project.id == Expense.project_id).filter(
            Expense.client_id == principal.client_id, Project.is_deleted == False, scope, Expense.is_deleted == False,  # noqa: E712
            Expense.status == "Submitted", Expense.spent_by != uid)
        for e, p in rows:
            try:
                check_expense_authority(db, principal, [e])
            except ApprovalError:
                continue
            items.append({"kind": "expense", "id": e.id, "project_id": p.id, "project_code": p.project_code, "title": f"{e.expense_key} {e.category}",
                          "detail": e.description, "amount": float(e.amount or 0), "requested_by": e.spent_by_name,
                          "requested_at": utc_iso(e.created_at), "link": "budget/expenses/"})

    if allowed(principal, "timesheets", "approve"):
        live_task = db.query(Task.id).filter(Task.is_deleted == False)  # noqa: E712
        q = projects_q(TimeEntry).filter(TimeEntry.is_deleted == False, TimeEntry.status == "Submitted", TimeEntry.user_id != uid,  # noqa: E712
                                          TimeEntry.task_id.in_(live_task))
        weeks = {}
        for t, p in q:
            key = (t.user_id or t.member_name, p.id)
            w = weeks.setdefault(key, {"kind": "timesheet", "id": t.id, "project_id": p.id, "project_code": p.project_code,
                                       "title": f"{t.member_name}: hours on {p.project_name}", "hours": 0.0, "requested_by": t.member_name,
                                       "requested_at": utc_iso(t.submitted_at), "link": "timesheets/approval/"})
            w["hours"] += float(t.hours)
        for w in weeks.values():
            w["detail"] = f"{w['hours']:g} h submitted"
            w["amount"] = None
            items.append(w)

    if allowed(principal, "deliverables", "approve"):
        for m, p in projects_q(Milestone).filter(Milestone.is_deleted == False, Milestone.status == "Ready for Review"):  # noqa: E712
            items.append({"kind": "milestone", "id": m.id, "project_id": p.id, "project_code": p.project_code, "title": m.name,
                          "detail": "Ready for review: the client accepts it in the portal, or you accept it for them",
                          "amount": float(m.amount or 0), "requested_by": None, "requested_at": utc_iso(m.updated_at),
                          "link": f"projects/projectDetails/?id={p.id}&tab=milestones"})

    counts = {}
    now = _utcnow()
    for i in items:
        counts[i["kind"]] = counts.get(i["kind"], 0) + 1
        # How long it has waited, so old requests stand out (and reminders / escalation can use it).
        at = i.get("requested_at")
        i["waiting_days"] = (now - datetime.fromisoformat(at.replace("Z", "")).replace(tzinfo=None)).days if at else None
    items.sort(key=lambda i: i.get("requested_at") or "", reverse=True)
    return {"items": items, "counts": counts, "total": len(items)}
