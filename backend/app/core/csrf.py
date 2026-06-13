import secrets

from fastapi import Header, HTTPException, Request

_HEADER = "X-CSRF-Token"


def generate_csrf_token() -> str:
    return secrets.token_hex(32)


def verify_csrf(
    request: Request,
    x_csrf_token: str | None = Header(default=None),
) -> None:
    """Dependency: compare X-CSRF-Token header to creditos_csrf_token cookie."""
    cookie_val = request.cookies.get("creditos_csrf_token")
    if not cookie_val or not x_csrf_token:
        raise HTTPException(status_code=403, detail="CSRF token missing")
    if not secrets.compare_digest(cookie_val, x_csrf_token):
        raise HTTPException(status_code=403, detail="CSRF token mismatch")
