"""API checks for the shared fixes of the 2026-10-05 audit: login tokens must be signed, name-only notifications never
reach a Client, approval history follows project visibility, a removed Client never becomes a Member, the login and
change-password limits, created_by for project creators, Accepted milestones keep their tasks, an active sprint blocks
closing a project, and the dashboard / reports budgets.
Uses demo company 900001 only; everything it creates is named "Audit ...".
Run from backend/pms_api:  venv\\Scripts\\python tests\\api_shared_fixes.py   (PMS_API_URL=http://127.0.0.1:8108/api for another copy)
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

sys.path.insert(0, os.getcwd())
from jose import jwt  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import engine  # noqa: E402

B = os.environ.get("PMS_API_URL", "http://localhost:8000/api")
USERS = {"admin": (1, "dev.user"), "pm": (3, "priya.sharma"), "member": (5, "anita.rao"), "client": (8, "ravi.kumar")}


def mint(claims, secret=None):
    return jwt.encode({"exp": int(time.time()) + 3600, **claims}, secret or settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


TOKENS = {k: mint({"client_id": 900001, "user_id": uid, "username": name}) for k, (uid, name) in USERS.items()}


def call(who, method, path, body=None, token=None):
    req = urllib.request.Request(B + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": "Bearer " + (token or TOKENS[who])} if (token or who) else {})})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


fails = 0


def ok(name, cond, extra=""):
    global fails
    fails += 0 if cond else 1
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {extra}"))


today = date.today()
stamp = str(int(time.time()))[-6:]
created = []
AUDIT_USER = 990201
AUDIT_EMAIL = f"audit.client{AUDIT_USER}@example.com"
AUDIT_PASSWORD = "Audit@Pass2026"


def new_project(who, name, budget=50000, manager=("Priya Sharma", 3)):
    body = {"project_name": f"Audit Shared {name} {stamp}", "project_type": "Fixed Price", "customer_name": "Acme Retail",
            "customer_contact_name": "Ravi Kumar", "customer_mobile": "9876543210", "start_date": today.isoformat(),
            "end_date": (today + timedelta(days=60)).isoformat(), "budget": budget, "project_manager_name": manager[0],
            "project_manager_id": manager[1]}
    s, r = call(who, "POST", "/projects/create", body)
    if s == 201:
        created.append(r["data"]["id"])
    return s, r


def drop_audit_user():
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM projectmanagement.user_roles WHERE client_id = 900001 AND user_id = :u"), {"u": AUDIT_USER})


try:
    # PMS-SEC-1: only tokens signed with the PMS secret, and the company always comes from the token
    forged = mint({"client_id": 900001, "user_id": 1, "username": "forged"}, secret="not-the-secret")
    s, _ = call(None, "GET", "/me", token=forged)
    ok("A token signed with another secret is refused (401)", s == 401, s)
    s, _ = call(None, "GET", "/me?client_id=900001&user_id=1", token=mint({"username": "no.company"}))
    ok("The company cannot come from the query string (403)", s == 403, s)

    # PMS-SEC-2: a task notification for a team member typed by name never reaches a Client login of that name
    s, draft = new_project("admin", "Notify Draft")
    pid = draft["data"]["id"]
    s, r = call("admin", "POST", f"/projects/{pid}/members", {"member_name": "Ravi Kumar", "role": "Developer", "allocation_pct": 0})
    ok("Admin adds 'Ravi Kumar' by name (no login)", s == 201 and r["data"]["user_id"] is None, r)
    s, task = call("admin", "POST", "/tasks/create", {"project_id": pid, "title": "Audit internal pricing task", "assignee_name": "Ravi Kumar"})
    ok("Task assigned to the typed member", s == 201, task)
    marker = f"Audit internal note {stamp}"
    s, r = call("admin", "POST", f"/tasks/{task['data']['id']}/comments", {"body": marker})
    ok("Internal comment added", s == 201, r)
    s, r = call("client", "GET", "/notifications?page_size=50")
    ok("Client login of the same name gets none of it", s == 200 and marker not in json.dumps(r) and "Audit internal pricing task" not in json.dumps(r), r)

    # PMS-SEC-3: approval history only for projects the caller can see
    s, hist = new_project("pm", "History", budget=500000)
    hid = hist["data"]["id"]
    call("pm", "POST", f"/projects/{hid}/status", {"status": "Pending Approval"})
    s, r = call("pm", "GET", f"/approvals/history?entity_type=project&entity_id={hid}")
    ok("PM sees the history of their project", s == 200 and r["detail"], r)
    s, _ = call("member", "GET", f"/projects/{hid}")
    s2, r = call("member", "GET", f"/approvals/history?entity_type=project&entity_id={hid}")
    ok("Member gets 404 for the project and an empty history", s == 404 and s2 == 200 and r["detail"] == [], (s, s2, r))

    # PMS-SEC-6: a project without a manager login is run by its creator, and the screens can tell
    s, r = new_project("pm", "No Manager", manager=("Audit Nobody", None))
    ok("project_out carries created_by", s == 201 and r["data"]["project_manager_id"] is None and r["data"]["created_by"] == 3, r)

    # PMS-SEC-7: wrong passwords are counted per address + email, and change-password has the same limit
    drop_audit_user()
    s, r = call("admin", "POST", "/settings/users", {"user_id": AUDIT_USER, "user_name": "Audit Client Login", "role": "client",
                                                     "customer_name": "Acme Retail", "email": AUDIT_EMAIL, "password": AUDIT_PASSWORD})
    ok("Admin adds an Audit client login", s == 201, r)
    role_id = r["data"]["id"]
    wrong = f"audit.lock{stamp}@example.com"
    codes = [call(None, "POST", "/auth/login", {"email": wrong, "password": "Wrong@Pass1"})[0] for _ in range(6)]
    ok("Five wrong passwords lock that email (429 on the 6th)", codes == [401] * 5 + [429], codes)
    s, r = call(None, "POST", "/auth/login", {"email": AUDIT_EMAIL, "password": AUDIT_PASSWORD})
    ok("Another email still signs in", s == 200 and r["detail"]["role"] == "client", r)
    client_token = r["detail"]["token"]
    codes = [call(None, "POST", "/auth/change-password", {"current_password": "Wrong@Pass1", "new_password": "Audit@Pass2027"},
                  token=client_token)[0] for _ in range(6)]
    ok("Five wrong current passwords lock change-password (429 on the 6th)", codes == [409] * 5 + [429], codes)

    # PMS-SEC-4: 'Remove Role' on a Client switches their access off instead of making them a Member
    s, r = call(None, "GET", "/me", token=client_token)
    ok("The client session works before", s == 200 and r["detail"]["role"] == "client", r)
    s, r = call("admin", "DELETE", f"/settings/users/{role_id}")
    ok("Removing a Client's role switches their access off", s == 200 and "switched off" in r["detail"], r)
    s, r = call(None, "GET", "/me", token=client_token)
    ok("Their open session is refused, not turned into a Member (403)", s == 403, (s, r))
    s, r = call(None, "GET", "/team/meta", token=client_token)
    ok("…and cannot read the staff list (403)", s == 403, s)

    # MB-2 / TS-7: an Accepted milestone keeps its tasks; an active sprint blocks closing the project
    s, act = new_project("admin", "Close Rules")
    aid = act["data"]["id"]
    for st in ("Pending Approval", "Approved", "Active"):
        call("admin", "POST", f"/projects/{aid}/status", {"status": st})
    s, ms = call("admin", "POST", f"/projects/{aid}/milestones", {"name": "Audit Sign-off", "amount": 10000})
    mid = ms["data"]["id"]
    call("admin", "POST", f"/projects/{aid}/members", {"member_name": "Priya Sharma", "user_id": 3, "role": "Developer", "allocation_pct": 0})
    s, t1 = call("admin", "POST", "/tasks/create", {"project_id": aid, "title": "Audit milestone task", "milestone_id": mid})
    tid = t1["data"]["id"]
    call("admin", "POST", f"/tasks/{tid}/status", {"status": "Done"})
    call("admin", "POST", f"/projects/{aid}/milestones/{mid}/deliverables", {"name": "Audit hand-over"})
    s, r = call("admin", "GET", f"/projects/{aid}/milestones")
    did = r["detail"][0]["deliverables"][0]["id"]
    call("admin", "POST", f"/projects/{aid}/milestones/{mid}/deliverables/{did}/done", {"is_done": True})
    call("admin", "POST", f"/projects/{aid}/milestones/{mid}/status", {"status": "Ready for Review"})
    s, r = call("admin", "POST", f"/projects/{aid}/milestones/{mid}/status", {"status": "Accepted", "feedback": "Audit accepted"})
    ok("Milestone accepted", s == 200, r)
    s, r = call("admin", "GET", f"/tasks/{tid}")
    t = r["detail"]
    body = {k: t.get(k) for k in ("project_id", "title", "task_type", "priority", "status", "assignee_name", "assignee_id", "updated_at")}
    s, r = call("admin", "PUT", f"/tasks/{tid}", {**body, "milestone_id": None})
    ok("A task cannot leave an Accepted milestone", s in (400, 409) and "Accepted" in str(r.get("detail")), (s, r))

    s, t2 = call("admin", "POST", "/tasks/create", {"project_id": aid, "title": "Audit sprint task"})
    s, sp = call("admin", "POST", f"/projects/{aid}/sprints", {"name": "Audit Sprint", "start_date": today.isoformat(),
                                                              "end_date": (today + timedelta(days=13)).isoformat()})
    sid = sp["data"]["id"]
    call("admin", "POST", f"/sprints/{sid}/tasks", {"task_ids": [t2["data"]["id"]]})
    s, r = call("admin", "POST", f"/sprints/{sid}/start")
    ok("Sprint started", s == 200, r)
    s, r = call("admin", "POST", f"/projects/{aid}/status", {"status": "Closed"})
    ok("A project with an active sprint cannot be closed", s == 409 and "Audit Sprint" in r.get("detail", ""), (s, r))
    call("admin", "POST", f"/sprints/{sid}/complete")

    # TS-14: dashboard and reports still give every project's money
    s, r = call("admin", "GET", "/dashboard/overview")
    ok("Dashboard overview loads with budgets", s == 200 and all("budgetActual" in p for p in r["detail"]["projects"]), s)
    for report in ("project-status", "budget"):
        s, r = call("admin", "GET", f"/reports/{report}")
        ok(f"Report {report} loads", s == 200 and r["detail"]["rows"] is not None, s)
finally:
    drop_audit_user()
    for pid in created:
        call("admin", "DELETE", f"/projects/{pid}")

print("\nALL CHECKS PASSED" if not fails else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
