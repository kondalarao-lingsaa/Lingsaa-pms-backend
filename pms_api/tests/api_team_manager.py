"""API checks: a project's team always has exactly one "Project Manager" - its current manager (bug 2026-10-02:
after changing the manager the old one was still listed as Project Manager).
Run from backend/pms_api with the API on port 8000:  venv\\Scripts\\python tests\\api_team_manager.py
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta

ROOT = r"C:\Users\kondalarao\Documents\LINGSAA_PMS"
dev = re.search(r"NEXT_PUBLIC_PMS_DEV_TOKEN=(.*)", open(os.path.join(ROOT, "frontend", ".env.local")).read()).group(1).strip()
B = "http://localhost:8000/api"


def call(method, path, body=None):
    req = urllib.request.Request(B + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + dev, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


fails = 0


def ok(name, cond, extra=""):
    global fails
    fails += 0 if cond else 1
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {extra}"))


d = lambda n: (date.today() + timedelta(days=n)).isoformat()  # noqa: E731
NAME = "Team Manager Api Check"
for p in call("GET", "/projects/options")[1].get("detail") or []:
    if p["project_name"].startswith(NAME):
        call("DELETE", f"/projects/{p['id']}")
base = {"project_name": NAME, "project_type": "Time & Material", "customer_name": "Acme Retail", "customer_contact_name": "Ravi Kumar",
        "customer_mobile": "9876543210", "start_date": d(-5), "end_date": d(40), "budget": 50000}
status, body = call("POST", "/projects/create", {**base, "project_manager_name": "Priya Shah"})
ok("project created", status == 201, body)
pid = body["data"]["id"]


def team():
    return {m["member_name"]: m["role"] for m in call("GET", f"/projects/{pid}/members")[1].get("detail") or []}


def managers():
    return sorted(n for n, r in team().items() if r == "Project Manager")


ok("new project: the manager is on the team as Project Manager", managers() == ["Priya Shah"], team())

call("PUT", f"/projects/{pid}", {**base, "project_manager_name": "Meena Iyer"})
ok("manager changed: only the new manager is Project Manager", managers() == ["Meena Iyer"], team())
ok("old manager without any work is removed from the team", "Priya Shah" not in team(), team())

call("POST", f"/projects/{pid}/members", {"member_name": "Anita Rao", "role": "Developer", "allocation_pct": 10})
call("POST", "/tasks/create", {"project_id": pid, "title": "Meena's task", "assignee_name": "Meena Iyer"})
call("PUT", f"/projects/{pid}", {**base, "project_manager_name": "Anita Rao"})
ok("existing member made manager gets the Project Manager role", managers() == ["Anita Rao"], team())
ok("old manager with a task stays on the team as Other", team().get("Meena Iyer") == "Other", team())

call("DELETE", f"/projects/{pid}")
print("\nALL PASSED" if fails == 0 else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
