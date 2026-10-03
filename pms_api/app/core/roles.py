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

# Roles that see every project of the company; the others see only their own (see access.project_scope).
SEE_ALL_PROJECTS = {ADMIN, DIRECTOR, FINANCE, RESOURCE_MANAGER}


def can(role_key: str, group: str, action: str) -> bool:
    return action in ROLE_MATRIX.get(role_key, {}).get(group, [])
