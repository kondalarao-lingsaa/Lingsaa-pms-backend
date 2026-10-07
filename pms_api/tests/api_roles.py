"""API checks for roles, project visibility, approval rules and the client portal.
Needs the demo role users (scripts/seed_demo_roles.py) and the API on port 8000.
Run from backend/pms_api:  venv\\Scripts\\python tests\\api_roles.py
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

from app.core.access import ROUTE_POLICY  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.main import app  # noqa: E402

B = "http://localhost:8000/api"
USERS = {"admin": (1, "dev.user"), "director": (9, "rohan.verma"), "pm": (3, "priya.sharma"), "lead": (4, "arjun.mehta"),
         "member": (5, "anita.rao"), "finance": (6, "kiran.iyer"), "resource": (7, "meena.das"), "client": (8, "ravi.kumar")}
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


# 1. every route has an access rule
missing = []
for r in app.routes:
    path = getattr(r, "path", "")
    if not path.startswith("/api/") or path == "/api/health":
        continue
    for m in r.methods - {"HEAD", "OPTIONS"}:
        if (m, path[4:]) not in ROUTE_POLICY:
            missing.append(f"{m} {path}")
ok("every API route has an access rule", not missing, missing)

# 2. each user gets their role
expected = {"admin": "admin", "director": "director", "pm": "project_manager", "lead": "team_lead", "member": "member",
            "finance": "finance", "resource": "resource_manager", "client": "client"}
roles_seen = {k: call(k, "GET", "/me")[1]["detail"]["role"] for k in USERS}
ok("/me returns each demo user's role", roles_seen == expected, roles_seen)

today = date.today()
stamp = str(int(time.time()))[-6:]
created = []


def new_project(who, budget, name, ptype="Fixed Price", customer="Acme Retail"):
    body = {"project_name": f"Zz Roles {name} {stamp}", "project_type": ptype, "customer_name": customer, "customer_contact_name": "Ravi Kumar",
            "customer_mobile": "9876543210", "start_date": today.isoformat(), "end_date": (today + timedelta(days=60)).isoformat(),
            "budget": budget, "project_manager_name": "Priya Sharma", "project_manager_id": 3}
    s, r = call(who, "POST", "/projects/create", body)
    if s == 201:
        created.append(r["data"]["id"])
    return s, r


try:
    # 3. module rights
    s, _ = new_project("member", 50000, "Member Try")
    ok("Member cannot create a project (403)", s == 403, s)
    s, _ = new_project("finance", 50000, "Finance Try")
    ok("Finance cannot create a project (403)", s == 403, s)
    s, _ = call("client", "GET", "/projects/list")
    ok("Client cannot open the internal project list (403)", s == 403, s)
    s, _ = call("member", "GET", "/settings/users")
    ok("Member cannot see Users & Roles (403)", s == 403, s)

    # 4. approval rules
    s, small = new_project("pm", 50000, "Small")
    ok("PM creates a project", s == 201, small)
    pid_small = small["data"]["id"]
    s, r = call("pm", "POST", f"/projects/{pid_small}/status", {"status": "Pending Approval"})
    ok("₹50,000 project is approved on submit (under the PM limit)", s == 200 and r["data"]["status"] == "Approved", r)

    s, mid = new_project("pm", 500000, "Mid")
    pid_mid = mid["data"]["id"]
    s, r = call("pm", "POST", f"/projects/{pid_mid}/status", {"status": "Pending Approval"})
    ok("₹5,00,000 project waits for level 1", s == 200 and r["data"]["status"] == "Pending Approval" and r["data"]["approval_level"] == 1, r)
    s, r = call("pm", "POST", f"/projects/{pid_mid}/status", {"status": "Approved"})
    ok("PM cannot approve it (needs Director or Admin)", s == 409, r)
    s, r = call("pm", "PUT", f"/projects/{pid_mid}", {**{k: v for k, v in mid["data"].items() if k in (
        "project_name", "project_type", "customer_name", "customer_contact_name", "customer_mobile", "start_date", "end_date",
        "project_manager_name", "project_manager_id")}, "budget": 40000})
    ok("A project waiting for approval cannot be edited", s == 409, r)
    s, inbox = call("director", "GET", "/approvals")
    ok("Director's approvals inbox lists it", s == 200 and any(i["kind"] == "project" and i["id"] == pid_mid for i in inbox["detail"]["items"]), inbox)
    s, r = call("director", "POST", f"/projects/{pid_mid}/status", {"status": "Draft"})
    ok("Approver must give a reason to send back", s == 409, r)
    s, r = call("director", "POST", f"/projects/{pid_mid}/status", {"status": "Approved", "remarks": "Fits the plan"})
    ok("Director approves it", s == 200 and r["data"]["status"] == "Approved" and r["data"]["approved_by_name"], r)
    s, r = call("pm", "GET", f"/projects/{pid_mid}")
    hist = [h["decision"] for h in r["detail"]["approval"]["history"]]
    ok("Approval history is recorded", hist[:1] == ["Submitted"] and "Approved" in hist, hist)

    s, big = new_project("pm", 2000000, "Big")
    pid_big = big["data"]["id"]
    call("pm", "POST", f"/projects/{pid_big}/status", {"status": "Pending Approval"})
    s, r = call("director", "POST", f"/projects/{pid_big}/status", {"status": "Approved"})
    ok("₹20,00,000 project: Director approves level 1, it waits for level 2",
       s == 200 and r["data"]["status"] == "Pending Approval" and r["data"]["approval_level"] == 2, r)
    s, r = call("director", "POST", f"/projects/{pid_big}/status", {"status": "Approved"})
    ok("The same Director cannot approve level 2", s == 409, r)
    s, r = call("admin", "POST", f"/projects/{pid_big}/status", {"status": "Approved"})
    ok("Admin approves level 2 and the project is Approved", s == 200 and r["data"]["status"] == "Approved", r)

    s, intern = new_project("pm", 900000, "Internal", ptype="Internal")
    s, r = call("pm", "POST", f"/projects/{intern['data']['id']}/status", {"status": "Pending Approval"})
    ok("Internal project needs no approval", r["data"]["status"] == "Approved", r)

    s, own = new_project("director", 300000, "Director Own")
    s, r = call("director", "POST", f"/projects/{own['data']['id']}/status", {"status": "Pending Approval"})
    ok("A Director's own ₹3,00,000 project is approved with their authority", r["data"]["status"] == "Approved", r)

    # 5. baseline budget is locked after approval
    p = mid["data"]
    body = {k: p[k] for k in ("project_name", "project_type", "customer_name", "customer_contact_name", "customer_mobile", "start_date", "end_date",
                              "project_manager_name", "project_manager_id")}
    s, r = call("pm", "PUT", f"/projects/{pid_mid}", {**body, "budget": 600000})
    ok("Approved budget cannot be edited directly (Change Request instead)", s == 409, r)

    # 6. visibility and rates
    s, r = call("pm", "POST", f"/projects/{pid_mid}/members", {"member_name": "Anita Rao", "user_id": 5, "role": "Designer", "allocation_pct": 0,
                                                               "hourly_rate": 600})
    ok("PM adds Anita (Member) to the team", s == 201, r)
    s, r = call("member", "GET", "/projects/list?page_size=100")
    ids = {x["id"] for x in r["detail"]}
    ok("Member sees the project they are on, not the others", pid_mid in ids and pid_big not in ids, ids)
    s, r = call("member", "GET", f"/projects/{pid_big}")
    ok("Member gets 404 for a project they are not on", s == 404, s)
    s, r = call("member", "GET", f"/projects/{pid_mid}/members")
    ok("Member does not see pay rates", s == 200 and all(m["hourly_rate"] is None for m in r["detail"]), r)
    s, r = call("pm", "GET", f"/projects/{pid_mid}/members")
    ok("PM sees pay rates", any(m["hourly_rate"] for m in r["detail"]), r)
    s, r = call("member", "GET", f"/projects/{pid_mid}/budget")
    ok("Member cannot see the budget (403)", s == 403, s)

    # 7. change request authority
    call("pm", "POST", f"/projects/{pid_mid}/status", {"status": "Active"})
    s, small_cr = call("member", "POST", f"/projects/{pid_mid}/change-requests",
                       {"title": "Extra banner", "reason": "Client asked for one more banner", "change_type": "Cost", "cost_impact": 5000})
    ok("Member raises a ₹5,000 change request", s == 201, small_cr)
    s, r = call("pm", "POST", f"/projects/{pid_mid}/change-requests/{small_cr['data']['id']}/approve", {})
    ok("PM approves a change within the PM limit", s == 200, r)
    s, big_cr = call("member", "POST", f"/projects/{pid_mid}/change-requests",
                     {"title": "New module", "reason": "Client wants a loyalty module added", "change_type": "Cost", "cost_impact": 200000})
    s, r = call("pm", "POST", f"/projects/{pid_mid}/change-requests/{big_cr['data']['id']}/approve", {})
    ok("PM cannot approve a ₹2,00,000 change (needs Director)", s == 409, r)
    s, r = call("director", "POST", f"/projects/{pid_mid}/change-requests/{big_cr['data']['id']}/approve", {})
    ok("Director approves it", s == 200, r)

    # 8. client portal
    s, ms = call("pm", "POST", f"/projects/{pid_mid}/milestones", {"name": "Design Sign-off", "amount": 50000})
    mid_ms = ms["data"]["id"]
    call("pm", "POST", f"/projects/{pid_mid}/milestones/{mid_ms}/deliverables", {"name": "Home page design"})
    s, r = call("pm", "GET", f"/projects/{pid_mid}/milestones")
    d_id = r["detail"][0]["deliverables"][0]["id"]
    call("pm", "POST", f"/projects/{pid_mid}/milestones/{mid_ms}/deliverables/{d_id}/done", {"is_done": True})
    call("pm", "POST", f"/projects/{pid_mid}/milestones/{mid_ms}/status", {"status": "In Progress"})
    s, r = call("pm", "POST", f"/projects/{pid_mid}/milestones/{mid_ms}/status", {"status": "Ready for Review"})
    ok("PM sends the milestone for review", s == 200, r)
    s, r = call("client", "GET", "/portal/projects")
    portal_ids = {p["id"] for p in r["detail"]["projects"]}
    ok("Client portal lists the client's approved project", pid_mid in portal_ids, portal_ids)
    s, r = call("client", "GET", f"/portal/projects/{pid_mid}")
    ok("Client sees milestones but no rates or hours", s == 200 and r["detail"]["milestones"] and "hourly_rate" not in json.dumps(r), r)
    s, r = call("client", "POST", f"/portal/projects/{pid_mid}/milestones/{mid_ms}/decision", {"decision": "accept", "feedback": "Looks good"})
    ok("Client accepts the milestone in the portal", s == 200, r)
    s, r = call("pm", "GET", f"/projects/{pid_mid}/milestones")
    ok("Milestone is Accepted", r["detail"][0]["status"] == "Accepted", r["detail"][0]["status"])
    s, r = call("client", "POST", f"/portal/projects/{pid_mid}/messages", {"body": "When can we see the next design?"})
    ok("Client sends a message to the team", s == 201, r)
    s, r = call("pm", "GET", f"/projects/{pid_mid}/client-messages")
    ok("PM sees the client's message", s == 200 and any(m["from_client"] for m in r["detail"]), r)
    s, other = new_project("pm", 50000, "Other Client", customer="Sahyadri Bank")
    call("pm", "POST", f"/projects/{other['data']['id']}/status", {"status": "Pending Approval"})
    s, r = call("client", "GET", f"/portal/projects/{other['data']['id']}")
    ok("Client cannot open another client's project (404)", s == 404, s)
    s, draft = new_project("pm", 50000, "Client Draft")
    s, r = call("client", "GET", f"/portal/projects/{draft['data']['id']}")
    ok("Client cannot see their company's project while it is a Draft (404)", s == 404, s)
    s, r = call("member", "POST", f"/projects/{pid_mid}/milestones/{mid_ms}/status", {"status": "Accepted"})
    ok("Member cannot accept a milestone (403)", s == 403, s)
    # A Director accepts for the client ("approve") but has no "edit" for other moves.
    s, ms2 = call("pm", "POST", f"/projects/{pid_mid}/milestones", {"name": "Build Sign-off", "amount": 25000})
    mid_ms2 = ms2["data"]["id"]
    call("pm", "POST", f"/projects/{pid_mid}/milestones/{mid_ms2}/deliverables", {"name": "Build hand-over"})
    s, r = call("pm", "GET", f"/projects/{pid_mid}/milestones")
    d2 = next(m for m in r["detail"] if m["id"] == mid_ms2)["deliverables"][0]["id"]
    call("pm", "POST", f"/projects/{pid_mid}/milestones/{mid_ms2}/deliverables/{d2}/done", {"is_done": True})
    call("pm", "POST", f"/projects/{pid_mid}/milestones/{mid_ms2}/status", {"status": "In Progress"})
    s, r = call("pm", "POST", f"/projects/{pid_mid}/milestones/{mid_ms2}/status", {"status": "Ready for Review"})
    ok("PM sends a second milestone for review", s == 200, r)
    s, r = call("director", "POST", f"/projects/{pid_mid}/milestones/{mid_ms2}/status", {"status": "In Progress"})
    ok("Director cannot move a milestone back to In Progress (403)", s == 403, s)
    s, r = call("director", "POST", f"/projects/{pid_mid}/milestones/{mid_ms2}/status", {"status": "Accepted", "feedback": "Accepted on the call"})
    ok("Director accepts the milestone for the client", s == 200 and r["data"]["status"] == "Accepted", r)

    # 9. permission matrix (Settings > Roles & Permissions)
    s, r = call("member", "GET", "/billing/invoices")
    ok("By default a Member cannot open Billing", s == 403, s)
    s, r = call("admin", "PUT", "/settings/permissions", {"role": "member", "permissions": {"billing": ["view"], "settings": ["view", "edit"]}})
    ok("Admin gives Members Billing (view)", s == 200 and r["data"]["matrix"]["member"].get("billing") == ["view"], r)
    ok("…but Settings stays Admin-only (locked)", "settings" not in r["data"]["matrix"]["member"], r["data"]["matrix"]["member"])
    s, r = call("member", "GET", "/billing/invoices")
    ok("The Member can now open Billing", s == 200, s)
    s, me = call("member", "GET", "/me")
    ok("/me shows the company's matrix", me["detail"]["permissions"].get("billing") == ["view"], me["detail"]["permissions"])
    s, r = call("pm", "PUT", "/settings/permissions", {"role": "member", "permissions": {"billing": ["view", "add"]}})
    ok("A Project Manager cannot change permissions (403)", s == 403, s)
    s, r = call("admin", "PUT", "/settings/permissions", {"role": "admin", "permissions": {"billing": []}})
    ok("Admin's own rights cannot be reduced", s == 422, s)
    s, r = call("admin", "PUT", "/settings/permissions", {"role": "member", "permissions": None})
    s2, _ = call("member", "GET", "/billing/invoices")
    ok("Reset to recommended removes it again", s == 200 and s2 == 403, (s, s2))
finally:
    call("admin", "PUT", "/settings/permissions", {"role": "member", "permissions": None})
    for pid in created:
        call("admin", "DELETE", f"/projects/{pid}")

print("\nALL CHECKS PASSED" if not fails else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
