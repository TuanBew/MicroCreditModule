from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.errors import api_error
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import User


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
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
