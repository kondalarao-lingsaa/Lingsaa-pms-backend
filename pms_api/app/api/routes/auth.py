"""The PMS's own login (email + password), used until the MASTER login is connected.

- POST /api/auth/login: email + password of a user in Settings > Users & Roles -> a signed login token.
  After 5 wrong passwords an email is locked for 10 minutes from that address.
- POST /api/auth/change-password: the signed-in person changes their own password (same 5-try limit).
When the PMS moves to the MASTER login, set DEMO_LOGIN_ENABLED=false: the screens, roles and approvals stay the same.
"""
import time
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from jose import jwt
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core import roles
from app.core.config import settings
from app.core.passwords import hash_password, password_problem, verify_password
from app.core.security import Principal, get_current_principal
from app.db.session import get_db
from app.models.access import UserRole

router = APIRouter(prefix="/auth", tags=["auth"])
# A separate router for change-password: it needs the normal signed-in checks (main.py adds them).
account_router = APIRouter(prefix="/auth", tags=["auth"])

MAX_FAILURES = 5
LOCK_SECONDS = 600
MAX_TRACKED = 10000  # keys kept at most, so trying endless different emails cannot grow memory without limit
# Recent wrong passwords (per server process): "login|<address>|<email>" -> times, "password|<company>|<user>" -> times.
# A login is locked per address + email, so a stranger elsewhere cannot keep someone else's account locked.
_failures = defaultdict(list)


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=150)
    password: str = Field(min_length=1, max_length=128)


def _locked(key: str) -> bool:
    now = time.time()
    recent = [t for t in _failures.get(key, []) if now - t < LOCK_SECONDS]
    if recent:
        _failures[key] = recent
    else:
        _failures.pop(key, None)
    return len(recent) >= MAX_FAILURES


def _failed(key: str) -> int:
    """Records a wrong password; returns how many tries are left."""
    if len(_failures) >= MAX_TRACKED and key not in _failures:
        now = time.time()
        for old in [k for k, times in _failures.items() if not times or now - times[-1] >= LOCK_SECONDS]:
            del _failures[old]
        if len(_failures) >= MAX_TRACKED:
            # Still full: forget the keys that failed longest ago.
            for old in sorted(_failures, key=lambda k: _failures[k][-1])[: MAX_TRACKED // 10]:
                del _failures[old]
    _failures[key].append(time.time())
    return MAX_FAILURES - len(_failures[key])


def _client_address(request: Request) -> str:
    return request.client.host if request.client else "-"


def issue_token(row: UserRole) -> str:
    claims = {"client_id": row.client_id, "user_id": row.user_id, "username": row.user_name, "email": row.email,
              "exp": int(time.time()) + settings.LOGIN_HOURS * 3600}
    return jwt.encode(claims, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    if not settings.DEMO_LOGIN_ENABLED:
        raise HTTPException(status_code=404, detail="Sign in through the Lingsaa login")
    email = body.email.strip().lower()
    key = f"login|{_client_address(request)}|{email}"
    if _locked(key):
        raise HTTPException(status_code=429, detail="Too many wrong passwords. Try again in 10 minutes")
    row = db.query(UserRole).filter(func.lower(UserRole.email) == email, UserRole.password_hash != None).first()  # noqa: E711
    if row is None or not verify_password(body.password, row.password_hash):
        left = _failed(key)
        raise HTTPException(status_code=401, detail="Email or password is wrong" + (f". {left} tries left" if 0 < left <= 2 else ""))
    if not row.is_active:
        raise HTTPException(status_code=403, detail="Your PMS access is switched off. Ask your PMS Admin")
    _failures.pop(key, None)
    row.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return {
        "detail": {
            "token": issue_token(row), "user_id": row.user_id, "username": row.user_name, "client_id": row.client_id,
            "role": row.role, "role_title": roles.ROLE_TITLES.get(row.role, row.role),
            "home": "portal/" if row.role == roles.CLIENT else "dashboard/",
        }
    }


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


@account_router.post("/change-password")
def change_password(body: ChangePasswordIn, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    # The same limit as signing in, so a stolen session cannot be used to guess the password.
    key = f"password|{principal.client_id}|{principal.user_id}"
    if _locked(key):
        raise HTTPException(status_code=429, detail="Too many wrong passwords. Try again in 10 minutes")
    row = db.query(UserRole).filter(UserRole.client_id == principal.client_id, UserRole.user_id == principal.user_id).one_or_none()
    if row is None or not verify_password(body.current_password, row.password_hash):
        left = _failed(key)
        raise HTTPException(status_code=409, detail="Your current password is wrong" + (f". {left} tries left" if 0 < left <= 2 else ""))
    _failures.pop(key, None)
    problem = password_problem(body.new_password)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    if body.new_password == body.current_password:
        raise HTTPException(status_code=422, detail="Choose a password different from the current one")
    row.password_hash = hash_password(body.new_password)
    db.commit()
    return {"detail": "Password changed. Use it next time you sign in"}
