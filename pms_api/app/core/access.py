"""Who may call what, and which projects they see. Applied to every API request (see main.py).

1. `authorize` (a dependency on every router except health) works out the caller's PMS role and checks the
   route against ROUTE_POLICY. A route missing from the policy is refused for everyone but Admin, so a new
   endpoint can never be open by accident (tests/api_roles.py fails until it is listed).
2. `project_scope` is the row rule: the SQL condition on Project that every list and lookup adds, so a person
   only ever sees the projects their role allows.
"""
import logging

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import exists, false, func, or_, select, true
from sqlalchemy.orm import Session, aliased

from app.core import roles
from app.core.security import Principal, get_current_principal
from app.db.session import get_db
from app.models.access import RolePermission, UserRole
from app.models.projects import Project
from app.models.team import ProjectMember

logger = logging.getLogger("pms.access")

ANY = "any"  # every signed-in user, Client included
INTERNAL = "internal"  # every signed-in user except a Client

# (method, route path without /api) -> (group, action) | ANY | INTERNAL
ROUTE_POLICY = {
    # who am I / role list
    ("GET", "/me"): ANY,
    ("POST", "/auth/change-password"): ANY,
    ("GET", "/meta/roles"): ANY,
    # projects
    ("GET", "/projects/meta"): ("projects", "view"),
    ("GET", "/projects/list"): ("projects", "view"),
    ("GET", "/projects/options"): INTERNAL,
    ("GET", "/projects/{project_id}"): ("projects", "view"),
    ("POST", "/projects/create"): ("projects", "add"),
    ("PUT", "/projects/{project_id}"): ("projects", "edit"),
    # Submit is "edit"; Approve / Send back are checked again inside (approval rules).
    ("POST", "/projects/{project_id}/status"): ("projects", "edit"),
    ("DELETE", "/projects/{project_id}"): ("projects", "delete"),
    ("GET", "/projects/{project_id}/approvals"): ("projects", "view"),
    # templates and project settings
    ("GET", "/templates"): ("projects", "view"),
    ("GET", "/templates/{template_id}"): ("projects", "view"),
    ("POST", "/templates"): ("projects", "add"),
    ("POST", "/templates/starter"): ("settings", "edit"),
    ("PUT", "/templates/{template_id}"): ("projects", "edit"),
    ("DELETE", "/templates/{template_id}"): ("projects", "delete"),
    ("POST", "/projects/{project_id}/save-as-template"): ("projects", "add"),
    ("POST", "/templates/{template_id}/create-project"): ("projects", "add"),
    ("GET", "/projects/{project_id}/settings"): ("projects", "view"),
    ("PUT", "/projects/{project_id}/settings"): ("projects", "edit"),
    # tasks
    ("GET", "/tasks/meta"): ("tasks", "view"),
    ("GET", "/tasks/list"): ("tasks", "view"),
    ("GET", "/tasks/board"): ("tasks", "view"),
    ("GET", "/tasks/{task_id}"): ("tasks", "view"),
    ("POST", "/tasks/create"): ("tasks", "add"),
    ("PUT", "/tasks/{task_id}"): ("tasks", "edit"),
    ("POST", "/tasks/{task_id}/status"): ("tasks", "edit"),
    ("DELETE", "/tasks/{task_id}"): ("tasks", "delete"),
    ("POST", "/tasks/{task_id}/move"): ("tasks", "edit"),
    ("GET", "/tasks/{task_id}/comments"): ("communication", "view"),
    ("POST", "/tasks/{task_id}/comments"): ("communication", "add"),
    ("DELETE", "/tasks/{task_id}/comments/{comment_id}"): ("communication", "delete"),
    ("GET", "/tasks/{task_id}/dependencies"): ("tasks", "view"),
    ("POST", "/tasks/{task_id}/dependencies"): ("planning", "edit"),
    ("DELETE", "/tasks/{task_id}/dependencies/{dependency_id}"): ("planning", "edit"),
    ("GET", "/tasks/{task_id}/watchers"): ("tasks", "view"),
    ("POST", "/tasks/{task_id}/watch"): ("tasks", "view"),
    ("GET", "/tasks/{task_id}/activity"): ("tasks", "view"),
    ("GET", "/calendar"): ("tasks", "view"),
    # planning
    ("GET", "/projects/{project_id}/timeline"): ("planning", "view"),
    ("POST", "/tasks/{task_id}/schedule"): ("planning", "edit"),
    ("GET", "/planning/roadmap"): ("planning", "view"),
    ("GET", "/planning/dependencies"): ("planning", "view"),
    # sprints
    ("GET", "/projects/{project_id}/sprints"): ("sprints", "view"),
    ("POST", "/projects/{project_id}/sprints"): ("sprints", "add"),
    ("PUT", "/sprints/{sprint_id}"): ("sprints", "edit"),
    ("DELETE", "/sprints/{sprint_id}"): ("sprints", "delete"),
    ("POST", "/sprints/{sprint_id}/tasks"): ("sprints", "edit"),
    ("DELETE", "/sprints/{sprint_id}/tasks/{task_id}"): ("sprints", "edit"),
    ("POST", "/sprints/{sprint_id}/start"): ("sprints", "edit"),
    ("POST", "/sprints/{sprint_id}/complete"): ("sprints", "edit"),
    ("GET", "/sprints/{sprint_id}/burndown"): ("sprints", "view"),
    ("GET", "/projects/{project_id}/backlog"): ("sprints", "view"),
    # team and resources (rates are hidden from roles that cannot see the budget)
    ("GET", "/team/meta"): INTERNAL,
    ("GET", "/projects/{project_id}/members"): INTERNAL,
    ("POST", "/projects/{project_id}/members"): ("resources", "add"),
    ("PUT", "/projects/{project_id}/members/{member_id}"): ("resources", "edit"),
    ("DELETE", "/projects/{project_id}/members/{member_id}"): ("resources", "delete"),
    ("GET", "/resources/allocation"): ("resources", "view"),
    ("GET", "/resources/capacity"): ("resources", "view"),
    ("GET", "/resources/utilization"): ("resources", "view"),
    # timesheets
    ("GET", "/timesheets/meta"): ("timesheets", "view"),
    ("GET", "/timesheets/my-week"): ("timesheets", "view"),
    ("POST", "/timesheets/entries"): ("timesheets", "add"),
    ("POST", "/timesheets/submit"): ("timesheets", "add"),
    ("GET", "/timesheets/list"): ("timesheets", "view"),
    ("GET", "/timesheets/approvals"): ("timesheets", "approve"),
    ("POST", "/timesheets/approve"): ("timesheets", "approve"),
    ("POST", "/timesheets/reject"): ("timesheets", "approve"),
    # budget and expenses
    ("GET", "/projects/{project_id}/budget"): ("budget", "view"),
    ("GET", "/budget/overview"): ("budget", "view"),
    ("GET", "/budget/actual-cost"): ("budget", "view"),
    ("GET", "/budget/variance"): ("budget", "view"),
    ("GET", "/expenses/meta"): ("expenses", "view"),
    ("GET", "/expenses"): ("expenses", "view"),
    ("POST", "/expenses"): ("expenses", "add"),
    ("PUT", "/expenses/{expense_id}"): ("expenses", "edit"),
    ("DELETE", "/expenses/{expense_id}"): ("expenses", "delete"),
    ("POST", "/expenses/{expense_id}/submit"): ("expenses", "add"),
    ("POST", "/expenses/approve"): ("expenses", "approve"),
    ("POST", "/expenses/reject"): ("expenses", "approve"),
    ("POST", "/expenses/{expense_id}/receipt"): ("expenses", "edit"),
    ("DELETE", "/expenses/{expense_id}/receipt"): ("expenses", "edit"),
    # milestones and deliverables (Accept / Reject are checked again inside)
    ("GET", "/milestones/meta"): ("deliverables", "view"),
    ("GET", "/milestones/list"): ("deliverables", "view"),
    ("GET", "/projects/{project_id}/milestones"): ("deliverables", "view"),
    ("POST", "/projects/{project_id}/milestones"): ("deliverables", "add"),
    ("PUT", "/projects/{project_id}/milestones/{milestone_id}"): ("deliverables", "edit"),
    ("DELETE", "/projects/{project_id}/milestones/{milestone_id}"): ("deliverables", "delete"),
    ("POST", "/projects/{project_id}/milestones/{milestone_id}/status"): ("deliverables", "edit"),
    ("POST", "/projects/{project_id}/milestones/{milestone_id}/deliverables"): ("deliverables", "add"),
    ("PUT", "/projects/{project_id}/milestones/{milestone_id}/deliverables/{deliverable_id}"): ("deliverables", "edit"),
    ("POST", "/projects/{project_id}/milestones/{milestone_id}/deliverables/{deliverable_id}/done"): ("deliverables", "edit"),
    ("DELETE", "/projects/{project_id}/milestones/{milestone_id}/deliverables/{deliverable_id}"): ("deliverables", "delete"),
    # risks, issues, change requests
    ("GET", "/risks/meta"): ("risks", "view"),
    ("GET", "/risks/list"): ("risks", "view"),
    ("GET", "/projects/{project_id}/risks"): ("risks", "view"),
    ("POST", "/projects/{project_id}/risks"): ("risks", "add"),
    ("PUT", "/projects/{project_id}/risks/{risk_id}"): ("risks", "edit"),
    ("POST", "/projects/{project_id}/risks/{risk_id}/status"): ("risks", "edit"),
    ("POST", "/projects/{project_id}/risks/{risk_id}/occurred"): ("risks", "edit"),
    ("DELETE", "/projects/{project_id}/risks/{risk_id}"): ("risks", "delete"),
    ("GET", "/issues/list"): ("risks", "view"),
    ("GET", "/projects/{project_id}/issues"): ("risks", "view"),
    ("POST", "/projects/{project_id}/issues"): ("risks", "add"),
    ("PUT", "/projects/{project_id}/issues/{issue_id}"): ("risks", "edit"),
    ("POST", "/projects/{project_id}/issues/{issue_id}/status"): ("risks", "edit"),
    ("POST", "/projects/{project_id}/issues/{issue_id}/task"): ("tasks", "add"),
    ("DELETE", "/projects/{project_id}/issues/{issue_id}"): ("risks", "delete"),
    ("GET", "/change-requests/list"): ("risks", "view"),
    ("GET", "/projects/{project_id}/change-requests"): ("risks", "view"),
    ("POST", "/projects/{project_id}/change-requests"): ("risks", "add"),
    ("PUT", "/projects/{project_id}/change-requests/{change_id}"): ("risks", "add"),
    ("POST", "/projects/{project_id}/change-requests/{change_id}/approve"): ("risks", "approve"),
    ("POST", "/projects/{project_id}/change-requests/{change_id}/reject"): ("risks", "approve"),
    ("DELETE", "/projects/{project_id}/change-requests/{change_id}"): ("risks", "add"),
    # documents
    ("GET", "/documents/meta"): ("documents", "view"),
    ("GET", "/documents/list"): ("documents", "view"),
    ("POST", "/projects/{project_id}/documents"): ("documents", "add"),
    ("GET", "/documents/{document_id}/versions"): ("documents", "view"),
    ("GET", "/documents/{document_id}/download"): ("documents", "view"),
    ("PUT", "/documents/{document_id}"): ("documents", "edit"),
    ("DELETE", "/documents/{document_id}"): ("documents", "delete"),
    # billing (Issue / Mark Paid / Cancel = approve)
    ("GET", "/billing/meta"): ("billing", "view"),
    ("GET", "/billing/billable"): ("billing", "view"),
    ("GET", "/billing/invoices"): ("billing", "view"),
    ("GET", "/billing/invoices/{invoice_id}"): ("billing", "view"),
    ("POST", "/billing/invoices"): ("billing", "add"),
    ("POST", "/billing/invoices/{invoice_id}/status"): ("billing", "approve"),
    # communication, notifications, search
    ("GET", "/notifications"): ANY,
    ("POST", "/notifications/read"): ANY,
    ("GET", "/communication/comments"): ("communication", "view"),
    ("GET", "/communication/mentions"): ("communication", "view"),
    ("GET", "/communication/activity"): ("communication", "view"),
    ("GET", "/communication/meta"): ("communication", "view"),
    ("GET", "/search"): INTERNAL,
    # dashboard and reports
    ("GET", "/dashboard/summary"): ("dashboard", "view"),
    ("GET", "/dashboard/overview"): ("dashboard", "view"),
    ("GET", "/reports/catalog"): ("reports", "view"),
    ("GET", "/reports/{report}"): ("reports", "view"),
    # company settings (the working calendar is read by many screens)
    ("GET", "/settings"): INTERNAL,
    ("PUT", "/settings/calendar"): ("settings", "edit"),
    ("PUT", "/settings/industry"): ("settings", "edit"),
    ("PUT", "/settings/approvals"): ("settings", "edit"),
    ("POST", "/settings/holidays"): ("settings", "edit"),
    ("DELETE", "/settings/holidays/{holiday_id}"): ("settings", "edit"),
    ("GET", "/settings/users"): ("settings", "view"),
    ("GET", "/settings/permissions"): ("settings", "view"),
    ("PUT", "/settings/permissions"): ("settings", "edit"),
    ("POST", "/settings/users"): ("settings", "edit"),
    ("PUT", "/settings/users/{role_id}"): ("settings", "edit"),
    ("DELETE", "/settings/users/{role_id}"): ("settings", "edit"),
    # approvals inbox (each item is checked again when acted on)
    ("GET", "/approvals"): INTERNAL,
    ("GET", "/approvals/history"): INTERNAL,
    # client portal
    ("GET", "/portal/projects"): ("portal", "view"),
    ("GET", "/portal/projects/{project_id}"): ("portal", "view"),
    ("POST", "/portal/projects/{project_id}/milestones/{milestone_id}/decision"): ("portal", "approve"),
    ("POST", "/portal/projects/{project_id}/messages"): ("portal", "add"),
    ("GET", "/portal/documents/{document_id}/download"): ("portal", "view"),
    ("GET", "/portal/invoices/{invoice_id}"): ("portal", "view"),
    ("GET", "/projects/{project_id}/client-messages"): ("communication", "view"),
    ("POST", "/projects/{project_id}/client-messages"): ("communication", "add"),
    # development-only test logins (the route itself is off in production)
    ("POST", "/dev/login-as"): ("settings", "edit"),
}


