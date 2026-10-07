# LINGSAA PMS API

FastAPI + SQLAlchemy service for the Project Management module (SQL Server database `lingsaa_pms`, schema `projectmanagement`).

## First-time setup (Windows, PowerShell)

```powershell
cd backend\pms_api
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt
copy .env.example .env          # then fill in DB_* and JWT_SECRET
.\venv\Scripts\python scripts\test_connection.py   # checks the database login
.\venv\Scripts\python scripts\init_db.py           # creates missing tables
.\venv\Scripts\python scripts\migrate.py           # adds columns introduced later (safe to re-run)
```

## Run

```powershell
# development (do not use --reload on Windows; restart after code changes)
.\venv\Scripts\python -m uvicorn app.main:app --port 8000

# production
.\venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 --proxy-headers --no-server-header --no-access-log
```

- Health: `GET /api/health` returns 200 when the API and the database are up, 503 when the database is unreachable.
- API docs: `/docs` (development only; switched off when `ENVIRONMENT=production`).

## Automation (Settings > Automation)

The API runs each company's scheduled jobs by itself: task, approval and timesheet reminders, the weekly status
report, budget / deadline / invoice alerts, monthly time & material draft invoices, recurring tasks and finishing
sprints. Event automations (draft invoice on milestone acceptance, main task done with its subtasks, milestone sent
for review) run straight after the action. Admins switch each job on or off, set its time and numbers, and use
Run now in Settings > Automation; every run is in the run history there.

- `AUTOMATION_ENABLED=false` stops the background scheduler on a server (Run now still works). With several API
  servers it is safe to leave it on everywhere: each job is claimed by one server per day.
- Schedules use the server's local time; jobs marked "working day" skip the company's weekends and holidays.
- Emails need `SMTP_HOST`; without it they are written to `storage/outbox` as `.eml` files.
- Test: `venv\Scripts\python tests\api_automation.py` (uses its own test company 900777).

## Production checklist

- `ENVIRONMENT=production`, `JWT_ENFORCE_SIGNATURE=True`, `ALLOW_TENANT_FROM_QUERY=False`, real `JWT_SECRET` (the app refuses to start otherwise). Signature checking is on by default in every environment; turning it off is for local development only (anyone could then sign in as anyone).
- When the MASTER login replaces the PMS's own login, set `DEMO_LOGIN_ENABLED=false`.
- `CORS_ORIGINS` lists only the real frontend address(es).
- `UPLOAD_DIR` points at a disk or share that is backed up (uploaded documents live there; default `storage/uploads`, not in git). `MAX_UPLOAD_MB` sets the largest file (default 15).
- After pulling new code run `scripts/init_db.py` and `scripts/migrate.py` (both safe to re-run).
- Run behind HTTPS (IIS / nginx reverse proxy). Every response carries `X-Request-ID`; the same id is in the log line and in 500-error messages.

## Layout

| Folder | Holds |
|---|---|
| `app/api/routes` | HTTP endpoints (projects, tasks, dashboard, meta, health) |
| `app/schemas` | Request validation; `rules.py` mirrors the frontend's `src/pms/utils/validation.js` |
| `app/repositories` | Database queries, always scoped to the caller's company (`client_id`) |
| `app/models` | SQLAlchemy tables |
| `app/core` | Settings, token handling, roles |
| `scripts` | Setup and maintenance scripts |
