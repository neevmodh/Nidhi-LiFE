from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Role, User
from app.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    user_id = decode_access_token(creds.credentials) if creds else None
    user = db.get(User, user_id) if user_id else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return user


def get_optional_user(
    db: DbSession,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User | None:
    user_id = decode_access_token(creds.credentials) if creds else None
    return db.get(User, user_id) if user_id else None


def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    """Dashboards: the state team, a district officer (their district) or a read-only auditor."""
    if user.role not in (Role.admin, Role.officer, Role.auditor):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return user


def require_reviewer(user: Annotated[User, Depends(get_current_user)]) -> User:
    """The proof review queue: the state team, a district officer, or a reviewer. Auditors can't change anything."""
    if user.role not in (Role.admin, Role.officer, Role.reviewer):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Reviewer access required")
    return user


STAFF_ROLES = (Role.admin, Role.officer, Role.reviewer, Role.auditor)
DISCOM_ROLES = (Role.discom_admin, Role.discom_engineer, Role.discom_auditor)


def require_discom(user: Annotated[User, Depends(get_current_user)]) -> User:
    """The DISCOM console: DISCOM staff for their own company, and the GEDA state team and auditors (read-only)."""
    if user.role not in (*DISCOM_ROLES, Role.admin, Role.auditor):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "DISCOM access required")
    return user


def require_discom_engineer(user: Annotated[User, Depends(get_current_user)]) -> User:
    """Changing things in the DISCOM console (raising outages, resolving flags). Auditors only read."""
    if user.role not in (Role.discom_admin, Role.discom_engineer):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "DISCOM engineer access required")
    return user


def discom_scope(user: User, requested: str | None = None) -> str | None:
    """The distribution company a user may see: their own for DISCOM staff, any (or all, None) for GEDA."""
    if user.role in DISCOM_ROLES:
        if requested is not None and requested != user.discom:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only see your own distribution company")
        return user.discom
    return requested


def district_scope(user: User, requested: int | None = None) -> int | None:
    """The district a GEDA user may see: any (or all, None) for the state team and auditors,
    only their own for officers and for reviewers who were given a district."""
    if user.role in (Role.admin, Role.auditor) or (user.role == Role.reviewer and user.district_id is None):
        return requested
    if requested is not None and requested != user.district_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only see your own district")
    return user.district_id


CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(require_admin)]
ReviewerUser = Annotated[User, Depends(require_reviewer)]
DiscomUser = Annotated[User, Depends(require_discom)]
DiscomEngineer = Annotated[User, Depends(require_discom_engineer)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