def resolve_role(db: Session, principal: Principal) -> None:
    """Sets principal.role_key / role_title / customer_name from Settings > Users & Roles.

    - A user with a row gets that role (an inactive row means no access at all).
    - The first person to use the PMS in a company with no rows becomes its Admin, so a new company is never
      locked out; they then add everyone else.
    - Anyone else without a row is a Member until the Admin gives them a role.
    """
    principal.customer_name = None
    row = None
    if principal.user_id is not None:
        row = db.query(UserRole).filter(UserRole.client_id == principal.client_id, UserRole.user_id == principal.user_id).one_or_none()
    if row is None and principal.user_id is not None:
        has_any = db.query(UserRole.id).filter(UserRole.client_id == principal.client_id).first() is not None
        if not has_any:
            row = UserRole(client_id=principal.client_id, user_id=principal.user_id, user_name=principal.user_name or f"User {principal.user_id}",
                           role=roles.ADMIN, created_by=principal.user_id, updated_by=principal.user_id)
            db.add(row)
            db.commit()
            logger.info("First PMS user %s of company %s made Admin", principal.user_id, principal.client_id)
    if row is not None and not row.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your PMS access is switched off. Ask your PMS Admin.")
    principal.role_key = row.role if row is not None and row.role in roles.ROLE_KEYS else roles.MEMBER
    principal.role_title = roles.ROLE_TITLES[principal.role_key]
    # The company's own matrix (Settings > Roles & Permissions) for this role.
    principal.permissions = company_matrix(db, principal.client_id)[principal.role_key]
    principal.customer_name = row.customer_name if row is not None else None
    principal.role_row_id = row.id if row is not None else None


