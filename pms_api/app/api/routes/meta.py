from fastapi import APIRouter

from app.core.roles import ACTIONS, ROLE_MATRIX, ROLES

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/roles")
def list_roles():
    """Default PMS roles and their action matrix (starting point for Super Admin role setup)."""
    return {"actions": ACTIONS, "roles": ROLES, "matrix": ROLE_MATRIX}
