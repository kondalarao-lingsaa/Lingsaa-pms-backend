import logging

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwt

from app.core.config import settings

logger = logging.getLogger("pms.security")
bearer_scheme = HTTPBearer(auto_error=False)
_reported = False


class Principal:
    """Identity of the caller: company (client_id), user and role."""

    def __init__(self, client_id, user_id, user_name, role, is_superadmin, raw_claims):
        self.client_id = client_id
        self.user_id = user_id
        self.user_name = user_name
        self.role = role
        self.is_superadmin = is_superadmin
        self.raw_claims = raw_claims
        # Filled in per request by access.authorize from Settings > Users & Roles.
        self.role_key = None
        self.role_title = None
        self.customer_name = None
        self.role_row_id = None
        self.permissions = None


def decode_token(token: str) -> dict:
    try:
        claims = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        _report(verified=True, claims=claims)
        return claims
    except ExpiredSignatureError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired") from exc
    except JWTError as exc:
        if settings.JWT_ENFORCE_SIGNATURE:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
        # TEMPORARY (local dev): the MASTER service's signing secret is not confirmed yet.
        # Accept the token unverified and log it, so a wrong secret cannot log users out of the whole app.
        claims = jwt.get_unverified_claims(token)
        _report(verified=False, claims=claims)
        return claims


def _report(verified: bool, claims: dict):
    global _reported
    if not _reported:
        _reported = True
        log = logger.info if verified else logger.warning
        log("JWT signature %s with configured JWT_SECRET; token claim keys: %s", "verified" if verified else "NOT verified", sorted(claims.keys()))


def _claim(claims: dict, *names):
    for name in names:
        if claims.get(name) not in (None, ""):
            return claims[name]
    return None


def get_current_principal(
    request: Request, credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)
) -> Principal:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    claims = decode_token(credentials.credentials)

    client_id = _claim(claims, "client_id", "clientId")
    user_id = _claim(claims, "user_id", "userId", "sub")
    user_name = _claim(claims, "user_name", "username", "name")

    # TEMPORARY: until the token is confirmed to carry client_id/user_id, fall back to the
    # query params the root app already sends on every call (same as its Finance APIs).
    if settings.ALLOW_TENANT_FROM_QUERY:
        params = request.query_params
        client_id = client_id or params.get("client_id")
        user_id = user_id or params.get("user_id")
        user_name = user_name or params.get("user_name")

    if client_id in (None, ""):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No company (client_id) on this session")

    return Principal(
        client_id=int(client_id),
        user_id=int(user_id) if str(user_id or "").isdigit() else None,
        user_name=user_name,
        role=_claim(claims, "role", "role_name"),
        is_superadmin=str(_claim(claims, "is_superadmin", "isSuperAdmin") or "0") in ("1", "true", "True"),
        raw_claims=claims,
    )