def company_matrix(db: Session, client_id: int) -> dict:
    rows = db.query(RolePermission).filter(RolePermission.client_id == client_id).all()
    return roles.effective_matrix({(r.role, r.module_group): [a for a in r.actions.split(",") if a] for r in rows})


def allowed(principal: Principal, group: str, action: str = "view") -> bool:
    """The caller's right on a module, from the company's matrix (default matrix for internal callers)."""
    perms = getattr(principal, "permissions", None)
    if perms is None:
        return roles.can(getattr(principal, "role_key", None), group, action)
    return action in perms.get(group, [])


def check(principal: Principal, group: str, action: str, what: str = None) -> None:
    """Refuses with a clear message when the caller's role lacks the action."""
    if not allowed(principal, group, action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Your role ({principal.role_title}) cannot {what or f'{action} {group}'}",
        )


def authorize(request: Request, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)) -> Principal:
    resolve_role(db, principal)
    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    path = path[4:] if path.startswith("/api/") else path
    rule = ROUTE_POLICY.get((request.method, path))
    if rule is None:
        if principal.role_key != roles.ADMIN:
            logger.warning("No access rule for %s %s; refused for %s", request.method, path, principal.role_key)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This action is not available to your role")
    elif rule == INTERNAL:
        if principal.role_key == roles.CLIENT:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This page is not part of the client portal")
    elif rule != ANY:
        check(principal, rule[0], rule[1], what=_ACTION_WORDS.get(rule))
    return principal


