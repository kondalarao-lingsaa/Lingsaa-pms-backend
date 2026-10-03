"""Risk register, issues and change requests of a project."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, or_, text

from app.models.billing import Invoice
from app.models.milestones import Milestone
from app.models.projects import Project
from app.models.risks import RISK_TRANSITIONS, ISSUE_TRANSITIONS, ChangeRequest, Issue, Risk, risk_level
from app.models.tasks import Task
from app.models.team import ProjectMember
from app.repositories import tasks as task_repo
from app.schemas.risks import change_out, issue_out, risk_out
from app.core.access import project_scope

SEVERITY_TO_PRIORITY = {"Low": "Low", "Medium": "Medium", "High": "High", "Critical": "Critical"}
LEVEL_TO_SEVERITY = {"Low": "Low", "Medium": "Medium", "High": "High"}


class RiskError(Exception):
    """A rule was broken; the message is safe to show to the user."""


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _next_key(db, project, kind) -> str:
    """PRJ-2026-0001-R3 / -I2 / -CR1. UPDLOCK/HOLDLOCK keeps keys unique when two people add at once."""
    row = db.execute(
        text("SELECT last_no FROM projectmanagement.record_counters WITH (UPDLOCK, HOLDLOCK) WHERE project_id = :p AND kind = :k"),
        {"p": project.id, "k": kind},
    ).first()
    if row is None:
        n = 1
        db.execute(text("INSERT INTO projectmanagement.record_counters (project_id, kind, last_no) VALUES (:p, :k, 1)"), {"p": project.id, "k": kind})
    else:
        n = row[0] + 1
        db.execute(text("UPDATE projectmanagement.record_counters SET last_no = :n WHERE project_id = :p AND kind = :k"), {"n": n, "p": project.id, "k": kind})
    return f"{project.project_code}-{kind}{n}"


def _open_project(project):
    if project.status == "Closed":
        raise RiskError(f"{project.project_code} is Closed, so its risks, issues and changes can no longer change")


def _owner(db, project, member_id):
    if not member_id:
        return None, None
    member = db.query(ProjectMember).filter(ProjectMember.id == member_id, ProjectMember.project_id == project.id, ProjectMember.is_deleted == False).one_or_none()  # noqa: E712
    if member is None:
        raise RiskError("The owner must be a member of this project's team")
    return member.id, member.member_name


def _milestone(db, project, milestone_id):
    if not milestone_id:
        return None
    m = db.query(Milestone).filter(Milestone.id == milestone_id, Milestone.project_id == project.id, Milestone.is_deleted == False).one_or_none()  # noqa: E712
    if m is None:
        raise RiskError("The milestone must belong to this project")
    return m


def _projects_of(db, rows):
    ids = {r.project_id for r in rows}
    return {p.id: p for p in db.query(Project).filter(Project.id.in_(ids))} if ids else {}


# ------------------------------------------------------------------------------------ risks


def _live_risks(db, principal):
    return db.query(Risk).join(Project, Project.id == Risk.project_id).filter(
        Risk.client_id == principal.client_id, Risk.is_deleted == False, Project.is_deleted == False, project_scope(db, principal)  # noqa: E712
    )


def get_risk(db, principal, project_id, risk_id):
    return _live_risks(db, principal).filter(Risk.project_id == project_id, Risk.id == risk_id).one_or_none()


def serialize_risks(db, risks) -> list:
    projects = _projects_of(db, risks)
    m_ids = {r.milestone_id for r in risks if r.milestone_id}
    names = dict(db.query(Milestone.id, Milestone.name).filter(Milestone.id.in_(m_ids)).all()) if m_ids else {}
    r_ids = [r.id for r in risks] or [-1]
    issues = dict(db.query(Issue.risk_id, func.count()).filter(Issue.risk_id.in_(r_ids), Issue.is_deleted == False).group_by(Issue.risk_id).all())  # noqa: E712
    return [risk_out(r, project=projects.get(r.project_id), milestone_name=names.get(r.milestone_id), issue_count=issues.get(r.id, 0)) for r in risks]


def list_risks(db, principal, *, project_id=None, status=None, level=None, search=None, open_only=False) -> list:
    query = _live_risks(db, principal)
    if project_id:
        query = query.filter(Risk.project_id == project_id)
    if status:
        query = query.filter(Risk.status == status)
    if open_only:
        query = query.filter(Risk.status.in_(("Open", "Monitoring")))
    if search:
        like = f"%{search}%"
        query = query.filter(or_(Risk.title.ilike(like), Risk.risk_key.ilike(like), Risk.owner_name.ilike(like), Project.project_name.ilike(like)))
    rows = serialize_risks(db, query.all())
    if level:
        rows = [r for r in rows if r["level"] == level]
    # Highest score first, then the ones whose review is due.
    return sorted(rows, key=lambda r: (r["status"] in ("Closed", "Mitigated", "Occurred"), -r["score"], not r["review_due"], r["risk_key"]))


def _check_review_date(data, current=None):
    review = data.get("review_date")
    if review and review != current and review < date.today():
        raise RiskError("The review date cannot be in the past")


def create_risk(db, principal, project, data) -> Risk:
    _open_project(project)
    _check_review_date(data)
    data["owner_member_id"], owner_name = _owner(db, project, data.get("owner_member_id"))
    _milestone(db, project, data.get("milestone_id"))
    risk = Risk(**data, owner_name=owner_name, client_id=principal.client_id, project_id=project.id, risk_key=_next_key(db, project, "R"),
                raised_by_name=principal.user_name, created_by=principal.user_id, updated_by=principal.user_id)
    db.add(risk)
    db.commit()
    db.refresh(risk)
    return risk


def update_risk(db, principal, project, risk, data) -> Risk:
    _open_project(project)
    if risk.status == "Closed":
        raise RiskError(f"{risk.risk_key} is Closed. Reopen it to make changes")
    _check_review_date(data, risk.review_date)
    data["owner_member_id"], owner_name = _owner(db, project, data.get("owner_member_id"))
    _milestone(db, project, data.get("milestone_id"))
    for key, value in data.items():
        setattr(risk, key, value)
    risk.owner_name = owner_name
    risk.updated_by = principal.user_id
    db.commit()
    db.refresh(risk)
    return risk


def change_risk_status(db, principal, project, risk, new_status) -> Risk:
    _open_project(project)
    if new_status == "Occurred":
        raise RiskError("Use 'It Happened' to record that a risk occurred - it raises an issue")
    if new_status not in RISK_TRANSITIONS.get(risk.status, []):
        raise RiskError(f"A risk that is {risk.status} cannot move to {new_status}")
    risk.status = new_status
    risk.closed_at = _utcnow() if new_status == "Closed" else None
    risk.updated_by = principal.user_id
    db.commit()
    db.refresh(risk)
    return risk


def risk_occurred(db, principal, project, risk) -> Issue:
    """The risk happened: it becomes an Issue (same owner, severity from the risk level)."""
    _open_project(project)
    if risk.status not in ("Open", "Monitoring", "Mitigated"):
        raise RiskError(f"{risk.risk_key} is {risk.status}")
    issue = Issue(
        client_id=principal.client_id, project_id=project.id, issue_key=_next_key(db, project, "I"), title=risk.title,
        description=f"Raised from risk {risk.risk_key}." + (f" Contingency plan: {risk.contingency}" if risk.contingency else ""),
        severity=LEVEL_TO_SEVERITY[risk_level(risk.probability * risk.impact)], owner_member_id=risk.owner_member_id, owner_name=risk.owner_name,
        due_date=date.today() + timedelta(days=7), risk_id=risk.id, raised_by_name=principal.user_name,
        created_by=principal.user_id, updated_by=principal.user_id,
    )
    db.add(issue)
    risk.status = "Occurred"
    risk.updated_by = principal.user_id
    db.commit()
    db.refresh(issue)
    return issue


def delete_risk(db, principal, project, risk) -> None:
    _open_project(project)
    if db.query(Issue).filter(Issue.risk_id == risk.id, Issue.is_deleted == False).first():  # noqa: E712
        raise RiskError(f"{risk.risk_key} has raised issues, so it is kept for the record. Close it instead")
    risk.is_deleted = True
    risk.updated_by = principal.user_id
    db.commit()


# ----------------------------------------------------------------------------------- issues


def _live_issues(db, principal):
    return db.query(Issue).join(Project, Project.id == Issue.project_id).filter(
        Issue.client_id == principal.client_id, Issue.is_deleted == False, Project.is_deleted == False, project_scope(db, principal)  # noqa: E712
    )


def get_issue(db, principal, project_id, issue_id):
    return _live_issues(db, principal).filter(Issue.project_id == project_id, Issue.id == issue_id).one_or_none()


def serialize_issues(db, issues) -> list:
    projects = _projects_of(db, issues)
    t_ids = {i.task_id for i in issues if i.task_id}
    tasks = {t.id: t for t in db.query(Task).filter(Task.id.in_(t_ids), Task.is_deleted == False)} if t_ids else {}  # noqa: E712
    r_ids = {i.risk_id for i in issues if i.risk_id}
    keys = dict(db.query(Risk.id, Risk.risk_key).filter(Risk.id.in_(r_ids)).all()) if r_ids else {}
    return [issue_out(i, project=projects.get(i.project_id), task=tasks.get(i.task_id), risk_key=keys.get(i.risk_id)) for i in issues]


SEVERITY_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


def list_issues(db, principal, *, project_id=None, status=None, severity=None, search=None, open_only=False) -> list:
    query = _live_issues(db, principal)
    if project_id:
        query = query.filter(Issue.project_id == project_id)
    if status:
        query = query.filter(Issue.status == status)
    if severity:
        query = query.filter(Issue.severity == severity)
    if open_only:
        query = query.filter(Issue.status.in_(("Open", "In Progress")))
    if search:
        like = f"%{search}%"
        query = query.filter(or_(Issue.title.ilike(like), Issue.issue_key.ilike(like), Issue.owner_name.ilike(like), Project.project_name.ilike(like)))
    rows = serialize_issues(db, query.all())
    return sorted(rows, key=lambda i: (i["status"] in ("Resolved", "Closed"), SEVERITY_RANK[i["severity"]], i["due_date"] or "9999", i["issue_key"]))


def create_issue(db, principal, project, data) -> Issue:
    _open_project(project)
    if data.get("due_date") and data["due_date"] < date.today():
        raise RiskError("The due date cannot be in the past")
    data["owner_member_id"], owner_name = _owner(db, project, data.get("owner_member_id"))
    if data.get("risk_id") and not get_risk(db, principal, project.id, data["risk_id"]):
        raise RiskError("The risk must belong to this project")
    issue = Issue(**data, owner_name=owner_name, client_id=principal.client_id, project_id=project.id, issue_key=_next_key(db, project, "I"),
                  raised_by_name=principal.user_name, created_by=principal.user_id, updated_by=principal.user_id)
    db.add(issue)
    db.commit()
    db.refresh(issue)
    return issue


def update_issue(db, principal, project, issue, data) -> Issue:
    _open_project(project)
    if issue.status == "Closed":
        raise RiskError(f"{issue.issue_key} is Closed")
    if data.get("due_date") and data["due_date"] != issue.due_date and data["due_date"] < date.today():
        raise RiskError("The due date cannot be in the past")
    data["owner_member_id"], owner_name = _owner(db, project, data.get("owner_member_id"))
    data.pop("risk_id", None)  # the source risk does not change after the issue is raised
    for key, value in data.items():
        setattr(issue, key, value)
    issue.owner_name = owner_name
    issue.updated_by = principal.user_id
    db.commit()
    db.refresh(issue)
    return issue


def change_issue_status(db, principal, project, issue, new_status, resolution=None) -> Issue:
    _open_project(project)
    if new_status not in ISSUE_TRANSITIONS.get(issue.status, []):
        raise RiskError(f"An issue that is {issue.status} cannot move to {new_status}")
    if new_status == "Resolved":
        if not resolution or len(resolution) < 10:
            raise RiskError("Please Enter the Resolution (at least 10 characters) - how was it fixed?")
        if issue.task_id:
            task = db.query(Task).filter(Task.id == issue.task_id, Task.is_deleted == False).one_or_none()  # noqa: E712
            if task is not None and task.status != "Done":
                raise RiskError(f"Its fix task {task.task_key} is {task.status}. Finish the task first")
        issue.resolution = resolution
        issue.resolved_at = _utcnow()
    if new_status in ("Open", "In Progress"):
        issue.resolved_at = None
    issue.status = new_status
    issue.updated_by = principal.user_id
    db.commit()
    db.refresh(issue)
    return issue


def create_fix_task(db, principal, project, issue) -> Task:
    """Puts the fix on the board: a task with the issue's owner and a priority from its severity."""
    _open_project(project)
    if issue.status in ("Resolved", "Closed"):
        raise RiskError(f"{issue.issue_key} is {issue.status}")
    if issue.task_id and db.query(Task).filter(Task.id == issue.task_id, Task.is_deleted == False).first():  # noqa: E712
        raise RiskError(f"{issue.issue_key} already has a fix task")
    owner = db.query(ProjectMember).filter(ProjectMember.id == issue.owner_member_id).one_or_none() if issue.owner_member_id else None
    try:
        task = task_repo.create_task(db, principal, {
            "project_id": project.id, "title": f"Fix: {issue.title}"[:300], "description": f"Fix for issue {issue.issue_key}. {issue.description or ''}".strip()[:4000],
            "task_type": "Bug", "priority": SEVERITY_TO_PRIORITY[issue.severity], "status": "To Do", "due_date": issue.due_date,
            "assignee_name": owner.member_name if owner else None, "assignee_id": owner.user_id if owner else None, "labels": ["issue"],
        })
    except task_repo.TaskError as exc:
        raise RiskError(str(exc)) from exc
    issue.task_id = task.id
    if issue.status == "Open":
        issue.status = "In Progress"
    issue.updated_by = principal.user_id
    db.commit()
    return task


