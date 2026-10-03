"""API checks for the go-live fixes of 2026-10-02: approvals need a user id, only the requester withdraws a change
request, CSV cells cannot run as Excel formulas, X-Request-ID is sanitised.
Run from backend/pms_api with the API on port 8000:  venv\\Scripts\\python tests\\api_security_fixes.py
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

sys.path.insert(0, os.getcwd())
from jose import jwt  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.repositories.reports import to_csv  # noqa: E402

ROOT = r"C:\Users\kondalarao\Documents\LINGSAA_PMS"
dev = re.search(r"NEXT_PUBLIC_PMS_DEV_TOKEN=(.*)", open(os.path.join(ROOT, "frontend", ".env.local")).read()).group(1).strip()
_mint = lambda claims: jwt.encode({"client_id": 900001, "exp": int(time.time()) + 3600, **claims}, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)  # noqa: E731
mgr = _mint({"user_id": 2, "username": "qa.manager", "role": "admin"})
no_id = _mint({"username": "no.id.user"})
B = "http://localhost:8000/api"


def call(method, path, body=None, token=None, headers=None):
    req = urllib.request.Request(B + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + (token or dev), "Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read()), r.headers
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read()), e.headers


fails = 0


def ok(name, cond, extra=""):
    global fails
    fails += 0 if cond else 1
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {extra}"))


today = date.today()
d = lambda n: (today + timedelta(days=n)).isoformat()  # noqa: E731
NAME = "Security Fixes Api Check"
for p in call("GET", f"/projects/list?search={NAME.replace(' ', '%20')}&page_size=20")[1].get("detail") or []:
    if p["project_name"] == NAME:
        call("DELETE", f"/projects/{p['id']}")
status, body, _ = call("POST", "/projects/create", {"project_name": NAME, "project_type": "Time & Material", "customer_name": "Acme Retail",
                                                    "customer_contact_name": "Ravi Kumar", "customer_mobile": "9876543210", "start_date": d(-30),
                                                    "end_date": d(60), "budget": 100000, "project_manager_name": "Priya Shah"})
ok("project created", status == 201, body)
pid = body["data"]["id"]
for st in ("Pending Approval", "Approved", "Active"):
    call("POST", f"/projects/{pid}/status", {"status": st})
call("POST", f"/projects/{pid}/members", {"member_name": "Dev User", "user_id": 1, "role": "Developer", "allocation_pct": 10, "hourly_rate": 500})
task = call("POST", "/tasks/create", {"project_id": pid, "title": "Check the fixes", "assignee_name": "Dev User", "estimated_hours": 8})[1]["data"]
log_day = today if today.weekday() < 5 else today - timedelta(days=today.weekday() - 4)
te = call("POST", "/timesheets/entries", {"task_id": task["id"], "work_date": log_day.isoformat(), "hours": 2})[1]["data"]
call("POST", "/timesheets/submit", {"week_start": (log_day - timedelta(days=log_day.weekday())).isoformat()})

print("\n[1] Approvals need a signed-in user id")
status, body, _ = call("POST", "/timesheets/approve", {"entry_ids": [te["id"]]}, token=no_id)
# Without a user id there is no PMS role either, so the role check refuses it first (403).
ok("a login without user id cannot approve time", status == 403 or (status == 409 and "no user id" in body["detail"]), (status, body))
status, body, _ = call("POST", "/timesheets/approve", {"entry_ids": [te["id"]]})
ok("nobody approves their own time", status == 409 and "own time" in body["detail"], (status, body))
status, body, _ = call("POST", "/timesheets/approve", {"entry_ids": [te["id"]]}, token=mgr)
ok("another manager approves it", status == 200, (status, body))

print("\n[2] Only the requester withdraws a change request")
status, body, _ = call("POST", f"/projects/{pid}/change-requests", {"title": "Add a reports page", "reason": "Client asked for one more report page",
                                                                     "change_type": "Scope"})
ok("change request raised", status == 201, (status, body))
cr = body["data"]["id"]
status, body, _ = call("POST", f"/projects/{pid}/change-requests/{cr}/approve", {}, token=no_id)
ok("a login without user id cannot decide it", status == 403 or (status == 409 and "no user id" in body["detail"]), (status, body))
status, body, _ = call("DELETE", f"/projects/{pid}/change-requests/{cr}", token=mgr)
ok("someone else cannot withdraw it", status == 409 and "only they can withdraw" in body["detail"], (status, body))
status, body, _ = call("DELETE", f"/projects/{pid}/change-requests/{cr}")
ok("the requester can withdraw it", status in (200, 204), (status, body))

print("\n[3] CSV export cannot run Excel formulas")
csv = to_csv({"title": "T", "columns": [{"key": "a", "label": "A"}, {"key": "n", "label": "N"}],
              "rows": [{"a": "=HYPERLINK(\"http://x\")", "n": -5}, {"a": "@SUM(1)", "n": 3}, {"a": "Normal", "n": 1}]}).decode("utf-8")
ok("text starting with = is prefixed", "'=HYPERLINK" in csv, csv)
ok("text starting with @ is prefixed", "'@SUM" in csv, csv)
ok("numbers stay numbers", ",-5" in csv and "'-5" not in csv, csv)

print("\n[4] X-Request-ID")
_, _, h = call("GET", "/health", headers={"X-Request-ID": "abc-123"})
ok("a plain id is echoed", h.get("X-Request-ID") == "abc-123", h.get("X-Request-ID"))
_, _, h = call("GET", "/health", headers={"X-Request-ID": "bad id<script>"})
ok("an unsafe id is replaced", h.get("X-Request-ID") not in (None, "bad id<script>"), h.get("X-Request-ID"))

call("DELETE", f"/projects/{pid}")
print("\nALL PASSED" if fails == 0 else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