_ACTION_WORDS = {
    ("projects", "add"): "create projects",
    ("projects", "edit"): "change projects",
    ("projects", "delete"): "delete projects",
    ("tasks", "add"): "create tasks",
    ("tasks", "delete"): "delete tasks",
    ("resources", "add"): "add people to a team",
    ("resources", "edit"): "change team members",
    ("resources", "delete"): "remove people from a team",
    ("timesheets", "approve"): "approve timesheets",
    ("expenses", "approve"): "approve expenses",
    ("risks", "approve"): "approve change requests",
    ("billing", "add"): "create invoices",
    ("billing", "approve"): "issue invoices or record payments",
    ("budget", "view"): "see budgets and costs",
    ("settings", "edit"): "change company settings",
    ("settings", "view"): "see company settings",
    ("deliverables", "add"): "create milestones",
    ("deliverables", "delete"): "delete milestones",
    ("planning", "edit"): "change the plan",
}


def project_scope(db: Session, principal: Principal):
    """SQL condition on Project: the projects this person may see."""
    role = getattr(principal, "role_key", None)
    if role is None:
        # Scripts and internal callers without a request: no role worked out, company-wide as before.
        return true()
    if role in roles.SEE_ALL_PROJECTS:
        return true()
    if role == roles.CLIENT:
        if not principal.customer_name:
            return false()
        return (func.lower(Project.customer_name) == principal.customer_name.lower()) & Project.status.notin_(("Draft", "Pending Approval"))
    uid = principal.user_id
    if uid is None:
        return false()
    # Own alias, so the check also works inside queries that already join the team table.
    team = aliased(ProjectMember)
    on_team = exists(
        select(team.id).where(team.project_id == Project.id, team.user_id == uid, team.is_deleted == False)  # noqa: E712
    ).correlate(Project)
    return or_(Project.project_manager_id == uid, Project.created_by == uid, on_team)


def visible_project_ids(db: Session, principal: Principal):
    """Subquery of visible project ids, for queries that do not join Project."""
    return select(Project.id).where(Project.client_id == principal.client_id, Project.is_deleted == False, project_scope(db, principal))  # noqa: E712


def can_see_rates(principal: Principal) -> bool:
    role = getattr(principal, "role_key", None)
    return role is None or allowed(principal, "budget", "view")
