r"""Daily approval reminders and escalation. Run once a day (Windows Task Scheduler, for example 9:00 AM).

- Anyone with requests waiting REMIND_DAYS or more for their decision gets one reminder (bell + email).
- Requests waiting ESCALATE_DAYS or more are escalated to the company's Admins, naming who they wait for.
It reads the same approvals inbox people see in the app, so the rules are the same.

Run from backend/pms_api:  venv\Scripts\python scripts\send_approval_reminders.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session  # noqa: E402

from app.core import roles  # noqa: E402
from app.core.access import resolve_role  # noqa: E402
from app.core.security import Principal  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.models.access import UserRole  # noqa: E402
from app.repositories import approvals, notifications  # noqa: E402

REMIND_DAYS = 2
ESCALATE_DAYS = 4
APPROVER_ROLES = (roles.ADMIN, roles.DIRECTOR, roles.PROJECT_MANAGER, roles.TEAM_LEAD, roles.FINANCE)


def run(db: Session) -> dict:
    sent = {"reminders": 0, "escalations": 0}
    approvers = db.query(UserRole).filter(UserRole.is_active == True, UserRole.role.in_(APPROVER_ROLES)).all()  # noqa: E712
    for row in approvers:
        person = Principal(client_id=row.client_id, user_id=row.user_id, user_name=row.user_name, role=None, is_superadmin=False, raw_claims={})
        resolve_role(db, person)
        waiting = [i for i in approvals.inbox(db, person)["items"] if (i.get("waiting_days") or 0) >= REMIND_DAYS]
        if not waiting:
            continue
        system = Principal(client_id=row.client_id, user_id=None, user_name="PMS Reminders", role=None, is_superadmin=False, raw_claims={})
        oldest = max(i["waiting_days"] for i in waiting)
        notifications.notify(
            db, system, [(row.user_id, row.user_name)], "reminder",
            f"{len(waiting)} request{'s' if len(waiting) > 1 else ''} waiting for your approval (oldest {oldest} days)",
            body="; ".join(f"{i['project_code']} {i['title']}" for i in waiting[:5]), link="approvals/",
        )
        sent["reminders"] += 1
        late = [i for i in waiting if i["waiting_days"] >= ESCALATE_DAYS]
        if late and row.role != roles.ADMIN:
            admins = db.query(UserRole).filter(UserRole.client_id == row.client_id, UserRole.role == roles.ADMIN, UserRole.is_active == True).all()  # noqa: E712
            notifications.notify(
                db, system, [(a.user_id, a.user_name) for a in admins], "reminder",
                f"Escalated: {len(late)} request{'s' if len(late) > 1 else ''} waiting {ESCALATE_DAYS}+ days for {row.user_name}",
                body="; ".join(f"{i['project_code']} {i['title']} ({i['waiting_days']} days)" for i in late[:5]), link="approvals/",
            )
            sent["escalations"] += 1
    db.commit()
    return sent


if __name__ == "__main__":
    with Session(engine) as session:
        print(run(session))
