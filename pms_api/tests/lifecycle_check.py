"""Full project lifecycle across every module, checking that each screen reports the same numbers.

Run from backend/pms_api with the API running on :8000:
    set PYTHONIOENCODING=utf-8 && venv\\Scripts\\python tests\\lifecycle_check.py

It creates one client project, takes it from Draft to billed and paid, and compares: Budget tab, Budget overview,
Actual Cost, Variance, Dashboard, Reports, Billing, Capacity, Calendar, Activity, Notifications. Two logins are used
(dev.user does the work, qa.manager approves) because nobody may approve their own time or expenses.
Everything it creates is deleted at the end.
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

ROOT = os.path.abspath(os.path.join(os.getcwd(), "..", ".."))
DEV = re.search(r"NEXT_PUBLIC_PMS_DEV_TOKEN=(.*)", open(os.path.join(ROOT, "frontend", ".env.local"), encoding="utf-8").read()).group(1).strip()
MGR = jwt.encode({"client_id": 900001, "user_id": 2, "username": "qa.manager", "role": "admin", "exp": int(time.time()) + 3600}, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
B = "http://127.0.0.1:8000/api"
NAME = "Lifecycle Check Store"


def call(method, path, body=None, token=None):
    req = urllib.request.Request(B + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + (token or DEV), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


fails = []
step_no = [0]


def step(title):
    step_no[0] += 1
    print(f"\n[{step_no[0]}] {title}")


def ok(name, cond, extra=""):
    if not cond:
        fails.append(name)
    print(("  PASS " if cond else "  FAIL ") + name + ("" if cond else f"  -> {extra}"))
    return cond


today = date.today()
d = lambda n: (today + timedelta(days=n)).isoformat()  # noqa: E731
monday = today - timedelta(days=today.weekday())
log_day = today if today.weekday() < 5 else monday + timedelta(days=4)

for p in call("GET", f"/projects/list?search={NAME.replace(' ', '%20')}&page_size=20")[1].get("detail") or []:
    if p["project_name"] == NAME:
        call("DELETE", f"/projects/{p['id']}")
pid = None
try:
    step("Project: create as Draft, then Pending Approval -> Approved -> Active")
    s, r = call("POST", "/projects/create", {"project_name": NAME, "project_type": "Time & Material", "customer_name": "Acme Retail", "customer_contact_name": "Ravi Kumar",
                                             "customer_mobile": "9876543210", "start_date": d(-14), "end_date": d(45), "budget": 100000, "project_manager_name": "Qa Manager", "priority": "High"})
    ok("created as Draft with a PRJ code", s == 201 and r["data"]["status"] == "Draft" and r["data"]["project_code"].startswith("PRJ-"), r)
    project = r["data"]
    pid = project["id"]
    s, r = call("POST", f"/projects/{pid}/status", {"status": "Active"})
    ok("Draft cannot jump straight to Active", s == 409, r)
    for st in ("Pending Approval", "Approved", "Active"):
        s, r = call("POST", f"/projects/{pid}/status", {"status": st})
    ok("approval chain ends Active", s == 200 and r["data"]["status"] == "Active", r)

    step("Team: project manager added automatically, two people with rates")
    members = {m["member_name"]: m for m in call("GET", f"/projects/{pid}/members")[1]["detail"]}
    ok("the project manager is on the team automatically", "Qa Manager" in members, list(members))
    call("PUT", f"/projects/{pid}/members/{members['Qa Manager']['id']}", {**{k: members["Qa Manager"][k] for k in ("member_name", "role")}, "user_id": 2, "allocation_pct": 10, "hourly_rate": 1500})
    s, r = call("POST", f"/projects/{pid}/members", {"member_name": "Dev User", "user_id": 1, "role": "Developer", "allocation_pct": 50, "hourly_rate": 1000})
    ok("developer added at 50%, ₹1000/h", s == 201, r)

    step("Settings: budget alert 60%, receipts above ₹5,000")
    s, r = call("PUT", f"/projects/{pid}/settings", {"budget_alert_pct": 60, "receipt_required_above": 5000, "default_tax_pct": 18, "default_payment_terms": 15})
    ok("project settings saved", s == 200, r)

    step("Plan: milestone worth ₹40,000, two tasks linked to it, one dependency")
    s, r = call("POST", f"/projects/{pid}/milestones", {"name": "Store Front Live", "due_date": d(10), "amount": 40000})
    ms = r["data"]
    ok("milestone created (Planned)", s == 201 and ms["status"] == "Planned", r)
    t1 = call("POST", "/tasks/create", {"project_id": pid, "title": "Design the store front", "assignee_name": "Dev User", "estimated_hours": 6, "start_date": d(-10), "due_date": d(-5), "milestone_id": ms["id"]}, token=MGR)[1]["data"]
    t2 = call("POST", "/tasks/create", {"project_id": pid, "title": "Build the checkout", "assignee_name": "Dev User", "estimated_hours": 10, "start_date": d(-4), "due_date": d(8), "milestone_id": ms["id"]}, token=MGR)[1]["data"]
    s, r = call("POST", f"/tasks/{t2['id']}/dependencies", {"depends_on_id": t1["id"]})
    ok("checkout depends on design", s in (200, 201), r)
    s, r = call("GET", f"/projects/{pid}/timeline")
    ok("Gantt timeline has both tasks and the milestone, critical path = 2 tasks", s == 200 and len(r["detail"]["tasks"]) == 2 and len(r["detail"]["critical_path"]) == 2, r.get("detail", {}).get("critical_path"))
    s, r = call("GET", "/notifications?kind=assigned&unread_only=true")
    ok("dev.user was notified about the 2 assignments", sum(1 for n in r["detail"] if n["task_id"] in (t1["id"], t2["id"])) == 2, r)

    step("Sprint: plan both tasks, start it")
    sp = call("POST", f"/projects/{pid}/sprints", {"name": "Sprint 1", "start_date": d(-7), "end_date": d(6)})[1]["data"]
    s, r = call("POST", f"/sprints/{sp['id']}/tasks", {"task_ids": [t1["id"], t2["id"]]})
    ok("2 tasks in Sprint 1", s == 200, r)
    s, r = call("POST", f"/sprints/{sp['id']}/start")
    ok("sprint started", s == 200 and r["data"]["status"] == "Active", r)

    step("Work: blocked task cannot finish first; status changes notify the manager")
    s, r = call("POST", f"/tasks/{t2['id']}/status", {"status": "Done"})
    ok("checkout cannot be Done while design is open", s == 409 and "blocked" in r["detail"], r)
    for st in ("In Progress", "Done"):
        call("POST", f"/tasks/{t1['id']}/status", {"status": st})
    call("POST", f"/tasks/{t2['id']}/status", {"status": "In Progress"})
    s, r = call("POST", f"/tasks/{t2['id']}/comments", {"body": "@Qa Manager checkout is ready for review"})
    ok("comment with a mention saved", s in (200, 201), r)
    s, r = call("GET", "/communication/mentions?unread_only=true", token=MGR)
    ok("manager sees the mention", any(m["task_id"] == t2["id"] for m in r["detail"]), r)

    step("Timesheets: 8 h logged, submitted, approved by the manager")
    e1 = call("POST", "/timesheets/entries", {"task_id": t1["id"], "work_date": log_day.isoformat(), "hours": 5})[1]
    e2 = call("POST", "/timesheets/entries", {"task_id": t2["id"], "work_date": log_day.isoformat(), "hours": 3})[1]
    ok("two entries saved", "data" in e1 and "data" in e2, (e1, e2))
    call("POST", "/timesheets/submit", {"week_start": (log_day - timedelta(days=log_day.weekday())).isoformat()})
    s, r = call("POST", "/timesheets/approve", {"entry_ids": [e1["data"]["id"], e2["data"]["id"]]}, token=MGR)
    ok("manager approved 8 h", s == 200, r)
    task1 = call("GET", f"/tasks/{t1['id']}")[1]["detail"]
    ok("task actual hours = approved hours (5)", task1["actual_hours"] == 5, task1["actual_hours"])

    step("Expenses: receipt rule, billable hotel approved")
    s, r = call("POST", "/expenses", {"project_id": pid, "category": "Food & Stay", "description": "Hotel near client", "amount": 6000, "billable": True, "expense_date": log_day.isoformat(), "submit": True})
    ok("₹6,000 without a receipt is refused (limit ₹5,000)", s == 409 and "receipt" in r["detail"], r)
    s, r = call("POST", "/expenses", {"project_id": pid, "category": "Travel", "description": "Cab to client", "amount": 2000, "billable": True, "expense_date": log_day.isoformat(), "submit": True})
    cab = r["data"]
    s, r = call("POST", "/expenses/approve", {"ids": [cab["id"]]}, token=MGR)
    ok("billable cab expense approved", s == 200, r)

    step("Milestone: finish the work, accept it")
    call("POST", f"/tasks/{t2['id']}/status", {"status": "Done"})
    s, r = call("GET", f"/projects/{pid}/milestones")
    m_now = next(m for m in r["detail"] if m["id"] == ms["id"])
    ok("milestone started itself when work began and shows 2/2 tasks done", m_now["status"] == "In Progress" and m_now["tasks_done"] == 2, m_now)
    call("POST", f"/projects/{pid}/milestones/{ms['id']}/status", {"status": "Ready for Review"})
    s, r = call("POST", f"/projects/{pid}/milestones/{ms['id']}/status", {"status": "Accepted"}, token=MGR)
    ok("milestone Accepted", s == 200 and r["data"]["status"] == "Accepted", r)

    step("Sprint: complete it -> velocity")
    s, r = call("POST", f"/sprints/{sp['id']}/complete", {"move_to_sprint_id": None})
    ok("sprint completed with 2 of 2 tasks", s == 200, r)
    s, r = call("GET", f"/projects/{pid}/sprints")
    ok("velocity = 16 estimated hours", r["stack_values"]["velocity"] and r["stack_values"]["velocity"][-1]["completed"] == 16, r["stack_values"])

    step("Billing: milestone invoice + Time & Material (hours + billable expense), issue, pay one")
    s, r = call("POST", "/billing/invoices", {"project_id": pid, "invoice_type": "Milestone", "milestone_id": ms["id"]})
    inv_m = r["data"]
    ok("milestone invoice uses the project default GST 18% -> ₹47,200", s == 201 and inv_m["total"] == 47200, r)
    s, r = call("POST", "/billing/invoices", {"project_id": pid, "invoice_type": "Time & Material", "period_from": d(-14), "period_to": d(0)})
    inv_t = r["data"]
    ok("T&M invoice = 8 h x ₹1000 + ₹2,000 cab = ₹10,000 + GST", s == 201 and inv_t["subtotal"] == 10000, r)
    call("POST", f"/billing/invoices/{inv_m['id']}/status", {"action": "issue"})
    call("POST", f"/billing/invoices/{inv_m['id']}/status", {"action": "pay"})
    call("POST", f"/billing/invoices/{inv_t['id']}/status", {"action": "issue"})

    step("Risk: a High risk makes the project At Risk on the dashboard")
    qa = next(m for m in call("GET", f"/projects/{pid}/members")[1]["detail"] if m["member_name"] == "Qa Manager")
    s, r = call("POST", f"/projects/{pid}/risks", {"title": "Payment gateway outage", "category": "Technical", "probability": 4, "impact": 5, "owner_member_id": qa["id"],
                                                   "mitigation": "Add a second gateway as fallback before go live"})
    ok("High risk (score 20) recorded", s == 201 and r["data"]["level"] == "High", r)

    step("Cross-check: every screen reports the same numbers")
    labour = 5 * 1000 + 3 * 1000
    actual = labour + 2000
    b = call("GET", f"/projects/{pid}/budget")[1]["detail"]
    ok(f"Budget tab: actual ₹{actual:,} (labour {labour:,} + expenses 2,000)", b["actual_cost"] == actual and b["labour_cost"] == labour and b["expense_cost"] == 2000, b)
    ok("Budget tab: billed = both invoices before GST (50,000), collected = paid one (40,000)", b["billed"] == 50000 and b["collected"] == 40000, (b["billed"], b["collected"]))
    ov = next(x for x in call("GET", "/budget/overview")[1]["detail"] if x["project_id"] == pid)
    ok("Budget overview: same actual cost", ov["actual_cost"] == actual, ov)
    ac = call("GET", f"/budget/actual-cost?project_id={pid}")[1]["detail"]["projects"][0]
    ok("Actual Cost screen: same labour / expenses / total", (ac["labour"], ac["expenses"], ac["total"]) == (labour, 2000, actual), ac)
    va = call("GET", f"/budget/variance?project_id={pid}")[1]["detail"]["projects"][0]
    ok("Variance: same actual, 100% done -> EV = budget, CPI = 100000/10000 = 10", va["actual"] == actual and va["progress"] == 100 and va["ev"] == 100000 and va["cpi"] == 10.0, va)
    dash = call("GET", f"/dashboard/overview?project_id={pid}")[1]["detail"]
    drow = dash["projects"][0]
    ok("Dashboard: same actual cost and billed", drow["budgetActual"] == actual and drow["billed"] == 50000, drow)
    ok("Dashboard: High risk -> project At Risk, risk counted", drow["health"] == "At Risk" and dash["riskCounts"]["High"] == 1, (drow.get("health"), dash["riskCounts"]))
    ok("Dashboard: billing paid ₹47,200, outstanding ₹11,800", dash["billing"]["paid"] == 47200 and dash["billing"]["outstanding"] == 11800, dash["billing"])
    rep = call("GET", f"/reports/budget?project_id={pid}")[1]["detail"]["rows"][0]
    ok("Reports > Budget vs Actual: same actual and billed", rep["actual"] == actual and rep["billed"] == 50000, rep)
    rps = call("GET", f"/reports/project-status?project_id={pid}")[1]["detail"]["rows"][0]
    ok("Reports > Project Status: 100% progress, 2 tasks done", rps["progress"] == 100 and rps["done"] == 2, rps)
    th = call("GET", f"/reports/timesheet-hours?project_id={pid}&date_from={d(-14)}&date_to={d(0)}")[1]["detail"]
    ok("Reports > Timesheet Hours: 8 approved hours", th["totals"].get("approved", th["totals"].get("hours")) == 8, th["totals"])
    cal = call("GET", f"/calendar?date_from={d(-15)}&date_to={d(15)}&project_id={pid}")[1]["detail"]
    ok("Task Calendar: both tasks and the milestone", len(cal["tasks"]) == 2 and len(cal["milestones"]) == 1, cal)
    act = call("GET", f"/communication/activity?project_id={pid}&page_size=100")[1]["detail"]
    kinds = {a["action"] for a in act}
    ok("Activity feed: created, status, comment, dependency, time, sprint", {"created", "status", "comment", "dependency", "time", "sprint"} <= kinds, kinds)
    cap = call("GET", f"/resources/capacity?project_id={pid}&weeks=2")[1]["detail"]
    ok("Capacity: Dev User has available hours, no open work left", any(p["member_name"] == "Dev User" and p["available"] > 0 and p["planned"] == 0 for p in cap["people"]), cap["people"])
    s, r = call("GET", f"/projects/{pid}")
    ok("project progress 100%", r["detail"].get("progress", r["detail"].get("stats", {}).get("progress")) == 100, r["detail"].get("progress"))

    step("Close the project: no more changes")
    s, r = call("POST", f"/projects/{pid}/status", {"status": "Closed"})
    ok("project Closed", s == 200, r)
    s, r = call("POST", "/tasks/create", {"project_id": pid, "title": "Late change"})
    ok("no new tasks on a Closed project", s in (400, 409) and "Closed" in r["detail"], r)
    s, r = call("PUT", f"/projects/{pid}/settings", {"budget_alert_pct": 70})
    ok("settings are read-only once Closed", s == 409, r)
finally:
    if pid:
        for inv in call("GET", f"/billing/invoices?project_id={pid}&page_size=20")[1].get("detail") or []:
            if inv["status"] in ("Draft", "Issued"):
                call("POST", f"/billing/invoices/{inv['id']}/status", {"action": "cancel"})
        for t in call("GET", f"/tasks/list?project_id={pid}&page_size=50")[1].get("detail") or []:
            call("DELETE", f"/tasks/{t['id']}")
        call("DELETE", f"/projects/{pid}")
    print(f"\n{'ALL PASSED' if not fails else f'{len(fails)} FAILED: ' + '; '.join(fails)}")
    sys.exit(1 if fails else 0)
