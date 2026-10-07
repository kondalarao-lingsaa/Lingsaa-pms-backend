"""Regression checks for the fixes of 5 Oct 2026 (Templates, Timesheets, Expenses, Risks & Issues, Billing review).
Each check PASSES when the fix holds. Needs the demo role users (scripts/seed_demo_roles.py) and the API on port 8000.
Run from backend/pms_api:  set PYTHONIOENCODING=utf-8 && venv\\Scripts\\python tests\\api_fixes_20261005.py
Everything it creates is named "Zz Fixes ..." and deleted at the end.
"""
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

API = "http://127.0.0.1:8000/api"
USERS = {"admin": "dev.user@lingsaa.com", "admin2": "qa.manager@lingsaa.com", "director": "rohan.verma@lingsaa.com",
         "pm": "priya.sharma@lingsaa.com", "lead": "arjun.mehta@lingsaa.com", "member": "anita.rao@lingsaa.com",
         "finance": "kiran.iyer@lingsaa.com"}
results = []


def raw(method, path, body=None, token=None):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


TOK = {}
for who, email in USERS.items():
    s, r = raw("POST", "/auth/login", {"email": email, "password": "Demo@123"})
    TOK[who] = (r.get("detail") or {}).get("token") or (r.get("detail") or {}).get("access_token")
    if not TOK[who]:
        sys.exit(f"cannot sign in as {email}: {s} {r}")


def call(who, method, path, body=None):
    return raw(method, path, body, TOK[who])


