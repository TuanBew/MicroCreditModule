from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import get_current_user, get_db
from app.models import User
from app.schemas.auth import LoginRequest, SignupRequest, TokenResponse, UserRead
from app.services.auth_service import login as login_user
from app.services.auth_service import signup as signup_user


router = APIRouter(tags=["auth"])


def _set_auth_cookies(response: Response, token_response: TokenResponse) -> None:
    settings = get_settings()
    response.set_cookie(
        "creditos_access_token",
        token_response.access_token,
        httponly=True,
        samesite=settings.cookie_samesite,
        secure=settings.cookie_secure,
        max_age=settings.access_token_expires_minutes * 60,
    )
    response.set_cookie(
        "creditos_csrf_token",
        token_response.csrf_token,
        httponly=False,
        samesite=settings.cookie_samesite,
        secure=settings.cookie_secure,
        max_age=settings.access_token_expires_minutes * 60,
    )


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(
    request: SignupRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> TokenResponse:
    token_response = signup_user(db, request)
    _set_auth_cookies(response, token_response)
    return token_response


@router.post("/login", response_model=TokenResponse)
def login(
    request: LoginRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> TokenResponse:
    token_response = login_user(db, request)
    _set_auth_cookies(response, token_response)
    return token_response


@router.get("/me", response_model=UserRead)
def me(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    return current_user
