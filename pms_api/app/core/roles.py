"""PMS login roles and what each may do, per module group and action.

Eight roles, the set used by market PMS tools (Zoho Projects, Monday, Odoo, MS Project): six inside the company,
one for resource planning and one outside (Client). A company gives each login user one role in
Settings > Users & Roles. The server checks every request against this matrix (app/core/access.py); the
screens use the same matrix (GET /api/me) only to hide what a person cannot use.

Which projects a role sees is a separate rule (access.project_scope): Admin, Director, Finance and Resource
Manager see every project; Project Manager, Team Lead and Member see the projects they manage or are on the
team of; a Client sees only their own company's projects, and only through the client portal.
"""

ACTIONS = ["view", "add", "edit", "delete", "approve"]

ADMIN = "admin"
DIRECTOR = "director"
PROJECT_MANAGER = "project_manager"
TEAM_LEAD = "team_lead"
MEMBER = "member"
FINANCE = "finance"
RESOURCE_MANAGER = "resource_manager"
CLIENT = "client"

ROLES = [
    {"key": ADMIN, "title": "Admin", "responsibility": "Owns the PMS: settings, users and roles, every project; final approval level"},
    {"key": DIRECTOR, "title": "Director", "responsibility": "Approves projects, budget changes and large expenses; watches every project"},
    {"key": PROJECT_MANAGER, "title": "Project Manager", "responsibility": "Plans and runs their projects: team, tasks, hours, risks, delivery"},
    {"key": TEAM_LEAD, "title": "Team Lead", "responsibility": "Runs the team's daily work: tasks, sprints, approves the team's hours"},
    {"key": MEMBER, "title": "Member", "responsibility": "Works on tasks, logs hours and expenses"},
    {"key": FINANCE, "title": "Finance", "responsibility": "Budgets, expense approval above the limit, invoices and payments"},
    {"key": RESOURCE_MANAGER, "title": "Resource Manager", "responsibility": "Who works where: team allocation, capacity and utilization"},
    {"key": CLIENT, "title": "Client", "responsibility": "Sees their own projects in the client portal; accepts milestones"},
]
ROLE_KEYS = [r["key"] for r in ROLES]
ROLE_TITLES = {r["key"]: r["title"] for r in ROLES}

GROUPS = [
    "dashboard", "projects", "planning", "tasks", "sprints", "resources", "timesheets", "budget", "expenses",
    "deliverables", "risks", "documents", "communication", "billing", "reports", "settings", "approvals", "portal",
]

_ALL = ["view", "add", "edit", "delete", "approve"]
_V = ["view"]
_VAED = ["view", "add", "edit", "delete"]

ROLE_MATRIX = {
    ADMIN: {g: _ALL for g in GROUPS},
    DIRECTOR: {
        "dashboard": _V, "projects": ["view", "add", "edit", "approve"], "planning": _V, "tasks": _V, "sprints": _V,
        "resources": _V, "timesheets": ["view", "approve"], "budget": ["view", "approve"], "expenses": ["view", "approve"],
        "deliverables": ["view", "approve"], "risks": ["view", "add", "edit", "approve"], "documents": ["view", "add"],
        "communication": ["view", "add"], "billing": ["view", "approve"], "reports": _V, "approvals": _V,
    },
    PROJECT_MANAGER: {
        "dashboard": _V, "projects": _VAED, "planning": _VAED, "tasks": _VAED, "sprints": _VAED,
        "resources": _VAED, "timesheets": ["view", "add", "edit", "approve"], "budget": _V, "expenses": _ALL,
        "deliverables": _ALL, "risks": _ALL, "documents": _VAED, "communication": _VAED, "billing": ["view", "add"],
        "reports": _V, "approvals": _V,
    },
    TEAM_LEAD: {
        "dashboard": _V, "projects": _V, "planning": ["view", "add", "edit"], "tasks": _VAED, "sprints": ["view", "add", "edit"],
        "resources": _V, "timesheets": ["view", "add", "edit", "approve"], "expenses": _ALL, "deliverables": ["view", "edit"],
        "risks": ["view", "add", "edit"], "documents": ["view", "add", "edit"], "communication": _VAED, "reports": _V,
        "approvals": _V,
    },
    MEMBER: {
        "dashboard": _V, "projects": _V, "planning": _V, "tasks": ["view", "edit"], "sprints": _V,
        "timesheets": ["view", "add", "edit"], "expenses": _VAED, "deliverables": _V, "risks": ["view", "add"],
        "documents": ["view", "add"], "communication": _VAED,
    },
    FINANCE: {
        "dashboard": _V, "projects": _V, "timesheets": _V, "budget": ["view", "edit", "approve"], "expenses": ["view", "approve"],
        "deliverables": _V, "documents": _V, "communication": ["view", "add"], "billing": _ALL, "reports": _V, "approvals": _V,
    },
    RESOURCE_MANAGER: {
        "dashboard": _V, "projects": _V, "planning": _V, "tasks": _V, "resources": _ALL, "timesheets": _V,
        "communication": ["view", "add"], "reports": _V,
    },
    CLIENT: {"portal": ["view", "add", "approve"]},
}

