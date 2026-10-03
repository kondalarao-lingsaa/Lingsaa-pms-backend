"""API checks for Project Settings and expense receipts."""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import date, timedelta

sys.path.insert(0, os.getcwd())
from jose import jwt  # noqa: E402

from app.core.config import settings  # noqa: E402

ROOT = r"C:\Users\kondalarao\Documents\LINGSAA_PMS"
dev = re.search(r"NEXT_PUBLIC_PMS_DEV_TOKEN=(.*)", open(os.path.join(ROOT, "frontend", ".env.local")).read()).group(1).strip()
mgr = jwt.encode({"client_id": 900001, "user_id": 2, "username": "qa.manager", "role": "admin", "exp": int(time.time()) + 3600}, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
B = "http://localhost:8000/api"


def call(method, path, body=None, token=None):
    req = urllib.request.Request(B + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + (token or dev), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def upload(path, file_name, data, token=None):
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{file_name}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(B + path, method="POST", data=body, headers={"Authorization": "Bearer " + (token or dev), "Content-Type": f"multipart/form-data; boundary={boundary}"})
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


today = date.today()
d = lambda n: (today + timedelta(days=n)).isoformat()  # noqa: E731
NAME = "Project Settings Api Check"
for p in call("GET", f"/projects/list?search={NAME.replace(' ', '%20')}&page_size=20")[1].get("detail") or []:
    if p["project_name"] == NAME:
        call("DELETE", f"/projects/{p['id']}")
p = call("POST", "/projects/create", {"project_name": NAME, "project_type": "Internal", "start_date": d(-40), "end_date": d(60), "budget": 10000, "project_manager_name": "Priya Shah"})[1]["data"]
pid = p["id"]
for st in ("Pending Approval", "Approved", "Active"):
    call("POST", f"/projects/{pid}/status", {"status": st})
call("POST", f"/projects/{pid}/members", {"member_name": "Dev User", "user_id": 1, "role": "Developer", "allocation_pct": 10, "hourly_rate": 500})

# ---------------- settings: defaults, validation, save
s, r = call("GET", f"/projects/{pid}/settings")
ok("new project uses the defaults (Medium, alert 80%, GST 18%, 30 days)", s == 200 and r["detail"]["is_default"] and r["detail"]["budget_alert_pct"] == 80 and r["detail"]["default_tax_pct"] == 18, r)
for body, why in [({"budget_alert_pct": 40}, "alert below 50%"), ({"timesheet_lock_days": 0}, "lock 0 days"), ({"default_task_priority": "Urgent"}, "unknown priority"),
                  ({"task_labels": ["a,b"]}, "label with a comma"), ({"default_tax_pct": 40}, "GST above 28%")]:
    s, r = call("PUT", f"/projects/{pid}/settings", body)
    ok(f"refused: {why} -> 422", s == 422, r)
s, r = call("PUT", f"/projects/{pid}/settings", {"default_task_priority": "High", "default_estimate_hours": 6, "task_labels": ["UI", "backend", "ui", " api "],
                                                 "timesheet_lock_days": 7, "budget_alert_pct": 60, "receipt_required_above": 2000, "default_tax_pct": 12, "default_payment_terms": 15})
ok("saved; labels cleaned (lower case, no duplicates, trimmed)", s == 200 and r["data"]["task_labels"] == ["ui", "backend", "api"] and r["data"]["default_task_priority"] == "High" and not r["data"]["is_default"], r)

# ---------------- timesheet lock
task = call("POST", "/tasks/create", {"project_id": pid, "title": "Build the api", "assignee_name": "Dev User", "estimated_hours": 8})[1]["data"]
s, r = call("POST", "/timesheets/entries", {"task_id": task["id"], "work_date": d(-10), "hours": 2})
ok("hours 10 days back are locked (lock = 7 days)", s == 409 and "locked" in r["detail"], r)
log_day = today if today.weekday() < 5 else today - timedelta(days=today.weekday() - 4)
s, r = call("POST", "/timesheets/entries", {"task_id": task["id"], "work_date": log_day.isoformat(), "hours": 4})
ok("recent hours are still fine", s == 200, r)

# ---------------- budget alert
call("POST", "/timesheets/submit", {"week_start": (log_day - timedelta(days=log_day.weekday())).isoformat()})
call("POST", "/timesheets/approve", {"entry_ids": [r["data"]["id"]]}, token=mgr)
e_big = call("POST", "/expenses", {"project_id": pid, "category": "Hardware", "description": "Laptop for tester", "amount": 4500, "expense_date": d(0)})[1]["data"]

# ---------------- receipts
s, r = call("POST", f"/expenses/{e_big['id']}/submit")
ok("₹4,500 > ₹2,000 limit: submit refused without a receipt", s == 409 and "needs a receipt" in r["detail"], r)
s, r = call("POST", "/expenses", {"project_id": pid, "category": "Hardware", "description": "Monitor", "amount": 2500, "expense_date": d(0), "submit": True})
ok("save + submit in one go is refused too when a receipt is needed", s == 409 and "needs a receipt" in r["detail"], r)
s, r = upload(f"/expenses/{e_big['id']}/receipt", "bill.exe", b"MZ\x90\x00binary")
ok("an executable as receipt is refused (422)", s == 422, r)
pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
s, r = upload(f"/expenses/{e_big['id']}/receipt", "laptop bill.pdf", pdf)
ok("PDF receipt attached", s == 200 and r["data"]["receipt_file_name"] == "laptop bill.pdf" and r["data"]["receipt_document_id"], r)
first_doc = r["data"]["receipt_document_id"]
s, r = upload(f"/expenses/{e_big['id']}/receipt", "laptop bill v2.pdf", pdf)
ok("a new upload replaces it (new version of the same document)", s == 200 and r["data"]["receipt_document_id"] != first_doc, r)
s, r = call("GET", f"/documents/list?project_id={pid}&category=Receipt")
docs = r.get("detail") or []
ok("the receipt is in Documents under category Receipt (latest version only listed)", len(docs) == 1 and docs[0]["version"] == 2, docs)
s, r = upload(f"/expenses/{e_big['id']}/receipt", "x.pdf", pdf, token=mgr)
ok("someone else cannot attach a receipt to my expense", s in (403, 409), r)  # 403: their role cannot edit expenses
s, r = call("POST", f"/expenses/{e_big['id']}/submit")
ok("with the receipt the expense can be submitted", s == 200 and r["data"]["status"] == "Submitted", r)
s, r = upload(f"/expenses/{e_big['id']}/receipt", "late.pdf", pdf)
ok("a submitted expense's receipt is locked", s == 409, r)
call("POST", "/expenses/approve", {"ids": [e_big["id"]]}, token=mgr)

s, r = call("GET", f"/projects/{pid}/budget")
b = r["detail"]
ok("budget alert: 2000 labour + 4500 expense = 65% of 10000 -> At risk (alert at 60%)", b["actual_cost"] == 6500 and b["health"] == "At risk" and "alerts at 60%" in b["health_reason"], b)

small = call("POST", "/expenses", {"project_id": pid, "category": "Travel", "description": "Bus ticket", "amount": 150, "expense_date": d(0)})[1]["data"]
upload(f"/expenses/{small['id']}/receipt", "ticket.pdf", pdf)
s, r = call("DELETE", f"/expenses/{small['id']}/receipt")
ok("a draft's receipt can be removed", s == 200, r)
s, r = call("POST", f"/expenses/{small['id']}/submit")
ok("small expenses (₹150) need no receipt", s == 200, r)

for t in call("GET", f"/tasks/list?project_id={pid}&page_size=50")[1].get("detail") or []:
    call("DELETE", f"/tasks/{t['id']}")
call("DELETE", f"/projects/{pid}")
print("\nALL PASSED" if not fails else f"\n{fails} FAILED")
