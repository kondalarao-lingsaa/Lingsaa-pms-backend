"""Global search (Ctrl+K): one query across projects, tasks, milestones, documents, risks, issues, expenses, invoices
and people. Each hit carries the screen path that opens it (relative to the PMS root, like notification links)."""
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.billing import Invoice
from app.models.documents import Document
from app.models.expenses import Expense
from app.models.milestones import Milestone
from app.models.projects import Project
from app.models.risks import Issue, Risk
from app.models.tasks import Task
from app.models.team import ProjectMember
from app.core.access import project_scope

PER_GROUP = 5


def _live_projects(db, principal):
    return db.query(Project.id).filter(Project.client_id == principal.client_id, Project.is_deleted == False, project_scope(db, principal))  # noqa: E712


def search(db: Session, principal, q: str) -> list:
    like = f"%{q}%"
    pids = _live_projects(db, principal)
    codes = dict(db.query(Project.id, Project.project_code).filter(Project.id.in_(pids)).all())
    groups = []

    def add(kind, rows):
        if rows:
            groups.append({"kind": kind, "items": rows})

    add("Projects", [
        {"title": f"{p.project_code} · {p.project_name}", "subtitle": f"{p.status} · {p.customer_name or 'Internal'} · PM {p.project_manager_name or '-'}",
         "link": f"projects/projectDetails/?id={p.id}"}
        for p in db.query(Project).filter(Project.id.in_(pids), or_(Project.project_name.ilike(like), Project.project_code.ilike(like), Project.customer_name.ilike(like)))
        .order_by(Project.project_code.desc()).limit(PER_GROUP)
    ])
    add("Tasks", [
        {"title": f"{t.task_key} · {t.title}", "subtitle": f"{t.status} · {t.priority} · {t.assignee_name or 'Unassigned'}", "link": f"tasks/taskDetails/?id={t.id}"}
        for t in db.query(Task).filter(Task.project_id.in_(pids), Task.is_deleted == False, or_(Task.title.ilike(like), Task.task_key.ilike(like)))  # noqa: E712
        .order_by(Task.id.desc()).limit(PER_GROUP)
    ])
    add("Milestones", [
        {"title": m.name, "subtitle": f"{codes.get(m.project_id)} · {m.status}" + (f" · due {m.due_date.strftime('%d %b %Y')}" if m.due_date else ""),
         "link": f"projects/projectDetails/?id={m.project_id}&tab=milestones"}
        for m in db.query(Milestone).filter(Milestone.project_id.in_(pids), Milestone.is_deleted == False, Milestone.name.ilike(like)).order_by(Milestone.id.desc()).limit(PER_GROUP)  # noqa: E712
    ])
    add("Documents", [
        {"title": doc.title, "subtitle": f"{codes.get(doc.project_id)} · {doc.category} · {doc.file_name}", "link": f"projects/projectDetails/?id={doc.project_id}&tab=files"}
        for doc in db.query(Document).filter(Document.project_id.in_(pids), Document.is_deleted == False, Document.is_latest == True,  # noqa: E712
                                             or_(Document.title.ilike(like), Document.file_name.ilike(like))).order_by(Document.id.desc()).limit(PER_GROUP)
    ])
    add("Risks & Issues", [
        {"title": f"{r.risk_key} · {r.title}", "subtitle": f"Risk · {r.status} · score {r.probability * r.impact}", "link": f"projects/projectDetails/?id={r.project_id}&tab=risks"}
        for r in db.query(Risk).filter(Risk.project_id.in_(pids), Risk.is_deleted == False, or_(Risk.title.ilike(like), Risk.risk_key.ilike(like))).limit(3)  # noqa: E712
    ] + [
        {"title": f"{i.issue_key} · {i.title}", "subtitle": f"Issue · {i.status} · {i.severity}", "link": f"projects/projectDetails/?id={i.project_id}&tab=risks"}
        for i in db.query(Issue).filter(Issue.project_id.in_(pids), Issue.is_deleted == False, or_(Issue.title.ilike(like), Issue.issue_key.ilike(like))).limit(3)  # noqa: E712
    ])
    add("Expenses", [
        {"title": f"{e.expense_key} · {e.description}", "subtitle": f"{e.category} · ₹{float(e.amount):,.0f} · {e.status}", "link": f"budget/expenses/?projectId={e.project_id}"}
        for e in db.query(Expense).filter(Expense.project_id.in_(pids), Expense.is_deleted == False,  # noqa: E712
                                          or_(Expense.description.ilike(like), Expense.expense_key.ilike(like), Expense.vendor.ilike(like))).order_by(Expense.id.desc()).limit(PER_GROUP)
    ])
    add("Invoices", [
        {"title": inv.invoice_no, "subtitle": f"{codes.get(inv.project_id)} · {inv.customer_name or '-'} · ₹{float(inv.total):,.0f} · {inv.status}", "link": "billing/"}
        for inv in db.query(Invoice).filter(Invoice.project_id.in_(pids), Invoice.is_deleted == False, or_(Invoice.invoice_no.ilike(like), Invoice.customer_name.ilike(like)))  # noqa: E712
        .order_by(Invoice.id.desc()).limit(PER_GROUP)
    ])
    people = {}
    for m in db.query(ProjectMember).filter(ProjectMember.project_id.in_(pids), ProjectMember.is_deleted == False, ProjectMember.member_name.ilike(like)).limit(30):  # noqa: E712
        person = people.setdefault(m.member_name.lower(), {"title": m.member_name, "roles": set(), "projects": set()})
        person["roles"].add(m.role)
        person["projects"].add(codes.get(m.project_id))
    add("People", [
        {"title": p["title"], "subtitle": f"{', '.join(sorted(p['roles']))} · {len(p['projects'])} project{'' if len(p['projects']) == 1 else 's'}",
         "link": f"resources/allocation/?search={p['title']}"}
        for p in list(people.values())[:PER_GROUP]
    ])
    return groups
