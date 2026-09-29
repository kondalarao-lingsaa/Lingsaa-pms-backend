"""PMS role design: default action matrix per role and module group.

Mirrors Lingsaa_Accounts/src/pms/config/pmsRoles.js. This is the recommended default a
Super Admin starts from; the real permissions come from Master (plan -> module -> action
flags) and are re-checked server-side in a later step. A missing group means NO ACCESS.
"""

ACTIONS = ["view", "add", "edit", "delete", "approve"]

ROLES = [
    {"key": "superAdmin", "title": "Super Admin", "responsibility": "System configuration"},
    {"key": "projectDirector", "title": "Project Director", "responsibility": "Approvals and high-level monitoring"},
    {"key": "projectManager", "title": "Project Manager", "responsibility": "Complete project management"},
    {"key": "teamLead", "title": "Project Lead / Team Lead", "responsibility": "Team and task management"},
    {"key": "employee", "title": "Employee", "responsibility": "Tasks, timesheets, daily updates"},
    {"key": "financeUser", "title": "Finance User", "responsibility": "Budget, expenses, invoices"},
    {"key": "hrUser", "title": "HR User", "responsibility": "Employee / resource information"},
    {"key": "client", "title": "Client", "responsibility": "View project, deliverables, approvals"},
    {"key": "vendor", "title": "Vendor", "responsibility": "Assigned work / deliverables"},
]

_ALL = ["view", "add", "edit", "delete", "approve"]
_VAE = ["view", "add", "edit"]
_V = ["view"]

ROLE_MATRIX = {
    "superAdmin": {
        g: _ALL
        for g in [
            "dashboard", "projects", "planning", "tasks", "sprints", "resources", "timesheets", "budget",
            "deliverables", "risks", "documents", "communication", "billing", "reports", "settings",
        ]
    },
    "projectDirector": {
        "dashboard": _V, "projects": ["view", "approve"], "planning": _V, "tasks": _V, "sprints": _V,
        "resources": _V, "timesheets": ["view", "approve"], "budget": ["view", "approve"],
        "deliverables": ["view", "approve"], "risks": ["view", "approve"], "documents": _V,
        "communication": _V, "billing": ["view", "approve"], "reports": _V,
    },
    "projectManager": {
        "dashboard": _V, "projects": _VAE + ["approve"], "planning": _VAE, "tasks": _VAE, "sprints": _VAE,
        "resources": _VAE, "timesheets": ["view", "approve"], "budget": _V, "deliverables": _VAE,
        "risks": _VAE, "documents": _VAE, "communication": _VAE, "billing": _V, "reports": _V, "settings": _V,
    },
    "teamLead": {
        "dashboard": _V, "projects": _V, "planning": _VAE, "tasks": _VAE, "sprints": _VAE, "resources": _V,
        "timesheets": ["view", "approve"], "deliverables": _V, "risks": _VAE,
        "documents": ["view", "add"], "communication": _VAE, "reports": _V,
    },
    "employee": {
        "dashboard": _V, "projects": _V, "tasks": ["view", "edit"], "timesheets": _VAE,
        "documents": ["view", "add"], "communication": ["view", "add"], "reports": _V,
    },
    "financeUser": {
        "dashboard": _V, "projects": _V, "timesheets": _V, "budget": _VAE,
        "billing": _VAE + ["approve"], "reports": _V,
    },
    "hrUser": {"dashboard": _V, "resources": _VAE, "timesheets": _V, "reports": _V},
    "client": {
        "projects": _V, "deliverables": ["view", "approve"], "documents": _V,
        "communication": ["view", "add"],
    },
    "vendor": {
        "tasks": ["view", "edit"], "deliverables": ["view", "add"], "documents": ["view", "add"],
        "communication": ["view", "add"],
    },
}


def can(role_key: str, group: str, action: str) -> bool:
    return action in ROLE_MATRIX.get(role_key, {}).get(group, [])
