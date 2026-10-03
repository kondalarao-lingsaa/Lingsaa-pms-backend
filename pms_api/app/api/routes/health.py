import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine

router = APIRouter(tags=["health"])
logger = logging.getLogger("pms.health")


@router.get("/health")
def health_check():
    """Liveness + database check, for load balancers and uptime monitors."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        database = "ok"
    except Exception:  # noqa: BLE001 - any DB failure means "not ready"
        logger.exception("Health check: database unreachable")
        database = "unreachable"

    body = {"status": "ok" if database == "ok" else "degraded", "database": database, "version": settings.APP_VERSION}
    return JSONResponse(body, status_code=200 if database == "ok" else 503)