def delete_issue(db, principal, project, issue) -> None:
    _open_project(project)
    issue.is_deleted = True
    issue.updated_by = principal.user_id
    db.commit()


# -------------------------------------------------------------------------- change requests


def _live_changes(db, principal):
    return db.query(ChangeRequest).join(Project, Project.id == ChangeRequest.project_id).filter(
        ChangeRequest.client_id == principal.client_id, ChangeRequest.is_deleted == False, Project.is_deleted == False, project_scope(db, principal)  # noqa: E712
    )


def get_change(db, principal, project_id, change_id):
    return _live_changes(db, principal).filter(ChangeRequest.project_id == project_id, ChangeRequest.id == change_id).one_or_none()


def serialize_changes(db, changes) -> list:
    projects = _projects_of(db, changes)
    m_ids = {c.milestone_id for c in changes if c.milestone_id}
    names = dict(db.query(Milestone.id, Milestone.name).filter(Milestone.id.in_(m_ids)).all()) if m_ids else {}
    return [change_out(c, project=projects.get(c.project_id), milestone_name=names.get(c.milestone_id)) for c in changes]


def list_changes(db, principal, *, project_id=None, status=None, search=None) -> list:
    query = _live_changes(db, principal)
    if project_id:
        query = query.filter(ChangeRequest.project_id == project_id)
    if status:
        query = query.filter(ChangeRequest.status == status)
    if search:
        like = f"%{search}%"
        query = query.filter(or_(ChangeRequest.title.ilike(like), ChangeRequest.cr_key.ilike(like), Project.project_name.ilike(like)))
    rows = serialize_changes(db, query.order_by(ChangeRequest.created_at.desc(), ChangeRequest.id.desc()).all())
    return sorted(rows, key=lambda c: c["status"] != "Submitted")


