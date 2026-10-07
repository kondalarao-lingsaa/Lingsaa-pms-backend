r"""Links project managers and team members to their login users where the screens saved only a name.

Before 5 Oct 2026 the Add Project and Add Member forms stored a typed name without the login user id, so those
people could not see their projects, log hours or approve. This repairs such rows: a project manager is linked
when the name is exactly one login user's name; a team member when the email (or else the exact name) matches.
Client users are never linked. Safe to re-run.

Run from backend/pms_api:
    venv\Scripts\python scripts\link_logins.py          (shows what it would change)
    venv\Scripts\python scripts\link_logins.py --apply  (changes it)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session  # noqa: E402

from app.db.session import engine  # noqa: E402
from app.models.access import UserRole  # noqa: E402
from app.models.projects import Project  # noqa: E402
from app.models.team import ProjectMember  # noqa: E402

APPLY = "--apply" in sys.argv

with Session(engine) as db:
    users = db.query(UserRole).filter(UserRole.is_active == True, UserRole.role != "client").all()  # noqa: E712
    by_company = {}
    for u in users:
        by_company.setdefault(u.client_id, []).append(u)

    def find(client_id, name=None, email=None):
        people = by_company.get(client_id, [])
        if email:
            hit = [u for u in people if (u.email or "").lower() == email.strip().lower()]
            if len(hit) == 1:
                return hit[0]
        if name:
            hit = [u for u in people if u.user_name.strip().lower() == name.strip().lower()]
            if len(hit) == 1:
                return hit[0]
        return None

    changes = 0
    for p in db.query(Project).filter(Project.is_deleted == False, Project.project_manager_id == None, Project.project_manager_name != None):  # noqa: E711,E712
        u = find(p.client_id, name=p.project_manager_name)
        if u:
            changes += 1
            print(f"project {p.project_code} {p.project_name}: manager {p.project_manager_name} -> login {u.user_name} (id {u.user_id})")
            if APPLY:
                p.project_manager_id = u.user_id
    live = db.query(Project.id).filter(Project.is_deleted == False)  # noqa: E712 - deleted projects are left as they were
    for m in db.query(ProjectMember).filter(ProjectMember.is_deleted == False, ProjectMember.user_id == None, ProjectMember.project_id.in_(live)):  # noqa: E711,E712
        u = find(m.client_id, name=m.member_name, email=m.email)
        if u:
            changes += 1
            print(f"member #{m.id} on project {m.project_id}: {m.member_name} -> login {u.user_name} (id {u.user_id})")
            if APPLY:
                m.user_id, m.member_name, m.email = u.user_id, u.user_name, u.email or m.email
    if APPLY:
        db.commit()
    print(f"\n{changes} row(s) {'linked' if APPLY else 'would be linked; run with --apply to change them'}")
