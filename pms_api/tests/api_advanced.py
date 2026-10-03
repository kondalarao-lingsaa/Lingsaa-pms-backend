"""API checks for industries (presets + a company's own), the approved-plan baseline, email alerts and approval
reminders. Needs the demo role users (scripts/seed_demo_roles.py) and the API on port 8000.
Run from backend/pms_api:  venv\\Scripts\\python tests\\api_advanced.py
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from email import message_from_bytes

sys.path.insert(0, os.getcwd())
from jose import jwt  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.mailer import outbox_dir  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.models.projects import Project  # noqa: E402

B = "http://localhost:8000/api"
USERS = {"admin": (1, "dev.user"), "director": (9, "rohan.verma"), "pm": (3, "priya.sharma")}
TOKENS = {k: jwt.encode({"client_id": 900001, "user_id": uid, "username": name, "exp": int(time.time()) + 3600}, settings.JWT_SECRET,
                        algorithm=settings.JWT_ALGORITHM) for k, (uid, name) in USERS.items()}


def call(who, method, path, body=None):
    req = urllib.request.Request(B + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + TOKENS[who], "Content-Type": "application/json"})
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
s, before = call("admin", "GET", "/settings")
saved_industry, saved_roles = before["detail"]["industry"], before["detail"]["member_roles"]

try:
    # 1. industries
    names = [i["name"] for i in before["detail"]["industries"]]
    ok("15 industry presets plus General", len(names) == 16 and "Legal" in names and "Engineering / EPC" in names, names)
    s, r = call("admin", "PUT", "/settings/industry", {"industry": "solar installation", "member_roles": ["Project Manager", "Site Surveyor", "Installer"]})
    ok("A company can type its own industry", s == 200 and r["data"]["industry"] == "Solar installation" and r["data"]["custom_industry"], r)
    s, r = call("admin", "POST", "/templates/starter?industry=Solar%20installation")
    ok("Its starter template is the General one", s == 201 and r["data"]["name"] == "General Project", r)
    if s == 201:
        call("admin", "DELETE", f"/templates/{r['data']['id']}")
    s, r = call("admin", "PUT", "/settings/industry", {"industry": "x", "member_roles": ["Project Manager", "Other"]})
    ok("A one-letter industry is refused", s == 422, s)

    # 2. baseline
    body = {"project_name": f"Zz Baseline {stamp}", "project_type": "Fixed Price", "customer_name": "Acme Retail", "customer_contact_name": "Ravi Kumar",
            "customer_mobile": "9876543210", "start_date": today.isoformat(), "end_date": (today + timedelta(days=30)).isoformat(),
            "budget": 300000, "project_manager_name": "Priya Sharma", "project_manager_id": 3}
    s, p = call("pm", "POST", "/projects/create", body)
    pid = p["data"]["id"]
    created.append(pid)
    s, ms = call("pm", "POST", f"/projects/{pid}/milestones", {"name": "Go Live", "due_date": (today + timedelta(days=25)).isoformat()})
    call("pm", "POST", f"/projects/{pid}/status", {"status": "Pending Approval"})
    ok("No baseline before approval", call("pm", "GET", f"/projects/{pid}")[1]["detail"]["baseline"] is None)
    s, r = call("director", "POST", f"/projects/{pid}/status", {"status": "Approved"})
    base = r["data"]["baseline"]
    ok("Approval freezes the baseline (budget and dates)", base and base["budget"] == 300000 and base["end_date"] == body["end_date"], base)
    s, r = call("pm", "GET", f"/projects/{pid}/milestones")
    ok("Milestone due date is in the baseline", r["detail"][0]["baseline_due_date"] == r["detail"][0]["due_date"], r["detail"][0])
    call("pm", "POST", f"/projects/{pid}/status", {"status": "Active"})
    s, cr = call("pm", "POST", f"/projects/{pid}/change-requests", {"title": "Two more weeks", "reason": "Client added a new payment gateway",
                                                                     "change_type": "Schedule", "days_impact": 14, "cost_impact": 40000})
    s, r = call("director", "POST", f"/projects/{pid}/change-requests/{cr['data']['id']}/approve", {})
    s, r = call("pm", "GET", f"/projects/{pid}")
    d = r["detail"]
    ok("After a change, the live plan moves but the baseline stays",
       d["budget"] == 340000 and d["baseline"]["budget"] == 300000 and d["end_date"] != d["baseline"]["end_date"], d)

    # 3. email alert (no SMTP here, so it goes to the outbox folder)
    first = set(outbox_dir().glob("*.eml")) if outbox_dir().exists() else set()
    s, big = call("pm", "POST", "/projects/create", {**body, "project_name": f"Zz Email {stamp}", "budget": 500000})
    created.append(big["data"]["id"])
    call("pm", "POST", f"/projects/{big['data']['id']}/status", {"status": "Pending Approval"})
    time.sleep(2)
    new = sorted(set(outbox_dir().glob("*.eml")) - first)
    mails = [message_from_bytes(f.read_bytes()) for f in new]
    to_director = [m for m in mails if m["To"] == "rohan.verma@lingsaa.com"]
    ok("Submitting emails the Director (outbox file)", to_director and "needs your approval" in to_director[0]["Subject"], [m["To"] for m in mails])

    # 4. waiting days and reminders
    with Session(engine) as db:
        row = db.get(Project, big["data"]["id"])
        row.submitted_at = datetime.utcnow() - timedelta(days=5)
        db.commit()
    s, r = call("director", "GET", "/approvals")
    item = next((i for i in r["detail"]["items"] if i["kind"] == "project" and i["id"] == big["data"]["id"]), None)
    ok("The inbox shows how many days a request has waited", item and item["waiting_days"] == 5, item)
    from scripts.send_approval_reminders import run  # noqa: E402

    with Session(engine) as db:
        sent = run(db)
    ok("Reminder script reminds and escalates", sent["reminders"] >= 1 and sent["escalations"] >= 1, sent)
    s, r = call("admin", "GET", "/notifications?kind=reminder&limit=5")
    titles = [n["title"] for n in r["detail"]] if s == 200 else []
    ok("The Admin gets the escalation in the bell", any("Escalated" in t for t in titles), titles)
finally:
    for pid in created:
        call("admin", "DELETE", f"/projects/{pid}")
    call("admin", "PUT", "/settings/industry", {"industry": saved_industry, "member_roles": saved_roles})

print("\nALL CHECKS PASSED" if not fails else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
