import logging
import re
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import InterfaceError, OperationalError, SQLAlchemyError

from app.api.routes import billing, dashboard, documents, health, milestones, planning, projects, reports, risks, sprints, tasks, team, timesheets, workload, communication
from app.api.routes import settings as company_settings
from app.api.routes import expenses as expense_routes
from app.api.routes import access as access_routes
from app.api.routes import portal
from app.core.access import authorize
from app.core.config import settings

logging.basicConfig(
    level=settings.LOG_LEVEL.upper(),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger("pms.api")
_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("%s %s starting (environment=%s)", settings.APP_NAME, settings.APP_VERSION, settings.ENVIRONMENT)
    if not settings.JWT_ENFORCE_SIGNATURE or settings.ALLOW_TENANT_FROM_QUERY:
        logger.warning("Development auth shortcuts are ON (JWT signature not enforced / tenant from query). Never use in production.")
    yield


app = FastAPI(
    lifespan=lifespan,
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    # API docs are for developers; they are switched off in production.
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)

app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Tags every request with an id (echoed in X-Request-ID) and logs method, path, status and duration."""
    # A caller's own id is kept only if it is short and plain, so it cannot inject text into the logs.
    request_id = request.headers.get("X-Request-ID", "")
    if not _REQUEST_ID.fullmatch(request_id):
        request_id = uuid.uuid4().hex[:12]
    request.state.request_id = request_id
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.headers["X-Request-ID"] = request_id
    if request.url.path != "/api/health":
        logger.info("%s %s %s %.0fms [%s]", request.method, request.url.path, response.status_code, elapsed_ms, request_id)
    return response


def _field_name(loc) -> str:
    parts = [str(p) for p in loc if p not in ("body", "query", "path")]
    return ".".join(parts) or "request"


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """Returns form errors as {"detail": "<first message>", "errors": {field: message}} so the UI can show
    one clear toast and highlight each field, instead of pydantic's raw error list."""
    errors = {}
    for err in exc.errors():
        message = str(err.get("msg", "Invalid value")).removeprefix("Value error, ")
        errors.setdefault(_field_name(err.get("loc", ())), message)
    first = next(iter(errors.values()), "Invalid request")
    detail = first if len(errors) == 1 else f"Please fix the {len(errors)} highlighted fields below"
    return JSONResponse(status_code=422, content={"detail": detail, "errors": errors})


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(request: Request, exc: SQLAlchemyError):
    request_id = getattr(request.state, "request_id", "-")
    logger.exception("Database error [%s]", request_id)
    # Only a lost/refused connection means "database down"; anything else is a bug to report with its reference.
    if isinstance(exc, (OperationalError, InterfaceError)) or getattr(exc, "connection_invalidated", False):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "The database is not available right now. Please try again in a moment."},
        )
    return JSONResponse(status_code=500, content={"detail": f"Something went wrong while saving or reading data. Reference: {request_id}"})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "-")
    logger.exception("Unhandled error [%s]", request_id)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": f"Something went wrong. Reference: {request_id}"},
    )


app.include_router(health.router, prefix="/api")
# Every other route needs a signed-in user whose role allows it (app/core/access.py).
for router in (projects.router, tasks.router, team.router, timesheets.router, milestones.router, billing.router, risks.router, documents.router, planning.router, reports.router, sprints.router, dashboard.router, workload.router, communication.router, company_settings.router, expense_routes.router, access_routes.router, portal.router):
    app.include_router(router, prefix="/api", dependencies=[Depends(authorize)])
