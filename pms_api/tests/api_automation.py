"""API checks for Settings > Automation, every automation job, recurring tasks and assignee suggestions.

Runs in its own test company (900777), so the demo company's data is never touched by the jobs (they act
company-wide). Run from backend/pms_api with the API on :8000:
    venv\\Scripts\\python tests\\api_automation.py
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

sys.path.insert(0, os.getcwd())
from jose import jwt  # noqa: E402

from app.core.config import settings  # noqa: E402

COMPANY = 900777
B = os.environ.get("PMS_API", "http://127.0.0.1:8000/api")


def token(user_id, username):
    return jwt.encode({"client_id": COMPANY, "user_id": user_id, "username": username, "exp": int(time.time()) + 3600},
                      settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


ADMIN, DIRECTOR, MEMBER = token(1, "auto.admin"), token(2, "auto.director"), token(3, "auto.member")


def call(method, path, body=None, tok=ADMIN):
    req = urllib.request.Request(B + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


fails = 0


def ok(name, cond, extra=""):
    global fails
    fails += 0 if cond else 1
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {str(extra)[:600]}"))


def run(job):
    s, r = call("POST", f"/automation/{job}/run")
    return r.get("data") or {"status": f"HTTP {s}", "summary": r.get("detail"), "items": 0}


def notes(kind=None, tok=ADMIN):
    return call("GET", "/notifications?page_size=50" + (f"&kind={kind}" if kind else ""), tok=tok)[1].get("detail") or []


today = date.today()
d = lambda n: (today + timedelta(days=n)).isoformat()  # noqa: E731

# ---------------- company setup: Admin (first user), a Director, a Member
call("GET", "/me")
for uid, name, role in ((1, "Auto Admin", "admin"), (2, "Auto Director", "director"), (3, "Auto Member", "member")):
    rows = call("GET", "/settings/users")[1].get("detail") or []
    rows = rows.get("users", rows) if isinstance(rows, dict) else rows
    row = next((x for x in rows if x.get("user_id") == uid), None)
    body = {"user_id": uid, "user_name": name, "role": role, "is_active": True}
    if row:
        call("PUT", f"/settings/users/{row['id']}", body)
    else:
        call("POST", "/settings/users", body)
# Every working day, so the time-based checks below do not depend on today's weekday.
call("PUT", "/settings/calendar", {"hours_per_day": 8, "working_days": [0, 1, 2, 3, 4, 5, 6]})

PREFIX = "Automation Check"
for p in call("GET", f"/projects/list?search={PREFIX.replace(' ', '%20')}&page_size=50")[1].get("detail") or []:
    for inv in call("GET", f"/billing/invoices?project_id={p['id']}&page_size=50")[1].get("detail") or []:
        if inv["status"] in ("Draft", "Issued"):
            call("POST", f"/billing/invoices/{inv['id']}/status", {"action": "cancel"})
    call("DELETE", f"/projects/{p['id']}")


def project(name, ptype="Time & Material", start=-60, end=60, budget=90000):
    body = {"project_name": f"{PREFIX} {name}", "project_type": ptype, "customer_name": None if ptype == "Internal" else "Auto Client Pvt Ltd",
            "customer_contact_name": "Ravi Kumar", "customer_mobile": "9876543210", "customer_email": "ravi@autoclient.in",
            "start_date": d(start), "end_date": d(end), "budget": budget, "project_manager_id": 1, "project_manager_name": "Auto Admin"}
    s, r = call("POST", "/projects/create", body)
    assert s in (200, 201), r
    pid = r["data"]["id"]
    for st in ("Pending Approval", "Approved", "Active"):
        call("POST", f"/projects/{pid}/status", {"status": st})
    status = call("GET", f"/projects/{pid}")[1]["detail"]["status"]
    assert status == "Active", status
    # The manager (Auto Admin) joins the team by himself; Auto Member works on many test projects, so a small share each.
    s, r = call("POST", f"/projects/{pid}/members", {"member_name": "Auto Member", "user_id": 3, "role": "Developer", "allocation_pct": 5, "hourly_rate": 500})
    assert s in (200, 201), r
    return pid


def task(pid, title, **kw):
    s, r = call("POST", "/tasks/create", {"project_id": pid, "title": title, **kw})
    assert s in (200, 201), r
    return r["data"]


def set_status(tid, status, tok=ADMIN):
    return call("POST", f"/tasks/{tid}/status", {"status": status}, tok=tok)


# ---------------- Settings > Automation (back to the defaults first: an earlier run changed some)
for key in ("task_reminders", "approval_reminders", "weekly_status_report", "parent_auto_done", "milestone_auto_review", "milestone_invoice"):
    call("PUT", f"/automation/{key}", {"enabled": True})
call("PUT", "/automation/task_reminders", {"run_time": "09:00", "params": {"escalate_after_days": 3}})
s, r = call("GET", "/automation")
jobs = {j["key"]: j for j in (r.get("detail") or {}).get("jobs", [])}
ok("GET /automation lists the 14 jobs in 4 groups", s == 200 and len(jobs) == 14 and len(r["detail"]["groups"]) == 4, r)
ok("defaults: task reminders daily 09:00, weekly report Monday, monthly invoices day 1", jobs.get("task_reminders", {}).get("run_time") == "09:00"
   and jobs["weekly_status_report"]["weekday"] == 0 and jobs["monthly_invoices"]["month_day"] == 1, jobs.get("task_reminders"))
ok("scheduler is running in the API", r["detail"].get("scheduler_running") is True, r["detail"].get("scheduler_running"))
ok("a Member cannot open automation settings (403)", call("GET", "/automation", tok=MEMBER)[0] == 403)
ok("a Member cannot run a job (403)", call("POST", "/automation/task_reminders/run", tok=MEMBER)[0] == 403)
for body, why in [({"run_time": "25:00"}, "time 25:00"), ({"params": {"escalate_after_days": 0}}, "escalate after 0 days"),
                  ({"params": {"unknown": 3}}, "unknown setting"), ({"month_day": 31}, "month day 31")]:
    s, r = call("PUT", "/automation/task_reminders", body)
    ok(f"refused: {why} -> 422", s == 422, r)
s, r = call("PUT", "/automation/approval_reminders", {"params": {"remind_after_days": 5, "escalate_after_days": 3}})
ok("refused: escalate sooner than remind", s == 422 and "more days" in r["detail"], r)
s, r = call("PUT", "/automation/task_reminders", {"run_time": "08:15", "params": {"escalate_after_days": 2}})
ok("saved: time 08:15, escalate after 2 days", s == 200 and r["data"]["run_time"] == "08:15" and r["data"]["params"]["escalate_after_days"] == 2, r)
s, r = call("PUT", "/automation/weekly_status_report", {"enabled": False})
ok("switched off: weekly report shows no next run", s == 200 and r["data"]["enabled"] is False and r["data"]["next_run_at"] is None, r)
call("PUT", "/automation/weekly_status_report", {"enabled": True})
ok("event jobs cannot be run by hand (404)", call("POST", "/automation/parent_auto_done/run")[0] == 404)

# ---------------- work: parent task finishes with its subtasks; milestone goes to review by itself
pid = project("Work")
parent = task(pid, "Build login screen", assignee_name="Auto Member")
subs = [task(pid, f"Login part {i}", parent_task_id=parent["id"], assignee_name="Auto Member") for i in (1, 2)]
set_status(subs[0]["id"], "Done")
ok("one of two subtasks done: main task not done yet", call("GET", f"/tasks/{parent['id']}")[1]["detail"]["status"] != "Done")
set_status(subs[1]["id"], "Done")
ok("last subtask done: main task moved to Done", call("GET", f"/tasks/{parent['id']}")[1]["detail"]["status"] == "Done")
set_status(subs[1]["id"], "In Progress")
ok("a subtask reopened: main task back to In Progress", call("GET", f"/tasks/{parent['id']}")[1]["detail"]["status"] == "In Progress")
call("PUT", "/automation/parent_auto_done", {"enabled": False})
set_status(subs[1]["id"], "Done")
ok("switched off: main task stays In Progress", call("GET", f"/tasks/{parent['id']}")[1]["detail"]["status"] == "In Progress")
call("PUT", "/automation/parent_auto_done", {"enabled": True})

m = call("POST", f"/projects/{pid}/milestones", {"name": "Phase One", "due_date": d(30), "amount": 50000})[1]["data"]
t1 = task(pid, "Phase one work", milestone_id=m["id"], assignee_name="Auto Member")
call("POST", f"/projects/{pid}/milestones/{m['id']}/deliverables", {"name": "Design document"})
ms = lambda: next(x for x in call("GET", f"/projects/{pid}/milestones")[1]["detail"] if x["id"] == m["id"])  # noqa: E731
dl = ms()["deliverables"][0]
set_status(t1["id"], "Done")
ok("task done but a deliverable open: milestone stays In Progress", ms()["status"] == "In Progress", ms()["status"])
call("POST", f"/projects/{pid}/milestones/{m['id']}/deliverables/{dl['id']}/done", {"is_done": True})
ok("deliverable done: milestone moved to Ready for Review by itself", ms()["status"] == "Ready for Review", ms()["status"])
ok("project manager told the milestone is ready", any("ready for review" in n["title"] for n in notes("approval")))

# ---------------- billing: draft invoice when a milestone is accepted
s, r = call("POST", f"/projects/{pid}/milestones/{m['id']}/status", {"status": "Accepted"}, tok=DIRECTOR)
ok("Director accepts the milestone", s == 200, r)
invs = call("GET", f"/billing/invoices?project_id={pid}&page_size=50")[1]["detail"]
mi = next((i for i in invs if i["invoice_type"] == "Milestone"), None)
ok("a Draft milestone invoice was created (50,000 + 18% GST)", mi is not None and mi["status"] == "Draft" and float(mi["total"]) == 59000, invs)
ok("Finance/Admin told about the draft invoice", any("Draft invoice" in n["title"] for n in notes("automation")))

# ---------------- reminders: due / overdue tasks and escalation
rp = project("Reminders")
late = task(rp, "Send weekly report", assignee_name="Auto Member", start_date=d(-5), due_date=d(-3))
task(rp, "Prepare demo", assignee_name="Auto Member", due_date=d(0))
res = run("task_reminders")
ok("task reminders ran", res["status"] == "Success" and res["items"] >= 2, res)
mine = notes("reminder", tok=MEMBER)
ok("assignee got one reminder listing overdue and due tasks", any("Task reminder" in n["title"] and "overdue" in n["title"] for n in mine), [n["title"] for n in mine])
ok("project manager got the escalation (3 days overdue, limit 2)", any(n["title"].startswith("Escalated") for n in notes("reminder")))
before = len([n for n in notes("reminder") if n["title"].startswith("Escalated")])
run("task_reminders")
after = len([n for n in notes("reminder") if n["title"].startswith("Escalated")])
ok("the same late task is not escalated twice", after == before, (before, after))

res = run("approval_reminders")
ok("approval reminders ran", res["status"] in ("Success", "Nothing to do"), res)
res = run("timesheet_reminders")
ok("timesheet reminder: people with nothing logged this week are reminded", res["status"] == "Success" and res["items"] >= 1, res)
ok("member got the timesheet reminder", any("Timesheet reminder" in n["title"] for n in notes("reminder", tok=MEMBER)))
res = run("timesheet_missing")
ok("missing timesheets report reached the project manager", res["status"] == "Success" and any("Missing timesheets" in n["title"] for n in notes("reminder")), res)

# ---------------- reports and alerts
res = run("weekly_status_report")
ok("weekly status report sent", res["status"] == "Success" and any(n["title"].startswith("Weekly status") for n in notes("report")), res)

bp = project("Budget", budget=1000)
bt = task(bp, "Costly work", assignee_name="Auto Member", estimated_hours=2)
log_day = today - timedelta(days=1)
s, r = call("POST", "/timesheets/entries", {"task_id": bt["id"], "work_date": log_day.isoformat(), "hours": 3}, tok=MEMBER)
call("POST", "/timesheets/submit", {"week_start": (log_day - timedelta(days=log_day.weekday())).isoformat()}, tok=MEMBER)
eids = [e["id"] for e in call("GET", f"/timesheets/list?project_id={bp}&page_size=50")[1]["detail"]]
s, r = call("POST", "/timesheets/approve", {"entry_ids": eids}, tok=DIRECTOR)
ok("3 h x 500 approved on a 1,000 budget", s == 200 and eids, r)
res = run("budget_alerts")
ok("budget alert: over budget", res["items"] >= 1 and any("over budget" in n["title"] for n in notes("automation")), res)
res = run("budget_alerts")
ok("the same budget alert is not repeated", "Budget" not in res["summary"] or res["items"] == 0, res)

dp = project("Deadline", start=-30, end=3)
task(dp, "Final handover", assignee_name="Auto Member", due_date=d(2))
res = run("deadline_alerts")
ok("deadline alert: ends in 3 days with work open", any("Deadline" in p for p in [res["summary"]]) and any("ends in 3 days" in n["title"] for n in notes("reminder")), res)
ok("deadline alert not repeated", run("deadline_alerts")["items"] == 0)

# ---------------- billing: monthly time & material drafts, invoice reminders
tp = project("Monthly Bill")
tt = task(tp, "Support work", assignee_name="Auto Member", start_date=d(-55))
last_month = today.replace(day=1) - timedelta(days=1)
work_day = last_month.replace(day=15)
s, r = call("POST", "/timesheets/entries", {"task_id": tt["id"], "work_date": work_day.isoformat(), "hours": 4}, tok=MEMBER)
ok("4 h logged last month", s in (200, 201), r)
call("POST", "/timesheets/submit", {"week_start": (work_day - timedelta(days=work_day.weekday())).isoformat()}, tok=MEMBER)
eids = [e["id"] for e in call("GET", f"/timesheets/list?project_id={tp}&page_size=50")[1]["detail"]]
call("POST", "/timesheets/approve", {"entry_ids": eids}, tok=DIRECTOR)
call("PUT", f"/projects/{tp}/settings", {"default_payment_terms": 0})
res = run("monthly_invoices")
tm = [i for i in call("GET", f"/billing/invoices?project_id={tp}&page_size=50")[1]["detail"] if i["invoice_type"] == "Time & Material"]
ok("monthly job drafted last month's T&M invoice (4 h x 500 + GST)", len(tm) == 1 and tm[0]["status"] == "Draft" and float(tm[0]["total"]) == 2360, (res, tm))
res = run("monthly_invoices")
tm2 = [i for i in call("GET", f"/billing/invoices?project_id={tp}&page_size=50")[1]["detail"] if i["invoice_type"] == "Time & Material"]
ok("running it again bills nothing twice", len(tm2) == 1, tm2)

s, r = call("POST", f"/billing/invoices/{tm[0]['id']}/status", {"action": "issue"}, tok=DIRECTOR)
ok("invoice issued (due today, 0 days terms)", s == 200, r)
res = run("invoice_reminders")
ok("invoice reminder: due today", any("is due today" in n["title"] for n in notes("reminder")), res)
ok("invoice reminder not repeated", run("invoice_reminders")["items"] == 0)

# ---------------- sprint completed on its end date
sp_ = project("Sprint")
st = task(sp_, "Sprint work", assignee_name="Auto Member")
s, r = call("POST", f"/projects/{sp_}/sprints", {"name": "Sprint Past", "start_date": d(-10), "end_date": d(-1)})
sid = r.get("data", {}).get("id")
call("POST", f"/sprints/{sid}/tasks", {"task_ids": [st["id"]]})
s, r = call("POST", f"/sprints/{sid}/start")
ok("past sprint started", s == 200, r)
res = run("sprint_auto_complete")
sprint = next(x for x in call("GET", f"/projects/{sp_}/sprints")[1]["detail"] if x["id"] == sid)
ok("sprint completed by automation, unfinished task back to the backlog", sprint["status"] == "Completed" and res["items"] >= 1, (res, sprint["status"]))

# ---------------- recurring tasks
rp2 = project("Recurring")
base = {"project_id": rp2, "title": "Weekly client call", "priority": "High", "assignee_name": "Auto Member", "estimated_hours": 1,
        "frequency": "Weekly", "every": 1, "weekday": today.weekday(), "start_date": d(0), "due_in_days": 1}
for patch, why in [({"frequency": "Weekly", "weekday": None}, "weekly without a weekday"), ({"end_date": d(-1)}, "ends before it starts"),
                   ({"assignee_name": "Not On Team"}, "assignee not on the team"), ({"start_date": d(200)}, "starts after the project ends")]:
    s, r = call("POST", "/recurring-tasks", {**base, **patch})
    ok(f"refused: {why}", s in (409, 422), r)
ok("a Member cannot create recurring tasks (403)", call("POST", "/recurring-tasks", base, tok=MEMBER)[0] == 403)
s, r = call("POST", "/recurring-tasks", base)
ok("weekly rule saved, first run today", s == 201 and r["data"]["next_run_on"] == d(0) and r["data"]["schedule_text"].startswith("Every"), r)
rid = r["data"]["id"]
ok("duplicate name refused", call("POST", "/recurring-tasks", base)[0] == 409)
s, r = call("POST", "/recurring-tasks", {**base, "title": "Monthly gst filing", "frequency": "Monthly", "month_day": 31, "weekday": None,
                                          "start_date": d(1), "due_in_days": 0})
ok("monthly on the 31st: short months use their last day", s == 201 and r["data"]["next_run_on"] is not None, r)
res = run("recurring_tasks")
created = [t for t in call("GET", f"/tasks/list?project_id={rp2}&page_size=50")[1]["detail"] if t["title"].startswith("Weekly client call")]
ok("today's weekly task was created (assignee, due tomorrow, label recurring)", len(created) == 1 and created[0]["assignee_name"] == "Auto Member"
   and created[0]["due_date"] == d(1), (res, created))
rule = next(x for x in call("GET", f"/recurring-tasks?project_id={rp2}")[1]["detail"] if x["id"] == rid)
ok("rule moved on to next week and counts 1 task", rule["next_run_on"] == d(7) and rule["created_count"] == 1, rule)
run("recurring_tasks")
again = [t for t in call("GET", f"/tasks/list?project_id={rp2}&page_size=50")[1]["detail"] if t["title"].startswith("Weekly client call")]
ok("running again the same day creates nothing more", len(again) == 1, again)
ok("assignee was told about the new task", any("assigned" in n["title"] and "Weekly client call" in n["title"] for n in notes("assigned", tok=MEMBER)))
s, r = call("PUT", f"/recurring-tasks/{rid}", {**base, "is_active": False})
ok("paused: no next run", s == 200 and r["data"]["next_run_on"] is None, r)
s, r = call("PUT", f"/recurring-tasks/{rid}", {**base, "is_active": True})
ok("resumed: next run is next week, not today again", s == 200 and r["data"]["next_run_on"] == d(7), r)
ok("deleted", call("DELETE", f"/recurring-tasks/{rid}")[0] == 200)

# ---------------- assignee suggestions
s, r = call("GET", f"/projects/{rp2}/assignee-suggestions?due_date={d(10)}&hours=4")
people = (r.get("detail") or {}).get("people", [])
ok("assignee suggestions list the team, most free time first", s == 200 and len(people) >= 2 and people[0]["free_hours"] >= people[-1]["free_hours"], r)

# ---------------- run history and the scheduler's due check
s, r = call("GET", "/automation/runs?limit=100")
ok("run history records manual and event runs", s == 200 and {"Manual", "Event"} <= {x["trigger"] for x in r["detail"]}, r)

from app.db.session import SessionLocal  # noqa: E402
from app.repositories import automation  # noqa: E402

db = SessionLocal()
try:
    from app.models.automation import AutomationRule  # noqa: E402
    row = db.query(AutomationRule).filter_by(client_id=COMPANY, job_key="deadline_alerts").one()
    row.last_run_on, row.run_time = today - timedelta(days=1), "00:00"
    db.commit()
    due = automation.due_jobs(db, COMPANY, datetime.now())
    ok("a job whose time has passed today is due", "deadline_alerts" in due, due)
    ok("claimed once only (a second server gets False)", automation.claim(db, COMPANY, "deadline_alerts", today) and not automation.claim(db, COMPANY, "deadline_alerts", today))
    ok("after the claim it is no longer due today", "deadline_alerts" not in automation.due_jobs(db, COMPANY, datetime.now()))
finally:
    db.close()

print(f"\n{'ALL PASSED' if not fails else f'{fails} FAILED'}")
sys.exit(1 if fails else 0)
