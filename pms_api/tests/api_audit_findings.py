"""Go-live audit checks (3 Oct 2026), kept as a regression test. A check PASSES when the app is safe;
a FAIL means the finding is real. Needs the demo role users and the API on port 8000.
Run from backend/pms_api:  venv\\Scripts\\python tests\\api_audit_findings.py
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

from app.core.config import settings  # noqa: E402

B = "http://localhost:8000/api"
USERS = {"admin": (1, "Dev User"), "director": (9, "Rohan Verma"), "pm": (3, "Priya Sharma"), "lead": (4, "Arjun Mehta"),
         "member": (5, "Anita Rao"), "finance": (6, "Kiran Iyer"), "resource": (7, "Meena Das"), "client": (8, "Ravi Kumar")}
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


results = []


def ok(code, name, safe, extra=""):
    results.append((code, name, bool(safe)))
    print(("PASS " if safe else "FAIL ") + f"[{code}] {name}" + ("" if safe else f"  {str(extra)[:240]}"))


today = date.today()
d = lambda n: (today + timedelta(days=n)).isoformat()  # noqa: E731
stamp = str(int(time.time()))[-6:]
created = []
FIELDS = ("project_name", "project_type", "customer_name", "customer_contact_name", "customer_mobile", "start_date", "end_date", "budget",
          "project_manager_name", "project_manager_id")


def project(who, name, budget, ptype="Fixed Price", pm_id=3, pm_name="Priya Sharma"):
    body = {"project_name": f"Zz Findings {name} {stamp}", "project_type": ptype, "customer_name": "Acme Retail", "customer_contact_name": "Ravi Kumar",
            "customer_mobile": "9876543210", "start_date": d(-14), "end_date": d(60), "budget": budget, "project_manager_name": pm_name,
            "project_manager_id": pm_id}
    s, r = call(who, "POST", "/projects/create", body)
    created.append(r["data"]["id"])
    return r["data"]


try:
    # F1 - an Internal project is auto-approved, then switched to a billable type
    p = project("pm", "Internal Switch", 50000000, ptype="Internal")
    call("pm", "POST", f"/projects/{p['id']}/status", {"status": "Pending Approval"})
    s, r = call("pm", "PUT", f"/projects/{p['id']}", {**{k: p[k] for k in FIELDS}, "project_type": "Fixed Price"})
    ok("F1", "an approved Internal project cannot become billable without approval", s == 409, (s, r.get("detail")))

    # F2 - a PM on another manager's team makes themselves the manager
    other = project("director", "Other PM", 50000, pm_id=9, pm_name="Rohan Verma")
    call("admin", "POST", f"/projects/{other['id']}/members", {"member_name": "Priya Sharma", "user_id": 3, "role": "Other", "allocation_pct": 5})
    s, r = call("pm", "PUT", f"/projects/{other['id']}", {**{k: other[k] for k in FIELDS}, "project_manager_id": 3, "project_manager_name": "Priya Sharma"})
    ok("F2", "a PM who is only a team member cannot take over the project", s in (403, 409), (s, r.get("detail")))
    s, r = call("pm", "DELETE", f"/projects/{other['id']}")
    ok("F2", "…nor delete it", s in (403, 409), (s, r.get("detail")))
    if s == 200:
        created.remove(other["id"])

    # set-up: an Active project with Anita's approved hours
    a = project("pm", "Rates", 300000)
    call("pm", "POST", f"/projects/{a['id']}/status", {"status": "Pending Approval"})
    call("director", "POST", f"/projects/{a['id']}/status", {"status": "Approved"})
    call("pm", "POST", f"/projects/{a['id']}/status", {"status": "Active"})
    s, mem = call("pm", "POST", f"/projects/{a['id']}/members", {"member_name": "Anita Rao", "user_id": 5, "role": "Designer", "allocation_pct": 0, "hourly_rate": 700})
    call("pm", "POST", f"/projects/{a['id']}/members", {"member_name": "Arjun Mehta", "user_id": 4, "role": "Team Lead", "allocation_pct": 0, "hourly_rate": 900})
    s, t = call("pm", "POST", "/tasks/create", {"project_id": a["id"], "title": "Rates task", "assignee_id": 5, "assignee_name": "Anita Rao"})
    work_day = today - timedelta(days=today.weekday() + 7) + timedelta(days=1)
    call("member", "POST", "/timesheets/entries", {"task_id": t["data"]["id"], "work_date": work_day.isoformat(), "hours": 2})
    call("member", "POST", "/timesheets/submit", {"week_start": (work_day - timedelta(days=work_day.weekday())).isoformat()})

    # F3 - rates and costs in timesheet lists
    s, r = call("member", "GET", f"/timesheets/list?project_id={a['id']}")
    rows = r.get("detail", []) if s == 200 else []
    ok("F3", "a Member's timesheet list hides pay rates and costs", not any(x.get("hourly_rate") or x.get("cost") for x in rows), rows[:1])
    s, r = call("lead", "GET", "/timesheets/approvals")
    leaked = [e for g in (r.get("detail") or []) for e in g["entries"] if e.get("hourly_rate") or e.get("cost")] if s == 200 else []
    ok("F3", "a Team Lead's approval list hides pay rates and costs", not leaked, leaked[:1])

    # F4 - money on the dashboard and in reports
    s, r = call("member", "GET", "/dashboard/overview")
    dd = r.get("detail", {})
    money = [dd.get("budgetActual"), dd.get("billing")] + [x.get(k) for x in dd.get("projects", []) for k in ("budgetActual", "margin", "billed")]
    ok("F4", "a Member's dashboard has no budget/billing money", all(v is None for v in money), money[:4])
    s, r = call("lead", "GET", "/reports/budget")
    ok("F4", "a Team Lead cannot run the Budget report", s == 403, s)
    s, r = call("resource", "GET", "/reports/billing")
    ok("F4", "a Resource Manager cannot run the Billing report", s == 403, s)

    # F6 - Resource Manager edits a member and the rate is wiped
    s, r = call("resource", "PUT", f"/projects/{a['id']}/members/{mem['data']['id']}",
                {"member_name": "Anita Rao", "user_id": 5, "role": "Designer", "allocation_pct": 0, "hourly_rate": None})
    s2, r2 = call("pm", "GET", f"/projects/{a['id']}/members")
    rate = next((m["hourly_rate"] for m in r2["detail"] if m["user_id"] == 5), None)
    ok("F6", "a Resource Manager's edit keeps the pay rate", rate == 700, (s, rate))

    # F7 - utilization of a project outside the caller's scope
    hidden = project("director", "Hidden", 50000, pm_id=9, pm_name="Rohan Verma")
    s, r = call("lead", "GET", f"/resources/utilization?project_id={hidden['id']}")
    ok("F7", "a Team Lead cannot read utilization of a project they are not on", s in (403, 404) or "Zz Findings Hidden" not in json.dumps(r), s)

    # F9 - change requests: editing someone else's, and big budget cuts
    s, cr = call("member", "POST", f"/projects/{a['id']}/change-requests", {"title": "Small add", "reason": "A small extra banner request", "change_type": "Cost", "cost_impact": 1000})
    s, r = call("lead", "PUT", f"/projects/{a['id']}/change-requests/{cr['data']['id']}",
                {"title": "Small add", "reason": "A small extra banner request", "change_type": "Cost", "cost_impact": 900000})
    ok("F9", "nobody can rewrite someone else's change request", s in (403, 409), (s, r.get("detail")))
    s, cut = call("member", "POST", f"/projects/{a['id']}/change-requests", {"title": "Big cut", "reason": "Client cancelled most of the scope", "change_type": "Cost", "cost_impact": -200000})
    s, r = call("pm", "POST", f"/projects/{a['id']}/change-requests/{cut['data']['id']}/approve", {})
    ok("F9", "a big budget cut (above the PM limit) needs a Director", s == 409, (s, r.get("detail")))

    # F13 - Time & Material invoice on a Fixed Price project
    s, r = call("finance", "POST", "/billing/invoices", {"project_id": a["id"], "invoice_type": "Time & Material", "period_from": d(-30), "period_to": d(0)})
    ok("F13", "a Fixed Price project cannot get a Time & Material invoice", s in (409, 422), (s, r.get("detail")))
    if s == 201:
        call("finance", "POST", f"/billing/invoices/{r['data']['id']}/status", {"action": "cancel"})

    # F17 - approval history of a project the caller cannot see
    s, r = call("member", "GET", f"/approvals/history?entity_type=project&entity_id={hidden['id']}")
    ok("F17", "a Member cannot read approval history of a project they are not on", s in (403, 404) or not r.get("detail"), r)

    # F10 - approved dates and approved projects
    s, r = call("pm", "PUT", f"/projects/{a['id']}", {**{k: a[k] for k in FIELDS}, "budget": 300000, "end_date": d(90)})
    ok("F10", "approved dates change only through a Change Request", s == 409, (s, r.get("detail")))
    s, r = call("pm", "DELETE", f"/projects/{a['id']}")
    ok("F10", "a PM cannot delete an approved project (close it instead)", s == 409, (s, r.get("detail")))

    # F11 - billing rate: used on Time & Material invoices, never shown to a Member
    tm = project("pm", "Bill Rate", 50000, ptype="Time & Material")
    call("pm", "POST", f"/projects/{tm['id']}/status", {"status": "Pending Approval"})
    call("pm", "POST", f"/projects/{tm['id']}/status", {"status": "Active"})
    call("pm", "POST", f"/projects/{tm['id']}/members", {"member_name": "Anita Rao", "user_id": 5, "role": "Designer", "allocation_pct": 0,
                                                          "hourly_rate": 600, "bill_rate": 1500})
    s, t2 = call("pm", "POST", "/tasks/create", {"project_id": tm["id"], "title": "Billable work", "assignee_id": 5, "assignee_name": "Anita Rao"})
    call("member", "POST", "/timesheets/entries", {"task_id": t2["data"]["id"], "work_date": work_day.isoformat(), "hours": 2})
    call("member", "POST", "/timesheets/submit", {"week_start": (work_day - timedelta(days=work_day.weekday())).isoformat()})
    s, q = call("pm", "GET", f"/timesheets/approvals?project_id={tm['id']}")
    call("admin", "POST", "/timesheets/approve", {"entry_ids": [e["id"] for g in q["detail"] for e in g["entries"]]})
    s, inv = call("finance", "POST", "/billing/invoices", {"project_id": tm["id"], "invoice_type": "Time & Material", "period_from": d(-30), "period_to": d(0)})
    line = (inv.get("data") or {}).get("lines", [{}])[0]
    ok("F11", "a Time & Material invoice uses the billing rate (2 h x Rs 1,500), not the pay rate", s == 201 and line.get("rate") == 1500, (s, line))
    s, r = call("member", "GET", f"/projects/{tm['id']}/members")
    ok("F11", "a Member sees neither pay nor billing rates", all(m.get("hourly_rate") is None and m.get("bill_rate") is None for m in r["detail"]), r["detail"][:1])

    # F12 - only the project's manager (or Director/Admin/Resource Manager) changes its team
    s, r = call("lead", "POST", f"/projects/{a['id']}/members", {"member_name": "Meena Das", "user_id": 7, "role": "Other", "allocation_pct": 5})
    ok("F12", "a Team Lead cannot change the team", s == 403, s)
    s, r = call("resource", "POST", f"/projects/{a['id']}/members", {"member_name": "Meena Das", "user_id": 7, "role": "Other", "allocation_pct": 5})
    ok("F12", "a Resource Manager can staff the project", s == 201, (s, r.get("detail")))

    # Audit flow finding - unknown project type
    s, r = call("pm", "POST", "/projects/create", {"project_name": f"Zz Findings Type {stamp}", "project_type": "Barter", "start_date": d(0),
                                                   "project_manager_name": "Priya Sharma", "customer_name": "Acme Retail", "customer_contact_name": "Ravi Kumar",
                                                   "customer_mobile": "9876543210"})
    ok("V1", "an unknown project type is refused", s == 422, s)
    if s == 201:
        created.append(r["data"]["id"])
finally:
    for pid in created:
        call("admin", "DELETE", f"/projects/{pid}")

failed = [r for r in results if not r[2]]
print(f"\n{len(results) - len(failed)} of {len(results)} safe; {len(failed)} confirmed problems: {', '.join(sorted({r[0] for r in failed}))}")