def _check_milestone_changeable(db, milestone):
    if milestone.status == "Accepted":
        raise RiskError(f"'{milestone.name}' is already Accepted, so its amount cannot change")
    if db.query(Invoice).filter(Invoice.milestone_id == milestone.id, Invoice.status != "Cancelled", Invoice.is_deleted == False).first():  # noqa: E712
        raise RiskError(f"'{milestone.name}' is already invoiced, so its amount cannot change")


def create_change(db, principal, project, data) -> ChangeRequest:
    _open_project(project)
    milestone = _milestone(db, project, data.get("milestone_id"))
    if milestone:
        _check_milestone_changeable(db, milestone)
    change = ChangeRequest(**data, client_id=principal.client_id, project_id=project.id, cr_key=_next_key(db, project, "CR"),
                           raised_by=principal.user_id, raised_by_name=principal.user_name)
    db.add(change)
    db.commit()
    db.refresh(change)
    return change


def update_change(db, principal, project, change, data) -> ChangeRequest:
    _open_project(project)
    if change.status != "Submitted":
        raise RiskError(f"{change.cr_key} is {change.status} and can no longer be edited")
    milestone = _milestone(db, project, data.get("milestone_id"))
    if milestone:
        _check_milestone_changeable(db, milestone)
    for key, value in data.items():
        setattr(change, key, value)
    db.commit()
    db.refresh(change)
    return change


