import time
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from jose import jwt
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core import roles
from app.core.config import settings
from app.core.security import Principal, get_current_principal
from app.db.session import get_db
from app.models.access import UserRole
from app.models.projects import Project
from app.repositories import approvals
from app.schemas.rules import EMAIL_REGEX, utc_iso

router = APIRouter(tags=["access"])


# ------------------------------------------------------------------------------ who am I


@router.get("/me")
def me(principal: Principal = Depends(get_current_principal)):
    """The signed-in person's PMS role and what it allows; the screens use it to show only what the person can use."""
    return {
        "detail": {
            "user_id": principal.user_id,
            "user_name": principal.user_name,
            "client_id": principal.client_id,
            "role": principal.role_key,
            "role_title": principal.role_title,
            "customer_name": principal.customer_name,
            "permissions": roles.ROLE_MATRIX.get(principal.role_key, {}),
            "sees_all_projects": principal.role_key in roles.SEE_ALL_PROJECTS,
        }
    }


@router.get("/meta/roles")
def list_roles():
    return {"detail": {"actions": roles.ACTIONS, "groups": roles.GROUPS, "roles": roles.ROLES, "matrix": roles.ROLE_MATRIX}}


# ------------------------------------------------------------------------------ Settings > Users & Roles


class UserRoleIn(BaseModel):
    user_id: int = Field(ge=1)
    user_name: str = Field(min_length=2, max_length=200)
    email: Optional[str] = Field(None, max_length=150)
    role: str
    customer_name: Optional[str] = Field(None, max_length=200)
    is_active: bool = True

    @field_validator("user_name", "customer_name")
    @classmethod
    def _clean(cls, v):
        return " ".join(v.split()) if v else v

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        v = (v or "").strip()
        if v and not EMAIL_REGEX.fullmatch(v):
            raise ValueError("Please Enter a valid Email")
        return v or None

    @field_validator("role")
    @classmethod
    def _role(cls, v):
        if v not in roles.ROLE_KEYS:
            raise ValueError("Please Select Role")
        return v


def _user_out(r: UserRole) -> dict:
    return {"id": r.id, "user_id": r.user_id, "user_name": r.user_name, "email": r.email, "role": r.role,
            "role_title": roles.ROLE_TITLES.get(r.role, r.role), "customer_name": r.customer_name, "is_active": r.is_active,
            "updated_at": utc_iso(r.updated_at)}


def _check_admin_left(db, principal, row: UserRole, new_role, new_active):
    """The company always keeps at least one active Admin, so nobody is locked out of Settings."""
    if row.role == roles.ADMIN and row.is_active and (new_role != roles.ADMIN or not new_active):
        others = db.query(UserRole.id).filter(UserRole.client_id == principal.client_id, UserRole.id != row.id,
                                              UserRole.role == roles.ADMIN, UserRole.is_active == True).first()  # noqa: E712
        if others is None:
            raise HTTPException(status_code=409, detail=f"{row.user_name} is the only Admin. Make someone else Admin first")


def _validate(db, principal, body: UserRoleIn):
    if body.role == roles.CLIENT and not body.customer_name:
        raise HTTPException(status_code=422, detail="Please Select the Client's company", headers=None)
    if body.role != roles.CLIENT:
        body.customer_name = None


@router.get("/settings/users")
def list_users(db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    rows = db.query(UserRole).filter(UserRole.client_id == principal.client_id).order_by(func.lower(UserRole.user_name)).all()
    customers = [c for (c,) in db.query(Project.customer_name).filter(
        Project.client_id == principal.client_id, Project.is_deleted == False, Project.customer_name != None  # noqa: E712,E711
    ).distinct().order_by(Project.customer_name) if c]
    return {"detail": {"users": [_user_out(r) for r in rows], "roles": roles.ROLES, "customers": customers}}


@router.post("/settings/users", status_code=201)
def add_user(body: UserRoleIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    _validate(db, principal, body)
    if db.query(UserRole.id).filter(UserRole.client_id == principal.client_id, UserRole.user_id == body.user_id).first():
        raise HTTPException(status_code=409, detail=f"User {body.user_id} already has a PMS role. Edit it instead")
    row = UserRole(client_id=principal.client_id, **body.model_dump(), created_by=principal.user_id, updated_by=principal.user_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"detail": f"{row.user_name} is now {roles.ROLE_TITLES[row.role]}", "data": _user_out(row)}


def _row(db, principal, role_id) -> UserRole:
    row = db.query(UserRole).filter(UserRole.client_id == principal.client_id, UserRole.id == role_id).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    return row


@router.put("/settings/users/{role_id}")
def update_user(role_id: int, body: UserRoleIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    row = _row(db, principal, role_id)
    _validate(db, principal, body)
    if body.user_id != row.user_id:
        raise HTTPException(status_code=409, detail="The user id cannot change. Remove this user and add the right one")
    _check_admin_left(db, principal, row, body.role, body.is_active)
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    row.updated_by = principal.user_id
    db.commit()
    db.refresh(row)
    return {"detail": f"{row.user_name} saved as {roles.ROLE_TITLES[row.role]}" + ("" if row.is_active else " (access off)"), "data": _user_out(row)}


@router.delete("/settings/users/{role_id}")
def remove_user(role_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    row = _row(db, principal, role_id)
    _check_admin_left(db, principal, row, None, False)
    name = row.user_name
    db.delete(row)
    db.commit()
    return {"detail": f"{name} removed. Without a role they are a Member"}


# ------------------------------------------------------------------------------ Settings > Approval Rules


class ApprovalLimitsIn(BaseModel):
    pm_approval_limit: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    high_approval_limit: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    expense_approval_limit: Decimal = Field(gt=0, max_digits=16, decimal_places=2)


@router.put("/settings/approvals")
def save_approval_limits(body: ApprovalLimitsIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    try:
        approvals.save_limits(db, principal, body.pm_approval_limit, body.high_approval_limit, body.expense_approval_limit)
    except approvals.ApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"detail": "Approval rules saved. They apply to the next approval", "data": approvals.limits_out(db, principal.client_id)}


# ------------------------------------------------------------------------------ approvals inbox


@router.get("/approvals")
def approvals_inbox(db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return {"detail": approvals.inbox(db, principal)}


@router.get("/approvals/history")
def approval_history(
    entity_type: str = Query(..., pattern="^(project|change|expense|milestone)$"), entity_id: int = Query(..., ge=1),
    db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal),
):
    return {"detail": approvals.history(db, principal, entity_type, entity_id)}


# ------------------------------------------------------------------------------ test logins (development only)


class LoginAsIn(BaseModel):
    user_id: int = Field(ge=1)


@router.post("/dev/login-as")
def login_as(body: LoginAsIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    """DEVELOPMENT ONLY: an Admin gets a login token for another user of the same company, to test each role.
    Switched off in production and whenever real login checking is on."""
    if settings.is_production or settings.JWT_ENFORCE_SIGNATURE:
        raise HTTPException(status_code=404, detail="Not available")
    row = db.query(UserRole).filter(UserRole.client_id == principal.client_id, UserRole.user_id == body.user_id).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Give this user a role first")
    claims = {"client_id": principal.client_id, "user_id": row.user_id, "username": row.user_name, "exp": int(time.time()) + 8 * 3600}
    token = jwt.encode(claims, settings.JWT_SECRET or "dev", algorithm=settings.JWT_ALGORITHM)
    return {"detail": {"token": token, "user_id": row.user_id, "username": row.user_name, "client_id": principal.client_id,
                       "role_title": roles.ROLE_TITLES[row.role]}}
