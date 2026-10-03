r"""Gives the demo company (900001) one login user per PMS role, for testing and demos. Safe to re-run.

Run from backend/pms_api:  venv\Scripts\python scripts\seed_demo_roles.py
In the app (development only), Admin > avatar menu > "Sign in as" switches between these users.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session  # noqa: E402

from app.db.session import engine  # noqa: E402
from app.core.passwords import hash_password  # noqa: E402
from app.models.access import UserRole  # noqa: E402

DEMO_PASSWORD = "Demo@123"  # every demo user signs in with it (change it in Settings > Users & Roles)

DEMO_COMPANY = 900001
# user_id, name, email, role, client company (Client role only)
DEMO_USERS = [
    (1, "Dev User", "dev.user@lingsaa.com", "admin", None),
    (2, "QA Manager", "qa.manager@lingsaa.com", "admin", None),  # second Admin: the tests use it as "another person"
    (3, "Priya Sharma", "priya.sharma@lingsaa.com", "project_manager", None),
    (4, "Arjun Mehta", "arjun.mehta@lingsaa.com", "team_lead", None),
    (5, "Anita Rao", "anita.rao@lingsaa.com", "member", None),
    (6, "Kiran Iyer", "kiran.iyer@lingsaa.com", "finance", None),
    (7, "Meena Das", "meena.das@lingsaa.com", "resource_manager", None),
    (8, "Ravi Kumar", "ravi.kumar@acmeretail.in", "client", "Acme Retail"),
    (9, "Rohan Verma", "rohan.verma@lingsaa.com", "director", None),
]

with Session(engine) as db:
    for user_id, name, email, role, customer in DEMO_USERS:
        row = db.query(UserRole).filter_by(client_id=DEMO_COMPANY, user_id=user_id).one_or_none()
        if row is None:
            row = UserRole(client_id=DEMO_COMPANY, user_id=user_id, user_name=name, email=email, role=role, customer_name=customer)
            db.add(row)
            print(f"added   {name} ({role})")
        else:
            print(f"exists  {row.user_name} ({row.role})")
        if not row.password_hash:
            row.email = row.email or email
            row.password_hash = hash_password(DEMO_PASSWORD)
            print(f"        login: {row.email} / {DEMO_PASSWORD}")
    db.commit()
