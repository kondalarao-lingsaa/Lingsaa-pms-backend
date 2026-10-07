"""End-to-end business flow, done by the right role at each step, with wrong inputs tried on purpose.

One project goes Draft -> Approved -> Active -> Closed: team, milestone, tasks, hours, expense, change request,
client acceptance, invoice, payment. At each step the wrong person and wrong values are tried too.
Needs the demo role users (scripts/seed_demo_roles.py) and the API on port 8000.
Run from backend/pms_api:  venv\\Scripts\\python tests\\api_audit_flow.py
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


def ok(area, name, cond, extra=""):
    results.append((area, name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + f"[{area}] {name}" + ("" if cond else f"  {str(extra)[:300]}"))


today = date.today()
d = lambda n: (today + timedelta(days=n)).isoformat()  # noqa: E731
stamp = str(int(time.time()))[-6:]
pid = None

base = {"project_name": f"Zz Audit Flow {stamp}", "project_type": "Fixed Price", "customer_name": "Acme Retail", "customer_contact_name": "Ravi Kumar",
        "customer_mobile": "9876543210", "start_date": d(-14), "end_date": d(60), "budget": 500000, "project_manager_name": "Priya Sharma",
        "project_manager_id": 3}

try:
    # ------------------------------------------------------------------ 1. create (validation)
    A = "Create project"
    for label, patch in [("empty name", {"project_name": ""}), ("bad mobile 1234567890", {"customer_mobile": "1234567890"}),
                         ("end before start", {"end_date": d(-20)}), ("negative budget", {"budget": -5}),
                         ("no client on a client project", {"customer_name": ""}), ("unknown project type", {"project_type": "Barter"})]:
        s, r = call("pm", "POST", "/projects/create", {**base, **patch})
        ok(A, f"refuses {label}", s == 422, (s, r))
        if s == 201:  # a wrong value got through: remove it so the real flow can continue
            call("admin", "DELETE", f"/projects/{r['data']['id']}")
    s, r = call("member", "POST", "/projects/create", base)
    ok(A, "a Member cannot create a project", s == 403, s)
    s, p = call("pm", "POST", "/projects/create", base)
    ok(A, "PM creates a valid project (Draft)", s == 201 and p["data"]["status"] == "Draft", p)
    pid = p["data"]["id"]
    s, r = call("pm", "POST", "/projects/create", base)
    ok(A, "refuses a duplicate project name", s == 409, s)

    # ------------------------------------------------------------------ 2. team
    A = "Team"
    s, r = call("pm", "POST", f"/projects/{pid}/members", {"member_name": "Anita Rao", "user_id": 5, "role": "Designer", "allocation_pct": 130})
    ok(A, "refuses allocation above 100%", s == 422, s)
    s, r = call("pm", "POST", f"/projects/{pid}/members", {"member_name": "Anita Rao", "user_id": 5, "role": "Designer", "allocation_pct": 0,
                                                           "hourly_rate": 600})
    ok(A, "adds Anita (Member) at 0% (real projects may book her fully), Rs 600/h", s == 201, r)
    s, r = call("pm", "POST", f"/projects/{pid}/members", {"member_name": "Anita Rao", "user_id": 5, "role": "Designer", "allocation_pct": 10})
    ok(A, "refuses adding the same person twice", s in (409, 422), s)
    s, r = call("pm", "POST", f"/projects/{pid}/members", {"member_name": "Arjun Mehta", "user_id": 4, "role": "Team Lead", "allocation_pct": 0,
                                                           "hourly_rate": 900})
    ok(A, "adds Arjun as Team Lead", s == 201, r)
    s, r = call("member", "POST", f"/projects/{pid}/members", {"member_name": "Meena Das", "user_id": 7, "role": "Other", "allocation_pct": 5})
    ok(A, "a Member cannot change the team", s == 403, s)

    # ------------------------------------------------------------------ 3. milestone + tasks
    A = "Plan"
    s, r = call("pm", "POST", f"/projects/{pid}/milestones", {"name": "Design Sign-off", "amount": -100})
    ok(A, "refuses a negative milestone amount", s == 422, s)
    s, r = call("pm", "POST", f"/projects/{pid}/milestones", {"name": "Late One", "due_date": d(90)})
    ok(A, "refuses a milestone due after the project ends", s in (409, 422), s)
    s, ms = call("pm", "POST", f"/projects/{pid}/milestones", {"name": "Design Sign-off", "amount": 150000, "due_date": d(20)})
    ok(A, "adds milestone Design Sign-off (Rs 1,50,000)", s == 201, ms)
    mid = ms["data"]["id"]
    s, r = call("pm", "POST", "/tasks/create", {"project_id": pid, "title": "Bad dates", "start_date": d(5), "due_date": d(1)})
    ok(A, "refuses a task due before it starts", s in (409, 422), s)
    s, r = call("pm", "POST", "/tasks/create", {"project_id": pid, "title": "Not on team", "assignee_name": "Kiran Iyer", "assignee_id": 6})
    ok(A, "refuses assigning a task to someone not on the team", s in (400, 409, 422), (s, r))
    s, t1 = call("pm", "POST", "/tasks/create", {"project_id": pid, "title": "Design home page", "assignee_id": 5, "assignee_name": "Anita Rao",
                                                 "estimated_hours": 16, "milestone_id": mid, "start_date": d(-10), "due_date": d(10)})
    ok(A, "adds task Design home page for Anita", s == 201, t1)
    tid = t1["data"]["id"]
    s, r = call("member", "POST", "/tasks/create", {"project_id": pid, "title": "Member task"})
    ok(A, "a Member cannot create tasks", s == 403, s)

    # ------------------------------------------------------------------ 4. approval
    A = "Approval"
    s, r = call("member", "POST", f"/projects/{pid}/status", {"status": "Pending Approval"})
    ok(A, "a Member cannot submit the project", s == 403, s)
    s, r = call("pm", "POST", f"/projects/{pid}/status", {"status": "Pending Approval"})
    ok(A, "PM submits: Rs 5,00,000 waits for the Director", s == 200 and r["data"]["status"] == "Pending Approval", r)
    s, r = call("pm", "POST", f"/projects/{pid}/status", {"status": "Approved"})
    ok(A, "PM cannot approve their own project", s == 409, s)
    s, r = call("finance", "POST", f"/projects/{pid}/status", {"status": "Approved"})
    ok(A, "Finance cannot approve projects", s in (403, 409), s)
    s, r = call("director", "POST", f"/projects/{pid}/status", {"status": "Approved", "remarks": "Approved for Q4"})
    ok(A, "Director approves", s == 200 and r["data"]["status"] == "Approved" and r["data"]["baseline"], r)
    s, r = call("pm", "POST", f"/projects/{pid}/status", {"status": "Active"})
    ok(A, "PM activates the project", s == 200 and r["data"]["status"] == "Active", r)

    # ------------------------------------------------------------------ 5. hours
    A = "Timesheets"
    s, r = call("member", "POST", "/timesheets/entries", {"task_id": tid, "work_date": d(1), "hours": 4})
    ok(A, "refuses hours on a future day", s in (409, 422), s)
    s, r = call("member", "POST", "/timesheets/entries", {"task_id": tid, "work_date": d(-1), "hours": 25})
    ok(A, "refuses more than 24 hours", s == 422, s)
    s, r = call("member", "POST", "/timesheets/entries", {"task_id": tid, "work_date": d(-1), "hours": 0.1})
    ok(A, "refuses hours not in quarter-hour steps", s in (409, 422), s)
    work_day = today - timedelta(days=today.weekday() + 7) + timedelta(days=1)  # Tuesday of last week
    s, r = call("member", "POST", "/timesheets/entries", {"task_id": tid, "work_date": work_day.isoformat(), "hours": 6})
    ok(A, "Anita logs 6 h", s == 200, r)
    week = (work_day - timedelta(days=work_day.weekday())).isoformat()
    s, r = call("member", "POST", "/timesheets/submit", {"week_start": week})
    ok(A, "Anita submits her week", s == 200, r)
    s, q = call("lead", "GET", "/timesheets/approvals")
    entry_ids = [e["id"] for g in q.get("detail", []) for e in g["entries"] if e["task_id"] == tid] if s == 200 else []
    ok(A, "Team Lead sees Anita's hours to approve", entry_ids, q)
    s, r = call("member", "POST", "/timesheets/approve", {"entry_ids": entry_ids})
    ok(A, "Anita cannot approve her own hours", s in (403, 409), s)
    s, r = call("lead", "POST", "/timesheets/approve", {"entry_ids": entry_ids})
    ok(A, "Team Lead approves them", s == 200, r)
    s, b = call("pm", "GET", f"/projects/{pid}/budget")
    ok(A, "labour cost = 6 h x Rs 600 = Rs 3,600", s == 200 and round(b["detail"]["labour_cost"]) == 3600, b.get("detail", {}).get("labour_cost"))

    # ------------------------------------------------------------------ 6. expense
    A = "Expenses"
    s, r = call("member", "POST", "/expenses", {"project_id": pid, "category": "Travel", "description": "Client visit", "expense_date": d(1),
                                                "amount": 2000})
    ok(A, "refuses a future-dated expense", s in (409, 422), s)
    s, r = call("member", "POST", "/expenses", {"project_id": pid, "category": "Travel", "description": "Client visit", "expense_date": d(-2),
                                                "amount": 0})
    ok(A, "refuses a zero amount", s == 422, s)
    s, e = call("member", "POST", "/expenses", {"project_id": pid, "category": "Hardware", "description": "Test devices", "expense_date": d(-2),
                                                "amount": 25000, "billable": True, "submit": True})
    ok(A, "Anita submits a Rs 25,000 expense", s == 201, e)
    eid = e["data"]["id"]
    s, r = call("pm", "POST", "/expenses/approve", {"ids": [eid]})
    ok(A, "PM cannot approve above the Rs 10,000 expense limit", s == 409, s)
    s, r = call("finance", "POST", "/expenses/approve", {"ids": [eid]})
    ok(A, "Finance approves it", s == 200, r)

    # ------------------------------------------------------------------ 7. change request
    A = "Change requests"
    s, c = call("member", "POST", f"/projects/{pid}/change-requests", {"title": "Extra page", "reason": "Client asked for a careers page",
                                                                      "change_type": "Cost", "cost_impact": 200000})
    ok(A, "Anita raises a Rs 2,00,000 change", s == 201, c)
    s, r = call("pm", "POST", f"/projects/{pid}/change-requests/{c['data']['id']}/approve", {})
    ok(A, "PM cannot approve a change above the PM limit", s == 409, s)
    s, r = call("director", "POST", f"/projects/{pid}/change-requests/{c['data']['id']}/approve", {})
    ok(A, "Director approves it", s == 200, r)
    s, pr = call("pm", "GET", f"/projects/{pid}")
    ok(A, "budget is now Rs 7,00,000, baseline stays Rs 5,00,000",
       pr["detail"]["budget"] == 700000 and pr["detail"]["baseline"]["budget"] == 500000, (pr["detail"]["budget"], pr["detail"]["baseline"]))

    # ------------------------------------------------------------------ 8. milestone -> client -> invoice
    A = "Delivery & billing"
    s, r = call("member", "POST", f"/tasks/{tid}/status", {"status": "Done"})
    ok(A, "Anita finishes her task", s == 200, r)
    # Settings > Automation: the milestone's last open task done -> it goes to Ready for Review by itself.
    s, ms = call("pm", "GET", f"/projects/{pid}/milestones")
    ok(A, "the milestone went to Ready for Review by itself", next(m for m in ms["detail"] if m["id"] == mid)["status"] == "Ready for Review", ms)
    s, r = call("client", "POST", f"/portal/projects/{pid}/milestones/{mid}/decision", {"decision": "changes", "feedback": "no"})
    ok(A, "client must say what to change (at least 5 characters)", s in (409, 422), s)
    s, r = call("client", "POST", f"/portal/projects/{pid}/milestones/{mid}/decision", {"decision": "accept"})
    ok(A, "client accepts the milestone in the portal", s == 200, r)
    s, r = call("member", "POST", "/billing/invoices", {"project_id": pid, "invoice_type": "Milestone", "milestone_id": mid})
    ok(A, "a Member cannot create invoices", s == 403, s)
    # Settings > Automation: accepting it drafted the invoice with the project's GST and terms.
    s, invs = call("finance", "GET", f"/billing/invoices?project_id={pid}&page_size=50")
    drafted = next((i for i in invs.get("detail") or [] if i["invoice_type"] == "Milestone" and i["status"] == "Draft"), None)
    ok(A, "the milestone invoice was drafted by itself on acceptance", drafted is not None, invs)
    iid = drafted["id"]
    s, r = call("pm", "POST", "/billing/invoices", {"project_id": pid, "invoice_type": "Milestone", "milestone_id": mid})
    ok(A, "the same milestone cannot be billed twice", s == 409, s)
    s, r = call("pm", "POST", f"/billing/invoices/{iid}/status", {"action": "issue"})
    ok(A, "PM cannot issue invoices (Finance does)", s == 403, s)
    s, r = call("finance", "POST", f"/billing/invoices/{iid}/status", {"action": "issue"})
    ok(A, "Finance issues it", s == 200, r)
    s, r = call("finance", "POST", f"/billing/invoices/{iid}/status", {"action": "pay", "paid_date": d(5)})
    ok(A, "refuses a payment date in the future", s in (409, 422), s)
    s, r = call("finance", "POST", f"/billing/invoices/{iid}/status", {"action": "pay", "paid_date": d(0)})
    ok(A, "Finance records the payment", s == 200, r)
    s, pp = call("client", "GET", f"/portal/projects/{pid}")
    ok(A, "client sees the paid invoice in the portal", s == 200 and any(i["status"] == "Paid" for i in pp["detail"]["invoices"]), pp)

    # ------------------------------------------------------------------ 9. visibility
    A = "Visibility"
    s, r = call("member", "GET", f"/projects/{pid}/members")
    ok(A, "Anita does not see pay rates", s == 200 and all(m["hourly_rate"] is None for m in r["detail"]), r)
    s, r = call("resource", "GET", f"/projects/{pid}/budget")
    ok(A, "Resource Manager cannot see the budget", s == 403, s)
    s, r = call("client", "GET", f"/tasks/{tid}")
    ok(A, "client cannot open internal task details", s == 403, s)
    s, r = call("client", "GET", "/search?q=Audit")
    ok(A, "client cannot use internal search", s == 403, s)
    s, r = call("lead", "GET", "/billing/invoices")
    ok(A, "Team Lead cannot open Billing", s == 403, s)

    # ------------------------------------------------------------------ 10. close
    A = "Close"
    s, r = call("member", "POST", f"/projects/{pid}/status", {"status": "Closed"})
    ok(A, "a Member cannot close the project", s == 403, s)
    s, r = call("pm", "POST", f"/projects/{pid}/status", {"status": "Closed"})
    ok(A, "PM closes the project", s == 200 and r["data"]["status"] == "Closed", r)
    s, r = call("pm", "POST", "/tasks/create", {"project_id": pid, "title": "After close"})
    ok(A, "no new tasks on a Closed project", s in (400, 409, 422), (s, r))
    s, r = call("member", "POST", "/timesheets/entries", {"task_id": tid, "work_date": d(-1), "hours": 1})
    ok(A, "no hours on a Closed project", s in (409, 422), s)
finally:
    if pid:
        call("admin", "DELETE", f"/projects/{pid}")

failed = [r for r in results if not r[2]]
print(f"\n{len(results) - len(failed)} of {len(results)} checks passed")
print("ALL CHECKS PASSED" if not failed else f"{len(failed)} FAILED")
sys.exit(1 if failed else 0)