def decide_change(db, principal, project, change, approve: bool, note=None) -> ChangeRequest:
    """Approve (and apply the impact to the project) or reject a change request."""
    _open_project(project)
    if change.status != "Submitted":
        raise RiskError(f"{change.cr_key} is already {change.status}")
    if not principal.user_id:
        raise RiskError("Your login has no user id, so it cannot approve or reject. Please sign in again")
    if change.raised_by == principal.user_id:
        raise RiskError("You raised this change, so someone else has to approve or reject it")
    if not approve and (not note or len(note) < 5):
        raise RiskError("Please Enter a Reason for rejecting (at least 5 characters)")
    from app.repositories import approvals  # local import: approvals reads these models

    try:
        approvals.check_change_authority(db, principal, project, change)
    except approvals.ApprovalError as exc:
        raise RiskError(str(exc)) from exc

    applied = []
    if approve:
        cost = Decimal(change.cost_impact or 0)
        if cost:
            if change.milestone_id:
                milestone = _milestone(db, project, change.milestone_id)
                _check_milestone_changeable(db, milestone)
                new_amount = Decimal(milestone.amount or 0) + cost
                if new_amount < 0:
                    raise RiskError(f"'{milestone.name}' would go below zero ({float(new_amount):,.2f})")
                milestone.amount = new_amount
                applied.append(f"Milestone '{milestone.name}' amount {'+' if cost > 0 else ''}{float(cost):,.2f}")
            else:
                new_budget = Decimal(project.budget or 0) + cost
                if new_budget < 0:
                    raise RiskError(f"The budget would go below zero ({float(new_budget):,.2f})")
                project.budget = new_budget
                applied.append(f"Budget {'+' if cost > 0 else ''}{float(cost):,.2f}")
        if change.days_impact:
            if not project.end_date:
                raise RiskError(f"{project.project_code} has no end date, so a schedule change cannot be applied. Set its end date first")
            new_end = project.end_date + timedelta(days=change.days_impact)
            if project.start_date and new_end < project.start_date:
                raise RiskError("The new end date would be before the project start")
            project.end_date = new_end
            applied.append(f"End date {'+' if change.days_impact > 0 else ''}{change.days_impact} days -> {new_end.strftime('%d %b %Y')}")
    change.status = "Approved" if approve else "Rejected"
    change.decision_note = note
    change.decided_by, change.decided_by_name, change.decided_at = principal.user_id, principal.user_name, _utcnow()
    change.applied_summary = "; ".join(applied) or ("No automatic changes (scope only)" if approve else None)
    approvals.log(db, principal, "change", change.id, change.status, project_id=project.id, remarks=note)
    db.commit()
    db.refresh(change)
    return change


def withdraw_change(db, principal, project, change) -> None:
    if change.status != "Submitted":
        raise RiskError(f"{change.cr_key} is {change.status} and stays on record")
    if change.raised_by and change.raised_by != principal.user_id and not principal.is_superadmin:
        raise RiskError(f"{change.cr_key} was raised by {change.raised_by_name or 'someone else'}; only they can withdraw it")
    change.is_deleted = True
    db.commit()


# -------------------------------------------------------------------------------- summaries


def risk_matrix(risks) -> list:
    """5x5 counts of open risks: matrix[impact-1][probability-1]."""
    matrix = [[0] * 5 for _ in range(5)]
    for r in risks:
        if r["status"] in ("Open", "Monitoring"):
            matrix[r["impact"] - 1][r["probability"] - 1] += 1
    return matrix
