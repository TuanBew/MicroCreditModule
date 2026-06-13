from collections.abc import Callable
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Cookie, Depends, Header, Request
from sqlalchemy.orm import Session

from app.core.errors import api_error
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import Feature, User, UserEntitlement


def get_current_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
    creditos_access_token: Annotated[str | None, Cookie()] = None,
) -> User:
    # Primary: httpOnly cookie
    token: str | None = creditos_access_token
    # Fallback: Authorization: Bearer <token> header (backward compat for tests)
    if token is None and authorization is not None:
        if authorization.startswith("Bearer "):
            token = authorization[7:]
    if token is None:
        raise api_error(401, "INVALID_TOKEN", "Authentication token is required.")

    try:
        payload = decode_access_token(token)
        user_id = UUID(str(payload["sub"]))
    except (KeyError, ValueError, jwt.PyJWTError):
        raise api_error(401, "INVALID_TOKEN", "Invalid or expired authentication token.")

    user = db.get(User, user_id)
    if user is None:
        raise api_error(401, "INVALID_TOKEN", "Invalid or expired authentication token.")
    return user


def require_admin(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    if current_user.role != "admin":
        raise api_error(403, "FORBIDDEN", "Admin role is required.")
    return current_user


def require_buyer(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    if current_user.role != "user":
        raise api_error(403, "FORBIDDEN", "User role is required.")
    return current_user


def require_feature(feature_key: str) -> Callable[..., tuple[Feature, User]]:
    """Returns a FastAPI dependency that validates entitlement for feature_key."""

    def _dep(
        db: Annotated[Session, Depends(get_db)],
        user: Annotated[User, Depends(require_buyer)],
    ) -> tuple[Feature, User]:
        feature = db.get(Feature, feature_key)
        if feature is None:
            raise api_error(404, "FEATURE_NOT_FOUND", f"Feature '{feature_key}' does not exist.")
        entitlement = db.get(UserEntitlement, {"user_id": user.id, "feature_key": feature_key})
        if entitlement is None:
            raise api_error(403, "FEATURE_LOCKED", "Feature is not unlocked for this account.")
        return feature, user

    return _dep
