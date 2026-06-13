from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import api_error
from app.core.security import create_auth_result, hash_password, verify_password
from app.models import User, UserCredit
from app.schemas.auth import LoginRequest, SignupRequest, TokenResponse


def normalize_email(email: str) -> str:
    return email.lower()


def derive_initials(email: str) -> str:
    local_part = email.split("@", 1)[0]
    characters = "".join(character for character in local_part if character.isalnum())
    return (characters[:2] or "US").upper()


def _token_response(user: User) -> TokenResponse:
    result = create_auth_result(user)
    return TokenResponse(
        access_token=result.access_token,
        csrf_token=result.csrf_token,
        user=user,
    )


def _user_already_exists_error() -> Exception:
    return api_error(409, "USER_ALREADY_EXISTS", "A user with this email already exists.")


def signup(db: Session, request: SignupRequest) -> TokenResponse:
    email = normalize_email(str(request.email))
    existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if existing is not None:
        raise _user_already_exists_error()

    user = User(
        email=email,
        password_hash=hash_password(request.password),
        role="user",
        initials=derive_initials(email),
    )
    db.add(user)
    try:
        db.flush()
        db.add(UserCredit(user_id=user.id, balance=0))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _user_already_exists_error() from exc
    db.refresh(user)
    return _token_response(user)


def login(db: Session, request: LoginRequest) -> TokenResponse:
    email = normalize_email(str(request.email))
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None or not verify_password(request.password, user.password_hash):
        raise api_error(401, "INVALID_CREDENTIALS", "Invalid email or password.")
    return _token_response(user)
