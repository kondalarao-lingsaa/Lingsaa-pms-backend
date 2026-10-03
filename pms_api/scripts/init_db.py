"""Create the `projectmanagement` schema and tables in lingsaa_pms, then seed the default roles.

Safe to re-run: existing tables are left alone and seed rows are only inserted when missing.
Run from backend/pms_api:  venv\\Scripts\\python scripts\\init_db.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.roles import ROLE_MATRIX, ROLES  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.models import projects as project_models  # noqa: E402,F401  (registers tables on Base)
from app.models import tasks as task_models  # noqa: E402,F401  (registers tables on Base)
from app.models import team as team_models  # noqa: E402,F401  (registers tables on Base)
from app.models import timesheets as timesheet_models  # noqa: E402,F401  (registers tables on Base)
from app.models import milestones as milestone_models  # noqa: E402,F401  (registers tables on Base)
from app.models import billing as billing_models  # noqa: E402,F401  (registers tables on Base)
from app.models import risks as risk_models  # noqa: E402,F401  (registers tables on Base)
from app.models import documents as document_models  # noqa: E402,F401  (registers tables on Base)
from app.models import sprints as sprint_models  # noqa: E402,F401  (registers tables on Base)
from app.models import notifications as notification_models  # noqa: E402,F401  (registers tables on Base)
from app.models import settings as settings_models  # noqa: E402,F401  (registers tables on Base)
from app.models import templates as template_models  # noqa: E402,F401  (registers tables on Base)
from app.models import expenses as expense_models  # noqa: E402,F401  (registers tables on Base)
from app.models import project_settings as project_settings_models  # noqa: E402,F401  (registers tables on Base)
from app.models import roles as role_models  # noqa: E402,F401  (registers tables on Base)
from app.models import access as access_models  # noqa: E402,F401  (registers tables on Base)
from app.models.roles import SCHEMA, DefaultRole, DefaultRolePermission  # noqa: E402


def main():
    with engine.begin() as conn:
        conn.execute(text(f"IF SCHEMA_ID('{SCHEMA}') IS NULL EXEC('CREATE SCHEMA {SCHEMA}')"))
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        for role in ROLES:
            row = db.query(DefaultRole).filter_by(role_key=role["key"]).one_or_none()
            if row is None:
                row = DefaultRole(role_key=role["key"], title=role["title"], responsibility=role["responsibility"])
                db.add(row)
                db.flush()
            existing = {(p.module_group, p.action) for p in db.query(DefaultRolePermission).filter_by(role_id=row.id)}
            for group, actions in ROLE_MATRIX.get(role["key"], {}).items():
                for action in actions:
                    if (group, action) not in existing:
                        db.add(DefaultRolePermission(role_id=row.id, module_group=group, action=action))
        db.commit()

        print("DB:", db.execute(text("SELECT DB_NAME()")).scalar())
        print("default_roles:", db.query(DefaultRole).count())
        print("default_role_permissions:", db.query(DefaultRolePermission).count())


if __name__ == "__main__":
    main()