def ok(area, name, cond, extra=""):
    results.append((area, name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + f"[{area}] {name}" + ("" if cond else f"  {str(extra)[:300]}"))


today = date.today()
d = lambda n: (today + timedelta(days=n)).isoformat()  # noqa: E731
stamp = str(int(time.time()))[-6:]
made_projects, made_templates = [], []


def project(name, ptype="Fixed Price", budget=500000, activate=True):
    s, p = call("pm", "POST", "/projects/create", {
        "project_name": f"Zz Fixes {name} {stamp}", "project_type": ptype, "customer_name": "Acme Retail", "customer_contact_name": "Ravi Kumar",
        "customer_mobile": "9876543210", "start_date": d(-30), "end_date": d(60), "budget": budget, "project_manager_name": "Priya Sharma",
        "project_manager_id": 3})
    pid = p["data"]["id"]
    made_projects.append(pid)
    if activate:
        call("pm", "POST", f"/projects/{pid}/status", {"status": "Pending Approval"})
        call("director", "POST", f"/projects/{pid}/status", {"status": "Approved"})
        call("pm", "POST", f"/projects/{pid}/status", {"status": "Active"})
    # 0%: real demo projects may already book all of Anita's time (no one can go above 100% in total).
    call("pm", "POST", f"/projects/{pid}/members", {"member_name": "Anita Rao", "user_id": 5, "role": "Designer", "allocation_pct": 0,
                                                     "hourly_rate": 500})
    return pid


def approved_hours(pid, hours=4):
    """A task with `hours` approved hours of Anita on last week's Tuesday."""
    s, t = call("pm", "POST", "/tasks/create", {"project_id": pid, "title": "Fix work", "assignee_id": 5, "assignee_name": "Anita Rao"})
    tid = t["data"]["id"]
    day = today - timedelta(days=today.weekday() + 7) + timedelta(days=1)
    call("member", "POST", "/timesheets/entries", {"task_id": tid, "work_date": day.isoformat(), "hours": hours})
    call("member", "POST", "/timesheets/submit", {"week_start": (day - timedelta(days=day.weekday())).isoformat()})
    s, q = call("pm", "GET", "/timesheets/approvals")
    ids = [e["id"] for g in q.get("detail", []) for e in g["entries"] if e["task_id"] == tid]
    call("pm", "POST", "/timesheets/approve", {"entry_ids": ids})
    return tid, ids


def cr(who, pid, cost, title="Extra work"):
    return call(who, "POST", f"/projects/{pid}/change-requests", {"title": title, "reason": "Client asked for more pages", "change_type": "Cost",
                                                                 "cost_impact": cost})


try:
    # ------------------------------------------------------------------ Billing (B1)
    A = "Billing"
    fp = project("Fixed")
    approved_hours(fp)
    s, r = call("finance", "POST", "/billing/invoices", {"project_id": fp, "invoice_type": "Time & Material", "period_from": d(-30), "period_to": d(0)})
    ok(A, "B1 Fixed Price hours are never billed by period (no double billing)", s == 409 and "Fixed Price" in r.get("detail", ""), (s, r.get("detail")))
    s, b = call("finance", "GET", f"/billing/billable?project_id={fp}")
    ok(A, "billable summary of a Fixed Price project shows no hours to bill",
       s == 200 and b["detail"]["unbilled_hours"] == 0 and b["detail"].get("bills_hours") is False, (s, b.get("detail")))
    tm = project("TandM", ptype="Time & Material")
    approved_hours(tm)
    s, r = call("finance", "POST", "/billing/invoices", {"project_id": tm, "invoice_type": "Time & Material", "period_from": d(-30), "period_to": d(0)})
    ok(A, "Time & Material hours still bill normally", s == 201, (s, r.get("detail")))
    tm_invoice = (r.get("data") or {}).get("id")

    # ------------------------------------------------------------------ Tasks with hours (B5)
    A = "Timesheets"
    tid, _ = approved_hours(fp, 2)
    s, r = call("pm", "DELETE", f"/tasks/{tid}")
    ok(A, "B5 a task with approved hours cannot be deleted", s == 409 and "hours" in r.get("detail", ""), (s, r.get("detail")))
    s, r = call("member", "GET", f"/timesheets/list?project_id={fp}")
    ok(A, "a Member lists only their own hours", s == 200 and all(e.get("member_name") == "Anita Rao" for e in r.get("detail", [])), s)
    s, r = call("pm", "GET", "/timesheets/list?status=Bogus")
    ok(A, "an unknown status filter is refused, not an empty list", s == 422, s)

    # ------------------------------------------------------------------ Change requests (B2, B3, locks, notifications)
    A = "Change requests"
    small = project("Small", budget=100000)
    first = cr("member", small, 90000)[1]["data"]
    s, r = call("pm", "POST", f"/projects/{small}/change-requests/{first['id']}/approve", {})
    ok(A, "PM approves a change within the PM limit", s == 200, (s, r.get("detail")))
    second = cr("member", small, 90000)[1]["data"]
    s, r = call("pm", "POST", f"/projects/{small}/change-requests/{second['id']}/approve", {})
    ok(A, "B2 changes adding up past the PM limit need a Director", s == 409 and "Director" in r.get("detail", ""), (s, r.get("detail")))
    s, r = call("director", "POST", f"/projects/{small}/change-requests/{second['id']}/approve", {})
    ok(A, "the Director approves it", s == 200, (s, r.get("detail")))
    pending = project("Pending", activate=False)
    call("pm", "POST", f"/projects/{pending}/status", {"status": "Pending Approval"})
    s, r = cr("member", pending, 5000)
    ok(A, "B3 no change requests while the project waits for approval", s == 409, (s, r.get("detail")))
    s, before = call("pm", "GET", f"/projects/{small}")
    many = [cr("member", small, 1000, f"Parallel {i}")[1]["data"]["id"] for i in range(4)]
    outs = []
    threads = [threading.Thread(target=lambda c: outs.append(call("director", "POST", f"/projects/{small}/change-requests/{c}/approve", {})[0]), args=(c,))
               for c in many]
    [t.start() for t in threads]
    [t.join() for t in threads]
    s, after = call("pm", "GET", f"/projects/{small}")
    ok(A, "four changes approved at the same moment all count (+4,000)", round(after["detail"]["budget"] - before["detail"]["budget"]) == 4000,
       (outs, before["detail"]["budget"], after["detail"]["budget"]))
    one = cr("member", small, 1000, "Twice")[1]["data"]["id"]
    outs = []
    threads = [threading.Thread(target=lambda: outs.append(call("director", "POST", f"/projects/{small}/change-requests/{one}/approve", {})[0])) for _ in range(3)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    ok(A, "one change approved three times at once is applied once", outs.count(200) == 1, outs)
    big = cr("member", small, 200000, "Notify me")[1]["data"]
    s, n = call("director", "GET", "/notifications?unread_only=true")
    ok(A, "the Director is notified of a change needing their decision", any(big["cr_key"] in x["title"] for x in n.get("detail", [])), s)
    call("director", "POST", f"/projects/{small}/change-requests/{big['id']}/reject", {"note": "Too expensive for now"})
    s, n = call("member", "GET", "/notifications?unread_only=true")
    ok(A, "the requester is notified of the decision", any(big["cr_key"] in x["title"] for x in n.get("detail", [])), s)
    mine = cr("member", small, 2000, "Admin edit")[1]["data"]
    s, r = call("admin", "PUT", f"/projects/{small}/change-requests/{mine['id']}",
                {"title": "Admin edit", "reason": "Client asked for more pages", "change_type": "Cost", "cost_impact": 900000})
    ok(A, "an Admin cannot rewrite someone else's change request", s == 409, (s, r.get("detail")))

    # ------------------------------------------------------------------ Issues
    A = "Issues"
    s, iss = call("pm", "POST", f"/projects/{small}/issues", {"title": "Login page broken", "severity": "High"})
    iid = iss["data"]["id"]
    outs = []
    threads = [threading.Thread(target=lambda: outs.append(call("pm", "POST", f"/projects/{small}/issues/{iid}/task")[0])) for _ in range(3)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    ok(A, "three 'make fix task' clicks at once make one task", outs.count(200) + outs.count(201) == 1, outs)
    s, r = call("pm", "DELETE", f"/projects/{small}/issues/{iid}")
    ok(A, "an issue with an open fix task cannot be deleted", s == 409, (s, r.get("detail")))

    # ------------------------------------------------------------------ Search (B6)
    A = "Search"
    s, r = call("member", "GET", "/search?q=INV")
    ok(A, "B6 a Member's search shows no invoices", s == 200 and not any(g["kind"] == "Invoices" for g in r.get("detail", [])), s)

    # ------------------------------------------------------------------ Client rename after an invoice (N3)
    A = "Projects"
    if tm_invoice:
        call("finance", "POST", f"/billing/invoices/{tm_invoice}/status", {"action": "issue"})
        s, p = call("pm", "GET", f"/projects/{tm}")
        body = {k: p["detail"][k] for k in ("project_name", "project_type", "customer_contact_name", "customer_mobile", "start_date", "end_date",
                                            "budget", "project_manager_name", "project_manager_id")}
        s, r = call("pm", "PUT", f"/projects/{tm}", {**body, "customer_name": "Other Client Ltd"})
        ok(A, "N3 the client of a project with an issued invoice cannot be renamed", s == 409, (s, r.get("detail")))

    # ------------------------------------------------------------------ Close checklist (K2, N1)
    A = "Close"
    s, e = call("member", "POST", "/expenses", {"project_id": fp, "category": "Travel", "description": "Client visit", "expense_date": d(-2),
                                                "amount": 2000, "submit": True})
    s, r = call("pm", "POST", f"/projects/{fp}/status", {"status": "Closed"})
    ok(A, "a project with an expense waiting for approval cannot be closed", s == 409 and "expense" in r.get("detail", ""), (s, r.get("detail")))

    # ------------------------------------------------------------------ Team members are linked to their login
    A = "Team login"
    s, meta = call("pm", "GET", "/team/meta")
    people = meta.get("detail", {}).get("people", [])
    ok(A, "Add Member offers the company's login users, never Client users",
       any(p["name"] == "Arjun Mehta" for p in people) and not any(p["role"] == "client" for p in people), [p["name"] for p in people])
    lt = project("Link", activate=True)
    s, r = call("pm", "POST", f"/projects/{lt}/members", {"member_name": "Arjun Mehata", "email": "ARJUN.MEHTA@lingsaa.com", "role": "Team Lead",
                                                          "allocation_pct": 0})
    ok(A, "typed name + login email links the login and fixes the name", s == 201 and r["data"]["user_id"] == 4 and r["data"]["member_name"] == "Arjun Mehta",
       (s, r.get("data") or r.get("detail")))
    s, r = call("pm", "POST", f"/projects/{lt}/members", {"member_name": "meena das", "role": "Developer", "allocation_pct": 1})
    ok(A, "the exact name of a login user links that login", s == 201 and r["data"]["user_id"] == 7, (s, r.get("data") or r.get("detail")))
    s, r = call("pm", "POST", f"/projects/{lt}/members", {"member_name": "Outside Freelancer", "role": "Developer", "allocation_pct": 1})
    ok(A, "someone without a login stays unlinked", s == 201 and r["data"]["user_id"] is None, (s, r.get("data") or r.get("detail")))
    s, r = call("pm", "POST", f"/projects/{lt}/members", {"member_name": "Ravi Kumar", "user_id": 8, "role": "Developer", "allocation_pct": 1})
    ok(A, "a Client login cannot be put on the team", s == 409, (s, r.get("detail")))
    s, r = call("lead", "GET", f"/projects/{lt}")
    ok(A, "the linked Team Lead can open the project", s == 200, s)
    s, r = call("director", "POST", "/projects/create", {"project_name": f"Zz Fixes Pm Link {stamp}", "project_type": "Internal", "start_date": d(0),
                                                        "project_manager_name": "priya sharma"})
    pm_pid = (r.get("data") or {}).get("id")
    made_projects.append(pm_pid)
    ok(A, "a project manager typed by name is linked to their login", s == 201 and r["data"]["project_manager_id"] == 3, (s, r.get("data") or r.get("detail")))
    s, r = call("pm", "GET", f"/projects/{pm_pid}")
    ok(A, "that manager can open the project", s == 200, s)

    # ------------------------------------------------------------------ Reopen a Closed project
    A = "Reopen"
    ro = project("Reopen")
    s, r = call("pm", "POST", f"/projects/{ro}/status", {"status": "Closed"})
    ok(A, "PM closes a project with nothing pending", s == 200 and r["data"]["status"] == "Closed", (s, r.get("detail")))
    s, r = call("pm", "POST", f"/projects/{ro}/reopen", {"reason": "Closed by mistake, work remains"})
    ok(A, "a Project Manager cannot reopen it", s == 403, (s, r.get("detail")))
    s, r = call("director", "POST", f"/projects/{ro}/reopen", {"reason": "oops"})
    ok(A, "reopening needs a reason of 10+ characters", s == 422, s)
    s, r = call("director", "POST", f"/projects/{ro}/reopen", {"reason": "Closed by mistake, two tasks remain"})
    ok(A, "the Director reopens it: Active again", s == 200 and r["data"]["status"] == "Active", (s, r.get("detail")))
    s, h = call("pm", "GET", f"/projects/{ro}/approvals")
    ok(A, "the reopening and its reason are in the approval history", "Closed by mistake, two tasks remain" in json.dumps(h), s)
    s, r = call("director", "POST", f"/projects/{ro}/reopen", {"reason": "Closed by mistake, two tasks remain"})
    ok(A, "an Active project cannot be reopened", s == 409, s)

    # ------------------------------------------------------------------ Templates
    A = "Templates"
    base = {"name": f"Zz Fixes Plan {stamp}", "duration_days": 10}
    s, r = call("pm", "POST", "/templates", {**base, "project_type": "Barter", "milestones": [{"name": "Done", "due_offset": 5}]})
    ok(A, "F6 an unknown project type is refused when the template is saved", s == 422, s)
    s, r = call("pm", "POST", "/templates", {**base, "milestones": [{"name": "Done", "due_offset": 10}]})
    ok(A, "a milestone on day 10 of a 10-day plan is refused (days run 0-9)", s == 422, s)
    s, r = call("pm", "POST", "/templates", {**base, "milestones": [{"name": "Done", "due_offset": 9}],
                                             "tasks": [{"title": "Child step", "parent_index": 1}, {"title": "Parent step"}]})
    ok(A, "a template ending on its last day is saved", s == 201, (s, r.get("detail")))
    if s == 201:
        tpl = r["data"]["id"]
        made_templates.append(tpl)
        s, r = call("pm", "POST", f"/templates/{tpl}/create-project", {
            "project_name": f"Zz Fixes From Plan {stamp}", "customer_name": "Acme Retail", "customer_contact_name": "Ravi Kumar",
            "customer_mobile": "9876543210", "project_type": "Fixed Price", "start_date": d(0), "project_manager_name": "Priya Sharma", "project_manager_id": 3})
        ok(A, "a project is created from it with no end date given", s == 201, (s, r.get("detail")))
        if s == 201:
            npid = (r.get("data") or {}).get("id") or (r.get("data") or {}).get("project", {}).get("id")
            made_projects.append(npid)
            s, ts = call("pm", "GET", f"/tasks/list?project_id={npid}&page_size=50")
            child = next((t for t in ts.get("detail", []) if t["title"] == "Child step"), {})
            ok(A, "a subtask listed above its parent still gets that parent", child.get("parent_task_id"), child)
finally:
    for pid in made_projects:
        if pid:
            for inv in call("admin", "GET", f"/billing/invoices?project_id={pid}&page_size=20")[1].get("detail") or []:
                if inv["status"] in ("Draft", "Issued"):
                    call("finance", "POST", f"/billing/invoices/{inv['id']}/status", {"action": "cancel"})
            call("admin", "DELETE", f"/projects/{pid}")
    for tpl in made_templates:
        call("admin", "DELETE", f"/templates/{tpl}")

failed = [r for r in results if not r[2]]
print(f"\n{len(results) - len(failed)} of {len(results)} checks passed")
print("ALL CHECKS PASSED" if not failed else f"{len(failed)} FAILED")
sys.exit(1 if failed else 0)
