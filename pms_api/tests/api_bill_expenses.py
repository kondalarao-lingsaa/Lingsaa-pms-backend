"""API checks for invoicing billable expenses on Time & Material invoices."""
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


fails = 0


def ok(name, cond, extra=""):
    global fails
    fails += 0 if cond else 1
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {extra}"))


today = date.today()
d = lambda n: (today + timedelta(days=n)).isoformat()  # noqa: E731
NAME = "Bill Expenses Api Check"
for p in call("GET", f"/projects/list?search={NAME.replace(' ', '%20')}&page_size=20")[1].get("detail") or []:
    if p["project_name"] == NAME:
        call("DELETE", f"/projects/{p['id']}")
p = call("POST", "/projects/create", {"project_name": NAME, "project_type": "Time & Material", "customer_name": "Acme Retail", "customer_contact_name": "Ravi Kumar",
                                      "customer_mobile": "9876543210", "start_date": d(-40), "end_date": d(60), "budget": 100000, "project_manager_name": "Priya Shah"})[1]["data"]
pid = p["id"]
for st in ("Pending Approval", "Approved", "Active"):
    call("POST", f"/projects/{pid}/status", {"status": st})
call("POST", f"/projects/{pid}/members", {"member_name": "Dev User", "user_id": 1, "role": "Developer", "allocation_pct": 10, "hourly_rate": 500})
task = call("POST", "/tasks/create", {"project_id": pid, "title": "Build the api", "assignee_name": "Dev User", "estimated_hours": 8})[1]["data"]
log_day = today if today.weekday() < 5 else today - timedelta(days=today.weekday() - 4)
te = call("POST", "/timesheets/entries", {"task_id": task["id"], "work_date": log_day.isoformat(), "hours": 4})[1]["data"]
call("POST", "/timesheets/submit", {"week_start": (log_day - timedelta(days=log_day.weekday())).isoformat()})
call("POST", "/timesheets/approve", {"entry_ids": [te["id"]]}, token=mgr)

mk = lambda **kw: call("POST", "/expenses", {"project_id": pid, "expense_date": d(0), "submit": True, **kw})[1]["data"]  # noqa: E731
hotel = mk(category="Food & Stay", description="Hotel at client city", amount=3000, billable=True)
lunch = mk(category="Food & Stay", description="Team lunch", amount=1000, billable=False)
old = mk(category="Travel", description="Flight for kick off", amount=6000, billable=True, expense_date=d(-35))
waiting = call("POST", "/expenses", {"project_id": pid, "expense_date": d(0), "category": "Hardware", "description": "Test phone", "amount": 9000, "billable": True, "submit": True})[1]["data"]
call("POST", "/expenses/approve", {"ids": [hotel["id"], lunch["id"], old["id"]]}, token=mgr)

s, r = call("GET", f"/billing/billable?project_id={pid}")
b = r.get("detail", {})
ok("billable summary: 2 billable approved expenses (9000), not the lunch or the waiting phone", s == 200 and b["unbilled_expenses"] == 2 and b["unbilled_expense_amount"] == 9000, b)
ok("unbilled period starts at the oldest billable expense", b["unbilled_from"] == d(-35), b)

s, r = call("POST", "/billing/invoices", {"project_id": pid, "invoice_type": "Time & Material", "period_from": d(-7), "period_to": d(0)})
inv = r.get("data", {})
ok("T&M invoice for the last week: hours line + the hotel only", s == 201 and len(inv.get("lines", [])) == 2 if "lines" in inv else s == 201, r)
s, r = call("GET", f"/billing/invoices/{inv['id']}")
lines = r["detail"]["lines"]
ok("lines: Dev User 4 hrs x 500 and 'Expense …: Food & Stay - Hotel at client city' 3000", any(l["unit"] == "hrs" and l["amount"] == 2000 for l in lines) and any(l["description"].startswith(f"Expense {hotel['expense_key']}") and l["amount"] == 3000 for l in lines), lines)
ok("subtotal 5000 + 18% GST = 5900", r["detail"]["subtotal"] == 5000 and r["detail"]["total"] == 5900, r["detail"])
s, r = call("GET", f"/expenses?project_id={pid}&page_size=20")
by = {e["expense_key"]: e for e in r["detail"]}
ok("the hotel shows its invoice number; the flight (outside the period) does not", by[hotel["expense_key"]]["invoice_no"] == inv["invoice_no"] and by[old["expense_key"]]["invoice_no"] is None, by)

s, r = call("POST", "/billing/invoices", {"project_id": pid, "invoice_type": "Time & Material", "period_from": d(-7), "period_to": d(0)})
ok("same period again: nothing left to bill -> 409", s == 409 and "billable expenses" in r["detail"], r)
s, r = call("POST", "/billing/invoices", {"project_id": pid, "invoice_type": "Time & Material", "period_from": d(-38), "period_to": d(-30), "include_expenses": False})
ok("expenses switched off and no hours in the period -> 409", s == 409, r)
s, r = call("POST", "/billing/invoices", {"project_id": pid, "invoice_type": "Time & Material", "period_from": d(-38), "period_to": d(-30)})
inv2 = r.get("data", {})
ok("an expenses-only invoice works (flight 6000)", s == 201 and inv2["subtotal"] == 6000, r)

s, r = call("POST", f"/billing/invoices/{inv['id']}/status", {"action": "cancel"})
ok("cancel the first invoice", s == 200, r)
s, r = call("GET", f"/billing/billable?project_id={pid}")
ok("after cancelling, the hotel is billable again (and the hours)", r["detail"]["unbilled_expenses"] == 1 and r["detail"]["unbilled_expense_amount"] == 3000 and r["detail"]["unbilled_hours"] == 4, r["detail"])

call("POST", f"/billing/invoices/{inv2['id']}/status", {"action": "cancel"})
for t in call("GET", f"/tasks/list?project_id={pid}&page_size=50")[1].get("detail") or []:
    call("DELETE", f"/tasks/{t['id']}")
call("DELETE", f"/projects/{pid}")
print("\nALL PASSED" if not fails else f"\n{fails} FAILED")
