"""API checks: Settings > Industry & Team Roles, starter templates and the project setup counts.
Restores the company's industry and roles at the end.
Run from backend/pms_api with the API on port 8000:  venv\\Scripts\\python tests\\api_industry.py
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
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
before = call("GET", "/settings")[1]["detail"]
ok("settings list the industries with their roles", len(before["industries"]) >= 6 and before["industry"] in [i["name"] for i in before["industries"]], before.get("industry"))
pid = None
template_id = None
try:
    print("\n[1] Industry and roles")
    construction = next(i for i in before["industries"] if i["name"] == "Construction")
    s, r = call("PUT", "/settings/industry", {"industry": "Construction", "member_roles": construction["roles"]})
    ok("switch to Construction", s == 200 and r["data"]["industry"] == "Construction", (s, r))
    ok("team role list follows the company", call("GET", "/team/meta")[1]["detail"]["roles"] == construction["roles"])
    s, r = call("PUT", "/settings/industry", {"industry": "Construction", "member_roles": ["Site Engineer", "Other"]})
    ok("Project Manager role cannot be removed", s == 422 and "Project Manager" in r["detail"], (s, r))
    s, r = call("PUT", "/settings/industry", {"industry": "Construction", "member_roles": ["Project Manager", "Site Engineer", "site engineer"]})
    ok("a role cannot be listed twice", s == 422 and "twice" in r["detail"], (s, r))
    # A company may type its own industry (2-60 characters); a nonsense one is refused.
    s, r = call("PUT", "/settings/industry", {"industry": "1", "member_roles": ["Project Manager", "Pilot"]})
    ok("an industry without letters is refused", s == 422, (s, r))
    s, r = call("PUT", "/settings/industry", {"industry": "Construction", "member_roles": ["Project Manager", "Site Engineer", "Other"]})

    print("\n[2] Members use the company's roles")
    name = "Industry Api Check"
    for p in call("GET", "/projects/options")[1].get("detail") or []:
        if p["project_name"].startswith(name):
            call("DELETE", f"/projects/{p['id']}")
    s, r = call("POST", "/projects/create", {"project_name": name, "project_type": "Fixed Price", "customer_name": "Acme Builders", "customer_contact_name": "Ravi Kumar",
                                             "customer_mobile": "9876543210", "start_date": d(0), "project_manager_name": "Priya Shah"})
    pid = r["data"]["id"]
    s, r = call("POST", f"/projects/{pid}/members", {"member_name": "Anil Rao", "role": "Site Engineer", "allocation_pct": 10})
    ok("a Construction role can be given", s == 201, (s, r))
    s, r = call("POST", f"/projects/{pid}/members", {"member_name": "Sunita Das", "role": "Developer", "allocation_pct": 10})
    ok("a role outside the company list is refused", s == 409 and "Settings" in r["detail"], (s, r))

    print("\n[3] Setup counts on Project Details")
    detail = call("GET", f"/projects/{pid}")[1]["detail"]
    ok("setup counts the team (manager + 1)", detail["setup"]["members"] == 2, detail.get("setup"))
    ok("setup lists what approval still needs", detail["setup"]["missing_for_approval"] == ["End Date", "Budget"], detail.get("setup"))
    ok("no milestones yet", detail["setup"]["milestones"] == 0, detail.get("setup"))

    print("\n[4] Starter template")
    for t in call("GET", "/templates")[1].get("detail") or []:
        if t["name"] == "Building Construction":
            call("DELETE", f"/templates/{t['id']}")
    s, r = call("POST", "/templates/starter?" + urllib.parse.urlencode({"industry": "Construction"}))
    ok("Construction starter template is added", s == 201 and r["data"]["name"] == "Building Construction", (s, r))
    template_id = r.get("data", {}).get("id")
    s, r = call("POST", "/templates/starter?" + urllib.parse.urlencode({"industry": "Construction"}))
    ok("the same starter cannot be added twice", s == 409, (s, r))
finally:
    if pid:
        call("DELETE", f"/projects/{pid}")
    if template_id:
        call("DELETE", f"/templates/{template_id}")
    call("PUT", "/settings/industry", {"industry": before["industry"], "member_roles": before["member_roles"]})
    after = call("GET", "/settings")[1]["detail"]
    ok("company industry and roles restored", after["industry"] == before["industry"] and after["member_roles"] == before["member_roles"])

print("\nALL PASSED" if fails == 0 else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
