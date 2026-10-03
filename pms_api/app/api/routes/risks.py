from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import Principal, get_current_principal
from app.db.session import get_db
from app.models.risks import CHANGE_STATUSES, CHANGE_TYPES, ISSUE_SEVERITIES, ISSUE_STATUSES, RISK_CATEGORIES, RISK_STATUSES
from app.repositories import projects as project_repo
from app.repositories import risks as repo
from app.schemas.risks import ChangeRequestIn, DecisionIn, IssueIn, IssueStatusIn, RiskIn, RiskStatusIn

router = APIRouter(tags=["risks"])


def _project(db, principal, project_id):
    project = project_repo.get_project(db, principal, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _found(item, what):
    if item is None:
        raise HTTPException(status_code=404, detail=f"{what} not found")
    return item


def _rule(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except repo.RiskError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/risks/meta")
def risk_meta(principal: Principal = Depends(get_current_principal)):
    return {"detail": {"categories": RISK_CATEGORIES, "risk_statuses": RISK_STATUSES, "severities": ISSUE_SEVERITIES,
                       "issue_statuses": ISSUE_STATUSES, "change_types": CHANGE_TYPES, "change_statuses": CHANGE_STATUSES}}


# ------------------------------------------------------------------------------------ risks


def _risk_list_response(rows):
    open_rows = [r for r in rows if r["status"] in ("Open", "Monitoring")]
    return {
        "detail": rows,
        "stack_values": {
            "count_pg": len(rows),
            "open": len(open_rows),
            "levels": {lvl: sum(1 for r in open_rows if r["level"] == lvl) for lvl in ("High", "Medium", "Low")},
            "review_due": sum(1 for r in rows if r["review_due"]),
            "matrix": repo.risk_matrix(rows),
        },
    }


@router.get("/risks/list")
def all_risks(status: Optional[str] = None, level: Optional[str] = None, search: Optional[str] = None, project_id: Optional[int] = None,
              db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return _risk_list_response(repo.list_risks(db, principal, project_id=project_id, status=status, level=level, search=search))


@router.get("/projects/{project_id}/risks")
def project_risks(project_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    _project(db, principal, project_id)
    return _risk_list_response(repo.list_risks(db, principal, project_id=project_id))


@router.post("/projects/{project_id}/risks", status_code=201)
def create_risk(project_id: int, body: RiskIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    risk = _rule(repo.create_risk, db, principal, _project(db, principal, project_id), body.model_dump())
    return {"detail": f"Risk {risk.risk_key} added", "data": repo.serialize_risks(db, [risk])[0]}


@router.put("/projects/{project_id}/risks/{risk_id}")
def update_risk(project_id: int, risk_id: int, body: RiskIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    project = _project(db, principal, project_id)
    risk = _rule(repo.update_risk, db, principal, project, _found(repo.get_risk(db, principal, project_id, risk_id), "Risk"), body.model_dump())
    return {"detail": f"Risk {risk.risk_key} updated", "data": repo.serialize_risks(db, [risk])[0]}


@router.post("/projects/{project_id}/risks/{risk_id}/status")
def change_risk_status(project_id: int, risk_id: int, body: RiskStatusIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    project = _project(db, principal, project_id)
    risk = _rule(repo.change_risk_status, db, principal, project, _found(repo.get_risk(db, principal, project_id, risk_id), "Risk"), body.status)
    return {"detail": f"{risk.risk_key} is now {risk.status}", "data": repo.serialize_risks(db, [risk])[0]}


@router.post("/projects/{project_id}/risks/{risk_id}/occurred", status_code=201)
def risk_occurred(project_id: int, risk_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    project = _project(db, principal, project_id)
    issue = _rule(repo.risk_occurred, db, principal, project, _found(repo.get_risk(db, principal, project_id, risk_id), "Risk"))
    return {"detail": f"Issue {issue.issue_key} raised from the risk", "data": repo.serialize_issues(db, [issue])[0]}


@router.delete("/projects/{project_id}/risks/{risk_id}")
def delete_risk(project_id: int, risk_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    project = _project(db, principal, project_id)
    risk = _found(repo.get_risk(db, principal, project_id, risk_id), "Risk")
    _rule(repo.delete_risk, db, principal, project, risk)
    return {"detail": f"Risk {risk.risk_key} deleted"}


# ----------------------------------------------------------------------------------- issues


def _issue_list_response(rows):
    open_rows = [i for i in rows if i["status"] in ("Open", "In Progress")]
    return {
        "detail": rows,
        "stack_values": {
            "count_pg": len(rows),
            "open": len(open_rows),
            "critical": sum(1 for i in open_rows if i["severity"] in ("Critical", "High")),
            "overdue": sum(1 for i in rows if i["is_overdue"]),
            "status_counts": {s: sum(1 for i in rows if i["status"] == s) for s in ISSUE_STATUSES},
        },
    }


@router.get("/issues/list")
def all_issues(status: Optional[str] = None, severity: Optional[str] = None, search: Optional[str] = None, project_id: Optional[int] = None,
               db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return _issue_list_response(repo.list_issues(db, principal, project_id=project_id, status=status, severity=severity, search=search))


@router.get("/projects/{project_id}/issues")
def project_issues(project_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    _project(db, principal, project_id)
    return _issue_list_response(repo.list_issues(db, principal, project_id=project_id))


@router.post("/projects/{project_id}/issues", status_code=201)
def create_issue(project_id: int, body: IssueIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    issue = _rule(repo.create_issue, db, principal, _project(db, principal, project_id), body.model_dump())
    return {"detail": f"Issue {issue.issue_key} raised", "data": repo.serialize_issues(db, [issue])[0]}


@router.put("/projects/{project_id}/issues/{issue_id}")
def update_issue(project_id: int, issue_id: int, body: IssueIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    project = _project(db, principal, project_id)
    issue = _rule(repo.update_issue, db, principal, project, _found(repo.get_issue(db, principal, project_id, issue_id), "Issue"), body.model_dump())
    return {"detail": f"Issue {issue.issue_key} updated", "data": repo.serialize_issues(db, [issue])[0]}


@router.post("/projects/{project_id}/issues/{issue_id}/status")
def change_issue_status(project_id: int, issue_id: int, body: IssueStatusIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    project = _project(db, principal, project_id)
    issue = _rule(repo.change_issue_status, db, principal, project, _found(repo.get_issue(db, principal, project_id, issue_id), "Issue"), body.status, body.resolution)
    return {"detail": f"{issue.issue_key} is now {issue.status}", "data": repo.serialize_issues(db, [issue])[0]}


@router.post("/projects/{project_id}/issues/{issue_id}/task", status_code=201)
def create_fix_task(project_id: int, issue_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    project = _project(db, principal, project_id)
    task = _rule(repo.create_fix_task, db, principal, project, _found(repo.get_issue(db, principal, project_id, issue_id), "Issue"))
    return {"detail": f"Fix task {task.task_key} created", "data": {"task_id": task.id, "task_key": task.task_key}}


@router.delete("/projects/{project_id}/issues/{issue_id}")
def delete_issue(project_id: int, issue_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    project = _project(db, principal, project_id)
    issue = _found(repo.get_issue(db, principal, project_id, issue_id), "Issue")
    _rule(repo.delete_issue, db, principal, project, issue)
    return {"detail": f"Issue {issue.issue_key} deleted"}


# -------------------------------------------------------------------------- change requests


def _change_list_response(rows):
    return {
        "detail": rows,
        "stack_values": {
            "count_pg": len(rows),
            "status_counts": {s: sum(1 for c in rows if c["status"] == s) for s in CHANGE_STATUSES},
            "approved_cost": round(sum(c["cost_impact"] or 0 for c in rows if c["status"] == "Approved"), 2),
            "approved_days": sum(c["days_impact"] or 0 for c in rows if c["status"] == "Approved"),
        },
    }


@router.get("/change-requests/list")
def all_changes(status: Optional[str] = None, search: Optional[str] = None, project_id: Optional[int] = None,
                db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return _change_list_response(repo.list_changes(db, principal, project_id=project_id, status=status, search=search))


@router.get("/projects/{project_id}/change-requests")
def project_changes(project_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    _project(db, principal, project_id)
    return _change_list_response(repo.list_changes(db, principal, project_id=project_id))


@router.post("/projects/{project_id}/change-requests", status_code=201)
def create_change(project_id: int, body: ChangeRequestIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    change = _rule(repo.create_change, db, principal, _project(db, principal, project_id), body.model_dump())
    return {"detail": f"Change request {change.cr_key} submitted", "data": repo.serialize_changes(db, [change])[0]}


@router.put("/projects/{project_id}/change-requests/{change_id}")
def update_change(project_id: int, change_id: int, body: ChangeRequestIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    project = _project(db, principal, project_id)
    change = _rule(repo.update_change, db, principal, project, _found(repo.get_change(db, principal, project_id, change_id), "Change request"), body.model_dump())
    return {"detail": f"Change request {change.cr_key} updated", "data": repo.serialize_changes(db, [change])[0]}


@router.post("/projects/{project_id}/change-requests/{change_id}/approve")
def approve_change(project_id: int, change_id: int, body: DecisionIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    project = _project(db, principal, project_id)
    change = _rule(repo.decide_change, db, principal, project, _found(repo.get_change(db, principal, project_id, change_id), "Change request"), True, body.note)
    return {"detail": f"{change.cr_key} approved. {change.applied_summary}", "data": repo.serialize_changes(db, [change])[0]}


@router.post("/projects/{project_id}/change-requests/{change_id}/reject")
def reject_change(project_id: int, change_id: int, body: DecisionIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    project = _project(db, principal, project_id)
    change = _rule(repo.decide_change, db, principal, project, _found(repo.get_change(db, principal, project_id, change_id), "Change request"), False, body.note)
    return {"detail": f"{change.cr_key} rejected", "data": repo.serialize_changes(db, [change])[0]}


@router.delete("/projects/{project_id}/change-requests/{change_id}")
def withdraw_change(project_id: int, change_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    project = _project(db, principal, project_id)
    change = _found(repo.get_change(db, principal, project_id, change_id), "Change request")
    _rule(repo.withdraw_change, db, principal, project, change)
    return {"detail": f"Change request {change.cr_key} withdrawn"}
