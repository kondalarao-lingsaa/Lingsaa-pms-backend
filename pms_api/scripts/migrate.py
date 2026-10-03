r"""Brings an existing database up to date with the models. Safe to run any number of times.

create_all() (scripts/init_db.py) only creates missing tables; columns added to existing tables later
are listed here and added only when missing.
Run from backend/pms_api:  venv\Scripts\python scripts\migrate.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from app.db.session import engine  # noqa: E402

# (table, column, SQL type) - always nullable, so existing rows stay valid.
ADDED_COLUMNS = [
    ("projectmanagement.projects", "customer_contact_name", "NVARCHAR(200)"),
    ("projectmanagement.projects", "customer_mobile", "NVARCHAR(15)"),
    ("projectmanagement.projects", "customer_email", "NVARCHAR(150)"),
    ("projectmanagement.projects", "customer_gstin", "NVARCHAR(15)"),
    ("projectmanagement.projects", "customer_pan", "NVARCHAR(10)"),
    ("projectmanagement.tasks", "milestone_id", "INT"),
    ("projectmanagement.time_entries", "invoice_id", "INT"),
    ("projectmanagement.tasks", "sprint_id", "INT"),
    ("projectmanagement.expenses", "invoice_id", "INT"),
    ("projectmanagement.expenses", "receipt_document_id", "INT"),
    ("projectmanagement.company_settings", "industry", "NVARCHAR(40)"),
    ("projectmanagement.company_settings", "member_roles", "NVARCHAR(1000)"),
    ("projectmanagement.company_settings", "pm_approval_limit", "DECIMAL(18,2)"),
    ("projectmanagement.company_settings", "high_approval_limit", "DECIMAL(18,2)"),
    ("projectmanagement.company_settings", "expense_approval_limit", "DECIMAL(18,2)"),
    ("projectmanagement.projects", "submitted_by", "INT"),
    ("projectmanagement.projects", "submitted_by_name", "NVARCHAR(200)"),
    ("projectmanagement.projects", "submitted_at", "DATETIME"),
    ("projectmanagement.projects", "approval_level", "INT"),
    ("projectmanagement.projects", "approval_levels", "INT"),
    ("projectmanagement.projects", "approved_by", "INT"),
    ("projectmanagement.projects", "approved_by_name", "NVARCHAR(200)"),
    ("projectmanagement.projects", "approved_at", "DATETIME"),
    ("projectmanagement.projects", "approval_note", "NVARCHAR(1000)"),
    ("projectmanagement.documents", "client_visible", "BIT"),
    ("projectmanagement.projects", "baseline_budget", "DECIMAL(18,2)"),
    ("projectmanagement.projects", "baseline_start_date", "DATE"),
    ("projectmanagement.projects", "baseline_end_date", "DATE"),
    ("projectmanagement.projects", "baseline_at", "DATETIME"),
    ("projectmanagement.milestones", "baseline_due_date", "DATE"),
]

# Columns widened after they were created.
WIDENED_COLUMNS = [
    ("projectmanagement.company_settings", "industry", "NVARCHAR(60)"),
]

with engine.begin() as conn:
    for table, column, sql_type in ADDED_COLUMNS:
        conn.execute(text(f"IF COL_LENGTH('{table}', '{column}') IS NULL ALTER TABLE {table} ADD {column} {sql_type} NULL"))
        print(f"ok: {table}.{column}")
    for table, column, sql_type in WIDENED_COLUMNS:
        conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN {column} {sql_type} NULL"))
        print(f"ok: {table}.{column} is {sql_type}")

# Text columns must be Unicode (NVARCHAR): with VARCHAR, the rupee sign, Telugu/Hindi names or any non-English
# text is saved as "?". Each VARCHAR column is changed in place (same length, same NULL rule, same default).
# Columns inside an index keep VARCHAR (they hold codes and statuses, always plain ASCII).
with engine.connect() as conn:
    columns = conn.execute(text("""
        SELECT c.TABLE_NAME, c.COLUMN_NAME, c.CHARACTER_MAXIMUM_LENGTH, c.IS_NULLABLE
        FROM INFORMATION_SCHEMA.COLUMNS c
        WHERE c.TABLE_SCHEMA = 'projectmanagement' AND c.DATA_TYPE = 'varchar'
          AND NOT EXISTS (
              SELECT 1 FROM sys.index_columns ic
              JOIN sys.columns sc ON sc.object_id = ic.object_id AND sc.column_id = ic.column_id
              WHERE ic.object_id = OBJECT_ID('projectmanagement.' + c.TABLE_NAME) AND sc.name = c.COLUMN_NAME)
    """)).all()
converted, kept = 0, []
for table, column, length, nullable in columns:
    size = "MAX" if length in (-1, None) or length > 4000 else str(length)
    try:
        # One transaction per column: a column an index filter depends on is kept as it is, the rest still convert.
        with engine.begin() as conn:
            default = conn.execute(text("""
                SELECT dc.name, dc.definition FROM sys.default_constraints dc
                JOIN sys.columns sc ON sc.object_id = dc.parent_object_id AND sc.column_id = dc.parent_column_id
                WHERE dc.parent_object_id = OBJECT_ID(:t) AND sc.name = :c
            """), {"t": f"projectmanagement.{table}", "c": column}).first()
            if default:
                conn.execute(text(f"ALTER TABLE projectmanagement.{table} DROP CONSTRAINT [{default[0]}]"))
            conn.execute(text(f"ALTER TABLE projectmanagement.{table} ALTER COLUMN [{column}] NVARCHAR({size}) {'NULL' if nullable == 'YES' else 'NOT NULL'}"))
            if default:
                conn.execute(text(f"ALTER TABLE projectmanagement.{table} ADD CONSTRAINT [{default[0]}] DEFAULT {default[1]} FOR [{column}]"))
        converted += 1
    except Exception:  # noqa: BLE001 - kept as VARCHAR; listed below
        kept.append(f"{table}.{column}")
print(f"ok: {converted} text columns changed to Unicode (NVARCHAR)" + (f"; kept (used by an index filter): {', '.join(kept)}" if kept else ""))

# Data backfills - each only inserts what is missing.
BACKFILLS = {
    # Projects approved before baselines existed: their current plan becomes the baseline (no variance yet).
    "baselines of approved projects": """
        UPDATE projectmanagement.projects
        SET baseline_budget = budget, baseline_start_date = start_date, baseline_end_date = end_date, baseline_at = updated_at
        WHERE baseline_at IS NULL AND is_deleted = 0 AND status IN ('Approved', 'Active', 'On Hold', 'Closed')
    """,
    "baselines of their milestones": """
        UPDATE m SET m.baseline_due_date = m.due_date
        FROM projectmanagement.milestones m JOIN projectmanagement.projects p ON p.id = m.project_id
        WHERE m.baseline_due_date IS NULL AND m.due_date IS NOT NULL AND m.is_deleted = 0
          AND p.baseline_at IS NOT NULL AND m.created_at <= p.baseline_at
    """,
    # Teams arrived after projects: every project manager joins their project's team (0% = not planned yet).
    "project managers on their teams": """
        INSERT INTO projectmanagement.project_members (client_id, project_id, user_id, member_name, role, allocation_pct)
        SELECT p.client_id, p.id, p.project_manager_id, p.project_manager_name, 'Project Manager', 0
        FROM projectmanagement.projects p
        WHERE p.is_deleted = 0 AND p.project_manager_name IS NOT NULL AND LTRIM(p.project_manager_name) <> ''
          AND NOT EXISTS (SELECT 1 FROM projectmanagement.project_members m
                          WHERE m.project_id = p.id AND m.is_deleted = 0
                            AND (LOWER(m.member_name) = LOWER(p.project_manager_name)
                                 OR (p.project_manager_id IS NOT NULL AND m.user_id = p.project_manager_id)))
    """,
    # People already assigned tasks join that project's team, so their tasks stay valid.
    "task assignees on their teams": """
        INSERT INTO projectmanagement.project_members (client_id, project_id, user_id, member_name, role, allocation_pct)
        SELECT t.client_id, t.project_id, MAX(t.assignee_id), MIN(t.assignee_name), 'Other', 0
        FROM projectmanagement.tasks t
        WHERE t.is_deleted = 0 AND t.assignee_name IS NOT NULL AND LTRIM(t.assignee_name) <> ''
          AND NOT EXISTS (SELECT 1 FROM projectmanagement.project_members m
                          WHERE m.project_id = t.project_id AND m.is_deleted = 0
                            AND LOWER(m.member_name) = LOWER(t.assignee_name))
        GROUP BY t.client_id, t.project_id, LOWER(t.assignee_name)
    """,
}

with engine.begin() as conn:
    for name, sql in BACKFILLS.items():
        result = conn.execute(text(sql))
        print(f"ok: {name} ({result.rowcount} added)")

# Indexes - each created only when missing. The filtered unique ones are a database-level safety net
# behind the app's own checks (double-clicks, two people saving at the same moment).
INDEXES = {
    "ux_time_entry_day": ("projectmanagement.time_entries",
                          "CREATE UNIQUE INDEX ux_time_entry_day ON projectmanagement.time_entries (task_id, user_id, work_date) "
                          "WHERE is_deleted = 0 AND user_id IS NOT NULL"),
    "ux_invoice_milestone": ("projectmanagement.invoices",
                             "CREATE UNIQUE INDEX ux_invoice_milestone ON projectmanagement.invoices (milestone_id) "
                             "WHERE milestone_id IS NOT NULL AND is_deleted = 0 AND status <> 'Cancelled'"),
    "ix_task_dependency_on": ("projectmanagement.task_dependencies",
                              "CREATE INDEX ix_task_dependency_on ON projectmanagement.task_dependencies (depends_on_id)"),
    "ix_notification_inbox": ("projectmanagement.notifications",
                              "CREATE INDEX ix_notification_inbox ON projectmanagement.notifications (client_id, recipient_user_id, is_read)"),
}

with engine.begin() as conn:
    for name, (table, sql) in INDEXES.items():
        conn.execute(text(f"IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = '{name}' AND object_id = OBJECT_ID('{table}')) {sql}"))
        print(f"ok: index {name}")

# Team clean-up: exactly one "Project Manager" per project - the project's current manager (old managers left
# behind by a manager change are removed, or kept as "Other" when they have tasks/hours). Soft changes only.
# Dry run (shows the changes, saves nothing):  venv\Scripts\python scripts\migrate.py --dry-run
from types import SimpleNamespace  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.projects import Project  # noqa: E402
from app.models.team import ProjectMember  # noqa: E402
from app.repositories import team as team_repo  # noqa: E402

dry_run = "--dry-run" in sys.argv
db = SessionLocal()
try:
    changes = []
    for p in db.query(Project).filter(Project.is_deleted == False).all():  # noqa: E712
        team_repo.ensure_manager_member(db, SimpleNamespace(client_id=p.client_id, user_id=None), p, commit=False)
        for obj in list(db.dirty) + list(db.new):
            if isinstance(obj, ProjectMember) and obj.project_id == p.id and (obj in db.new or db.is_modified(obj)):
                what = "added" if obj in db.new else ("removed" if obj.is_deleted else f"role -> {obj.role}")
                changes.append(f"{p.project_code} {p.project_name}: {obj.member_name} {what}")
        db.flush()
    for line in sorted(set(changes)):
        print(("would change: " if dry_run else "changed: ") + line)
    if dry_run:
        db.rollback()
    else:
        db.commit()
    print(f"ok: project managers on teams ({len(set(changes))} change(s){', dry run - nothing saved' if dry_run else ''})")
finally:
    db.close()
