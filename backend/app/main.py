from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import get_settings
from app.core.errors import ApiError, api_error_handler, validation_error_handler
from app.core.rate_limit import limiter
from app.routers.auth import router as auth_router
from app.routers.feature_runs import router as feature_runs_router
from app.routers.features import router as features_router
from app.routers.packages import router as packages_router
from app.routers.purchases import router as purchases_router
from app.routers.wallet import router as wallet_router


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="CreditOS API", version="0.1.0")

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth_router, prefix="/api/v1/auth")
    app.include_router(features_router, prefix="/api/v1/features")
    app.include_router(feature_runs_router, prefix="/api/v1/features")
    app.include_router(packages_router, prefix="/api/v1/packages")
    app.include_router(purchases_router, prefix="/api/v1/purchases")
    app.include_router(wallet_router, prefix="/api/v1/wallet")

    return app


app = create_app()
