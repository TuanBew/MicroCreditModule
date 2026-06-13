from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import bcrypt
import jwt

from app.core.config import get_settings

if TYPE_CHECKING:
    from app.models import User


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(subject: str, email: str, role: str) -> str:
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expires_minutes)
    return jwt.encode(
        {"sub": subject, "email": email, "role": role, "exp": expires_at},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


@dataclass
class AuthResult:
    access_token: str
    csrf_token: str
    user: "User"


def create_auth_result(user: "User") -> AuthResult:
    from app.core.csrf import generate_csrf_token

    settings = get_settings()
    access_token = create_access_token(
        subject=str(user.id),
        email=user.email,
        role=user.role,
    )
    csrf_token = generate_csrf_token()
    return AuthResult(access_token=access_token, csrf_token=csrf_token, user=user)
