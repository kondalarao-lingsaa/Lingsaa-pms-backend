r"""Approval reminders and escalation, run by hand.

The API now runs this every working day by itself (Settings > Automation > Approval reminders, where the time and
the number of days are set). This script is kept for running it from Windows Task Scheduler on a server where the
API's scheduler is switched off (AUTOMATION_ENABLED=false). It runs the same job for every company.

Run from backend/pms_api:  venv\Scripts\python scripts\send_approval_reminders.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.repositories import automation, automation_jobs  # noqa: E402


def run(db) -> dict:
    """Runs the reminders for every company now; {"reminders": n, "escalations": n} (kept for older callers)."""
    sent = {"reminders": 0, "escalations": 0}
    for client_id in automation.companies(db):
        result = automation_jobs.approval_reminders(db, client_id, automation.params_for(db, client_id, "approval_reminders"), date.today())
        sent["reminders"] += result["reminders"]
        sent["escalations"] += result["escalations"]
    return sent


if __name__ == "__main__":
    db = SessionLocal()
    try:
        for client_id in automation.companies(db):
            print(client_id, automation.run_job(db, client_id, "approval_reminders", trigger="Manual", by_name="Task Scheduler"))
    finally:
        db.close()