# What each module covers, for Settings > Roles & Permissions.
GROUP_INFO = {
    "dashboard": ("Dashboard", "Company-wide health, workload and money at a glance"),
    "approvals": ("My Approvals", "The inbox of requests waiting for this person"),
    "projects": ("Projects", "Create and change projects, templates; approve = project approval (by Approval Rules)"),
    "planning": ("Planning", "Gantt, roadmap and task links"),
    "tasks": ("Tasks", "Tasks, board, backlog and calendar"),
    "sprints": ("Sprints", "Sprint planning and boards"),
    "resources": ("Team & Resources", "Who is on a team, allocation %, capacity and utilization"),
    "timesheets": ("Timesheets", "Log hours (add/edit); approve = approve the team's hours"),
    "budget": ("Budget & Costs", "Budgets, costs and pay rates (rates are hidden without this)"),
    "expenses": ("Expenses", "Spend outside salaries; approve = approve expenses (by Approval Rules)"),
    "deliverables": ("Milestones", "Milestones and deliverables; approve = accept for the client"),
    "risks": ("Risks & Changes", "Risks, issues and change requests; approve = approve changes (by Approval Rules)"),
    "documents": ("Documents", "Project files and versions"),
    "communication": ("Communication", "Comments, mentions, activity and client messages"),
    "billing": ("Billing", "Invoices; approve = issue invoices and record payments"),
    "reports": ("Reports", "All reports and CSV downloads"),
    "settings": ("Settings", "Company settings, users, roles and approval rules"),
    "portal": ("Client Portal", "The client's own view of their projects"),
}

INTERNAL_GROUPS = [g for g in GROUPS if g != "portal"]


def locked(role: str, group: str, action: str) -> str | None:
    """Rules that keep the PMS safe whatever a company changes; None when the cell may be changed.

    - Admin always has everything, so nobody can lock the company out.
    - Settings (users, roles, approval rules) is Admin-only: nobody can give themselves more rights.
    - A Client only ever has the client portal; inside the company nobody needs portal rights but the Admin.
    - Project approval levels belong to Director and Admin (Settings > Approval Rules)."""
    if role == ADMIN:
        return "Admin always has full access"
    if group == "settings":
        return "Only the Admin manages settings, users and permissions"
    if role == CLIENT and group != "portal":
        return "A client only uses the client portal"
    if group == "portal" and role != CLIENT:
        return "The client portal is for client logins"
    if group == "projects" and action == "approve" and role != DIRECTOR:
        return "Project approval levels are Director and Admin (Approval Rules)"
    if group == "projects" and action == "approve":
        return "Directors approve projects (Approval Rules)"
    if group == "approvals" and action != "view":
        return "My Approvals is a list; decisions are made on each item"
    return None


def effective_matrix(overrides: dict) -> dict:
    """The company's matrix: the recommended defaults, with its own changes on the cells that may change.
    overrides: {(role, group): [actions]}."""
    matrix = {}
    for role in ROLE_KEYS:
        rights = {}
        for group in GROUPS:
            default = list(ROLE_MATRIX.get(role, {}).get(group, []))
            chosen = overrides.get((role, group))
            if chosen is None:
                actions = default
            else:
                # Locked cells always keep the default; the rest follow the company's choice.
                actions = [a for a in ACTIONS if (a in default if locked(role, group, a) else a in chosen)]
            if actions and "view" not in actions:
                actions = ["view"] + actions  # any right on a module includes seeing it
            if actions:
                rights[group] = actions
        matrix[role] = rights
    return matrix


# Roles that see every project of the company; the others see only their own (see access.project_scope).
SEE_ALL_PROJECTS = {ADMIN, DIRECTOR, FINANCE, RESOURCE_MANAGER}


def can(role_key: str, group: str, action: str) -> bool:
    return action in ROLE_MATRIX.get(role_key, {}).get(group, [])
