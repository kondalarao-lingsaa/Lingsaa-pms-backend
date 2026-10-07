"""The background scheduler behind Settings > Automation.

A daemon thread wakes up every AUTOMATION_TICK_SECONDS, and for every company runs the scheduled jobs whose time
has come (app/repositories/automation.py due_jobs). Each job is claimed with one UPDATE before it runs, so with
several workers or servers a job still runs once a day. A job that fails is recorded in the run history; it never
stops the others or the API. Started and stopped by the app's lifespan (main.py).
"""
import logging
import threading
from datetime import datetime

from app.core.config import settings
from app.db.session import SessionLocal

logger = logging.getLogger("pms.scheduler")

_stop = threading.Event()
_thread = None


def tick(now: datetime = None) -> list:
    """One pass over every company. Returns what ran: [(client_id, job_key, status)]."""
    from app.repositories import automation  # local import: the repositories import the models at load time

    now = now or datetime.now()
    ran = []
    db = SessionLocal()
    try:
        for client_id in automation.companies(db):
            try:
                due = automation.due_jobs(db, client_id, now)
            except Exception:  # noqa: BLE001 - one company's bad data must not stop the others
                db.rollback()
                logger.exception("Could not check automation for company %s", client_id)
                continue
            for job_key in due:
                if _stop.is_set():
                    return ran
                if not automation.claim(db, client_id, job_key, now.date()):
                    continue  # another worker took it
                result = automation.run_job(db, client_id, job_key, trigger="Schedule")
                logger.info("Automation %s for company %s: %s - %s", job_key, client_id, result["status"], result["summary"])
                ran.append((client_id, job_key, result["status"]))
        if now.hour == 3 and now.minute < 2:
            automation.prune(db)
    finally:
        db.close()
    return ran


def _loop() -> None:
    logger.info("Automation scheduler started (every %ss)", settings.AUTOMATION_TICK_SECONDS)
    while not _stop.wait(settings.AUTOMATION_TICK_SECONDS):
        try:
            tick()
        except Exception:  # noqa: BLE001 - e.g. the database is down for a moment; try again next minute
            logger.exception("Automation scheduler pass failed")
    logger.info("Automation scheduler stopped")


def start() -> None:
    global _thread
    if not settings.AUTOMATION_ENABLED or (_thread is not None and _thread.is_alive()):
        if not settings.AUTOMATION_ENABLED:
            logger.info("Automation scheduler is off (AUTOMATION_ENABLED=false); jobs run only with Run now")
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="pms-automation", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()


def is_running() -> bool:
    return _thread is not None and _thread.is_alive()
