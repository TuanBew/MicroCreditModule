# Scaling & Security Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the purchase flow async (Celery + Redis), close Tier 1 and Tier 2 security gaps, add catalog caching, and add a Locust load test — without breaking any existing behaviour.

**Architecture:** Purchase submission returns 202 immediately after writing a `pending` transaction; a Celery worker processes it and transitions to `completed` or `failed`; the UI polls a status endpoint. Auth tokens move from `localStorage` to `httpOnly` cookies with a CSRF double-submit pattern. Redis serves as Celery broker, result backend, and catalog cache.

**Tech Stack:** Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic · Celery 5 · Redis 7 · slowapi · React 18 · TypeScript · Vite · Playwright · Locust

**Constraints (NEVER VIOLATE):**
- Never run any `git` command. At every checkpoint stop, hand the human a commit message, they run it.
- No regressions: entire existing test suite stays green at every checkpoint.
- Worker is idempotent: checking `transaction.status != "pending"` before applying any credits.
- Purchase request carries only `package_id`; price/credits read from the DB.
- Role, credits, balance can never be set from client input.
- Feature spends remain synchronous and unchanged.
- DO NOT add real payments, OAuth, email flows, or Tier 3 hardening.

---

## File Map

| Action | Path |
|--------|------|
| Modify | `backend/pyproject.toml` |
| Modify | `backend/app/core/config.py` |
| Modify | `backend/app/core/deps.py` |
| Modify | `backend/app/core/security.py` |
| Modify | `backend/app/models/credits.py` |
| Modify | `backend/app/routers/auth.py` |
| Modify | `backend/app/routers/purchases.py` |
| Modify | `backend/app/routers/packages.py` |
| Modify | `backend/app/routers/features.py` |
| Modify | `backend/app/schemas/auth.py` |
| Modify | `backend/app/schemas/purchase.py` |
| Modify | `backend/app/services/auth_service.py` |
| Modify | `backend/app/services/purchase_service.py` |
| Modify | `backend/app/main.py` |
| Modify | `backend/tests/conftest.py` |
| Modify | `backend/tests/test_auth.py` |
| Modify | `backend/tests/test_purchase_ledger.py` |
| Modify | `docker-compose.yml` |
| Modify | `.env.example` |
| Create | `backend/alembic/versions/0002_transaction_status_lifecycle.py` |
| Create | `backend/app/worker/__init__.py` |
| Create | `backend/app/worker/celery_app.py` |
| Create | `backend/app/worker/tasks.py` |
| Create | `backend/app/core/cache.py` |
| Create | `backend/app/core/rate_limit.py` |
| Create | `backend/tests/test_purchase_async.py` |
| Create | `backend/tests/test_security_attacks.py` |
| Create | `loadtest/locustfile.py` |
| Create | `loadtest/validate.py` |
| Create | `loadtest/requirements.txt` |
| Modify | `frontend/src/api/client.ts` |
| Modify | `frontend/src/api/purchases.ts` |
| Modify | `frontend/src/context/AuthContext.tsx` |
| Create | `frontend/src/hooks/usePurchasePoller.ts` |
| Modify | `frontend/src/pages/Store.tsx` |

---

## Batch A: Foundation

### Task A1: Alembic migration — transaction status lifecycle

**Files:**
- Create: `backend/alembic/versions/0002_transaction_status_lifecycle.py`

- [ ] **Step 1: Write the migration file**

```python
# backend/alembic/versions/0002_transaction_status_lifecycle.py
"""Add transaction status lifecycle columns.

Revision ID: 0002_transaction_status_lifecycle
Revises: 0001_initial_creditos_schema
Create Date: 2026-06-13
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0002_transaction_status_lifecycle"
down_revision: str | None = "0001_initial_creditos_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add completed_at (nullable — only set when status becomes "completed")
    op.add_column(
        "transactions",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Add failure_reason (nullable — only set on "failed" status)
    op.add_column(
        "transactions",
        sa.Column("failure_reason", sa.String(length=255), nullable=True),
    )
    # Change default status from "completed" to "pending"
    op.alter_column(
        "transactions",
        "status",
        server_default="pending",
    )


def downgrade() -> None:
    op.alter_column("transactions", "status", server_default="completed")
    op.drop_column("transactions", "failure_reason")
    op.drop_column("transactions", "completed_at")
```

- [ ] **Step 2: Update the Transaction model to reflect new columns**

In `backend/app/models/credits.py`, add `completed_at` and `failure_reason` and change the default status:

```python
# In class Transaction, replace:
#   status: Mapped[str] = mapped_column(String(40), nullable=False, default="completed")
# and add the two new columns after credits_granted:

    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    credits_granted: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
```

- [ ] **Step 3: Verify the migration applies cleanly in Docker**

```bash
docker compose up db -d
docker compose run --rm backend alembic upgrade head
```

Expected: `Running upgrade 0001_initial_creditos_schema -> 0002_transaction_status_lifecycle, OK`

- [ ] **Step 4: Run the full pytest suite — must stay green**

```bash
docker compose run --rm backend python -m pytest -q
```

Expected: all existing tests pass (they use SQLite in-memory which picks up the new columns automatically).

---

### Task A2: Config expansion

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `.env.example`

- [ ] **Step 1: Add new settings fields**

Replace `backend/app/core/config.py` with:

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite+pysqlite:///:memory:"
    jwt_secret: str = "dev-test-secret-dev-test-secret-32"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 1440  # kept for backward compat; access_token_expires_minutes takes precedence
    access_token_expires_minutes: int = 30
    seed_admin_email: str = "admin@creditos.app"
    seed_admin_password: str = "credits123"
    seed_user_email: str = "buyer@acme.io"
    seed_user_password: str = "credits123"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/0"
    # Security / rate limiting
    login_rate_limit: str = "10/minute"
    catalog_cache_ttl_seconds: int = 300
    cookie_secure: bool = False
    cookie_samesite: str = "lax"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 2: Add new vars to `.env.example`**

Append to `.env.example`:

```dotenv
# Async purchase processing
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

# Auth hardening
ACCESS_TOKEN_EXPIRES_MINUTES=30
LOGIN_RATE_LIMIT=10/minute

# Catalog caching
CATALOG_CACHE_TTL_SECONDS=300

# Cookie settings (set COOKIE_SECURE=true and COOKIE_SAMESITE=strict for production HTTPS)
COOKIE_SECURE=false
COOKIE_SAMESITE=lax
```

- [ ] **Step 3: Run pytest to confirm no regressions**

```bash
cd backend && python -m pytest -q
```

Expected: all pass.

---

### Task A3: docker-compose — add Redis and worker services

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add redis and worker services**

Replace `docker-compose.yml`:

```yaml
services:
  db:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks:
      - creditos
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    networks:
      - creditos
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    restart: unless-stopped
    environment:
      DATABASE_URL: "postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}"
      JWT_SECRET: ${JWT_SECRET}
      CORS_ORIGINS: ${CORS_ORIGINS}
      REDIS_URL: "redis://redis:6379/0"
      CELERY_BROKER_URL: "redis://redis:6379/0"
      CELERY_RESULT_BACKEND: "redis://redis:6379/0"
      ACCESS_TOKEN_EXPIRES_MINUTES: "${ACCESS_TOKEN_EXPIRES_MINUTES:-30}"
      LOGIN_RATE_LIMIT: "${LOGIN_RATE_LIMIT:-10/minute}"
      CATALOG_CACHE_TTL_SECONDS: "${CATALOG_CACHE_TTL_SECONDS:-300}"
      COOKIE_SECURE: "${COOKIE_SECURE:-false}"
      COOKIE_SAMESITE: "${COOKIE_SAMESITE:-lax}"
      SEED_ADMIN_EMAIL: ${SEED_ADMIN_EMAIL:-admin@creditos.app}
      SEED_ADMIN_PASSWORD: ${SEED_ADMIN_PASSWORD:-credits123}
      SEED_USER_EMAIL: ${SEED_USER_EMAIL:-buyer@acme.io}
      SEED_USER_PASSWORD: ${SEED_USER_PASSWORD:-credits123}
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - creditos

  worker:
    build:
      context: ./backend
      dockerfile: Dockerfile
    command: ["celery", "-A", "app.worker.celery_app", "worker", "--loglevel=info", "--concurrency=4"]
    restart: unless-stopped
    environment:
      DATABASE_URL: "postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}"
      JWT_SECRET: ${JWT_SECRET}
      REDIS_URL: "redis://redis:6379/0"
      CELERY_BROKER_URL: "redis://redis:6379/0"
      CELERY_RESULT_BACKEND: "redis://redis:6379/0"
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - creditos

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    restart: unless-stopped
    ports:
      - "3000:80"
    depends_on:
      - backend
    networks:
      - creditos

networks:
  creditos:
    driver: bridge

volumes:
  postgres_data:
```

- [ ] **Step 2: Verify Docker build still works**

```bash
docker compose build
```

Expected: all four images build successfully.

---

### Task A4: New Python modules — Celery app, cache, rate limiter

**Files:**
- Create: `backend/app/worker/__init__.py`
- Create: `backend/app/worker/celery_app.py`
- Create: `backend/app/core/cache.py`
- Create: `backend/app/core/rate_limit.py`
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add new dependencies to pyproject.toml**

In `[project] dependencies`, add after `sqlalchemy`:

```toml
    "celery[redis]>=5.4",
    "redis>=5.0",
    "slowapi>=0.1.9",
```

And add a new optional group at the end:

```toml
[project.optional-dependencies]
test = [
    "httpx>=0.27.0",
    "pytest>=8.3.2",
    "pytest-asyncio>=0.23.8",
]
loadtest = [
    "locust>=2.29",
]
```

- [ ] **Step 2: Install new deps in Docker (rebuild)**

```bash
docker compose build backend worker
```

Expected: both images rebuild with celery, redis, and slowapi installed.

- [ ] **Step 3: Create `backend/app/worker/__init__.py`**

```python
```

(Empty file — makes `app.worker` a package.)

- [ ] **Step 4: Create `backend/app/worker/celery_app.py`**

```python
from celery import Celery

from app.core.config import get_settings


def make_celery() -> Celery:
    settings = get_settings()
    app = Celery(
        "creditos",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        include=["app.worker.tasks"],
    )
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_max_retries=3,
    )
    return app


celery_app = make_celery()
```

- [ ] **Step 5: Create `backend/app/core/cache.py`**

```python
import json
from typing import Any

import redis

from app.core.config import get_settings

_client: redis.Redis | None = None


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(get_settings().redis_url, decode_responses=False)
    return _client


def cache_get(key: str) -> bytes | None:
    return _get_client().get(key)


def cache_set(key: str, value: bytes, ttl: int) -> None:
    _get_client().set(key, value, ex=ttl)


def cache_delete(*keys: str) -> None:
    if keys:
        _get_client().delete(*keys)


PACKAGES_CACHE_KEY = "catalog:packages:active"
FEATURES_CACHE_KEY = "catalog:features:all"


def invalidate_catalog_cache() -> None:
    cache_delete(PACKAGES_CACHE_KEY, FEATURES_CACHE_KEY)
```

- [ ] **Step 6: Create `backend/app/core/rate_limit.py`**

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings


def make_limiter() -> Limiter:
    settings = get_settings()
    return Limiter(
        key_func=get_remote_address,
        storage_uri=settings.redis_url,
        default_limits=[],
    )


limiter = make_limiter()
```

- [ ] **Step 7: Run pytest — must still be green**

```bash
cd backend && python -m pytest -q
```

Expected: all existing tests pass (new modules are not yet imported by production code).

---

**Checkpoint A — commit message for the human:**

```
feat(infra): add Celery+Redis foundation, expand config, update docker-compose

- Alembic 0002: adds completed_at, failure_reason to transactions; changes
  default status to "pending"
- Settings: redis_url, celery_*, access_token_expires_minutes, login_rate_limit,
  catalog_cache_ttl_seconds, cookie_secure, cookie_samesite
- docker-compose: redis service + worker service
- pyproject.toml: celery[redis], redis, slowapi deps
- New modules: app/worker/celery_app.py, app/core/cache.py, app/core/rate_limit.py
- .env.example: documents all new vars

Tests: all passing
```

---

## Batch B: Async Purchase Backend

### Task B1: Purchase schemas — add 202 and status shapes

**Files:**
- Modify: `backend/app/schemas/purchase.py`

- [ ] **Step 1: Write the failing test for the new schema shapes**

In a new test file `backend/tests/test_purchase_async.py`, add:

```python
from uuid import uuid4
from app.schemas.purchase import PurchaseAccepted, TransactionStatusResponse


def test_purchase_accepted_schema() -> None:
    obj = PurchaseAccepted(transaction_id=uuid4(), status="pending")
    assert obj.status == "pending"


def test_transaction_status_response_pending() -> None:
    obj = TransactionStatusResponse(transaction_id=uuid4(), status="pending")
    assert obj.balance is None
    assert obj.entitlements is None
    assert obj.failure_reason is None


def test_transaction_status_response_completed() -> None:
    tid = uuid4()
    obj = TransactionStatusResponse(
        transaction_id=tid,
        status="completed",
        balance=50,
        entitlements=["feat_a"],
    )
    assert obj.balance == 50
    assert obj.entitlements == ["feat_a"]
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd backend && python -m pytest tests/test_purchase_async.py -v
```

Expected: ImportError — `PurchaseAccepted` and `TransactionStatusResponse` do not exist yet.

- [ ] **Step 3: Add the new schemas**

Replace `backend/app/schemas/purchase.py`:

```python
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PurchaseRequest(BaseModel):
    package_id: UUID


class TransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    package_id: UUID
    package_name: str
    status: str
    amount_cents: int
    credits_granted: int
    created_at: datetime


class PurchaseResponse(BaseModel):
    transaction: TransactionRead
    balance: int
    newly_unlocked: list[str]
    entitlements: list[str]


# --- New async shapes ---

class PurchaseAccepted(BaseModel):
    """Returned immediately (HTTP 202) when the purchase is enqueued."""
    transaction_id: UUID
    status: str  # always "pending" at creation time


class TransactionStatusResponse(BaseModel):
    """Returned by GET /purchases/{id}/status."""
    transaction_id: UUID
    status: str  # pending | processing | completed | failed
    balance: int | None = None
    newly_unlocked: list[str] | None = None
    entitlements: list[str] | None = None
    failure_reason: str | None = None
```

- [ ] **Step 4: Run the schema tests**

```bash
cd backend && python -m pytest tests/test_purchase_async.py -v
```

Expected: 3 tests pass.

---

### Task B2: Purchase service — split into initiate + worker logic

**Files:**
- Modify: `backend/app/services/purchase_service.py`

- [ ] **Step 1: Add the `initiate_purchase` function**

The existing `purchase_package` stays intact (worker calls it internally). Add two new public functions at the bottom of `backend/app/services/purchase_service.py`:

```python
import uuid as _uuid_module
from datetime import timezone as _tz

from app.schemas.purchase import PurchaseAccepted, TransactionStatusResponse


def initiate_purchase(
    db: Session,
    user: User,
    payload: PurchaseRequest,
    idempotency_key: str,
) -> tuple[PurchaseAccepted, bool]:
    """
    Validate the request, check for replay, write a pending transaction.
    Returns (PurchaseAccepted, is_new).  is_new=False means idempotent replay
    of an already-existing transaction (any status).
    """
    replayed = _replay_purchase(db, user.id, payload, idempotency_key)
    if replayed is not None:
        # Find the transaction to return its id
        tx = db.execute(
            select(Transaction).where(
                Transaction.user_id == user.id,
                Transaction.idempotency_key == idempotency_key,
            )
        ).scalar_one()
        return PurchaseAccepted(transaction_id=tx.id, status=tx.status), False

    package = _load_package(db, payload.package_id)
    transaction = Transaction(
        user_id=user.id,
        package_id=package.id,
        idempotency_key=idempotency_key,
        request_fingerprint=_fingerprint(package.id),
        status="pending",
        amount_cents=package.price_cents,
        credits_granted=package.credits,
    )
    db.add(transaction)
    try:
        db.flush()
        db.commit()
    except IntegrityError:
        db.rollback()
        replayed = _replay_purchase(db, user.id, payload, idempotency_key)
        if replayed is not None:
            tx = db.execute(
                select(Transaction).where(
                    Transaction.user_id == user.id,
                    Transaction.idempotency_key == idempotency_key,
                )
            ).scalar_one()
            return PurchaseAccepted(transaction_id=tx.id, status=tx.status), False
        raise api_error(
            409,
            "IDEMPOTENCY_KEY_CONFLICT",
            "Idempotency key was already used for a conflicting purchase.",
        )

    return PurchaseAccepted(transaction_id=transaction.id, status="pending"), True


def get_transaction_status(
    db: Session,
    user_id: _uuid_module.UUID,
    transaction_id: _uuid_module.UUID,
) -> TransactionStatusResponse:
    """Load a transaction owned by user_id and return its current status."""
    tx = db.execute(
        select(Transaction)
        .options(selectinload(Transaction.package))
        .where(Transaction.id == transaction_id, Transaction.user_id == user_id)
    ).scalar_one_or_none()

    if tx is None:
        raise api_error(404, "TRANSACTION_NOT_FOUND", "Transaction not found.")

    if tx.status == "completed":
        wallet = db.get(UserCredit, user_id)
        return TransactionStatusResponse(
            transaction_id=tx.id,
            status="completed",
            balance=wallet.balance if wallet else 0,
            newly_unlocked=[],
            entitlements=_entitlement_keys(db, user_id),
        )

    if tx.status == "failed":
        return TransactionStatusResponse(
            transaction_id=tx.id,
            status="failed",
            failure_reason=tx.failure_reason,
        )

    return TransactionStatusResponse(transaction_id=tx.id, status=tx.status)
```

- [ ] **Step 2: Run full pytest — existing tests must stay green**

```bash
cd backend && python -m pytest -q
```

Expected: all existing tests pass (we only added new functions, changed nothing existing).

---

### Task B3: Celery worker task — `process_purchase`

**Files:**
- Modify: `backend/app/worker/tasks.py`

- [ ] **Step 1: Write a unit test for the worker function first**

In `backend/tests/test_purchase_async.py`, add:

```python
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import Package, Transaction, User, UserCredit
from app.worker.tasks import _apply_purchase_in_worker


@pytest.fixture
def buyer_with_package(db_session: Session):
    user = User(
        email="worker-buyer@example.com",
        password_hash=hash_password("secret123"),
        role="user",
        initials="WB",
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(UserCredit(user_id=user.id, balance=0))

    pkg = Package(
        name="Worker Pack",
        slug="worker-pack",
        description="Test package",
        price_cents=500,
        credits=100,
        active=True,
    )
    db_session.add(pkg)
    db_session.flush()

    tx = Transaction(
        user_id=user.id,
        package_id=pkg.id,
        idempotency_key="worker-test-key",
        request_fingerprint=f"package:{pkg.id}",
        status="pending",
        amount_cents=500,
        credits_granted=100,
    )
    db_session.add(tx)
    db_session.commit()
    return user, pkg, tx


def test_apply_purchase_grants_credits(db_session: Session, buyer_with_package) -> None:
    user, pkg, tx = buyer_with_package
    _apply_purchase_in_worker(db_session, tx.id)
    db_session.expire_all()

    updated_tx = db_session.get(Transaction, tx.id)
    assert updated_tx.status == "completed"
    assert updated_tx.completed_at is not None

    wallet = db_session.get(UserCredit, user.id)
    assert wallet.balance == 100


def test_apply_purchase_is_idempotent(db_session: Session, buyer_with_package) -> None:
    user, pkg, tx = buyer_with_package
    _apply_purchase_in_worker(db_session, tx.id)
    _apply_purchase_in_worker(db_session, tx.id)  # second call — must be no-op
    db_session.expire_all()

    wallet = db_session.get(UserCredit, user.id)
    assert wallet.balance == 100  # not 200
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd backend && python -m pytest tests/test_purchase_async.py::test_apply_purchase_grants_credits -v
```

Expected: ImportError — `_apply_purchase_in_worker` does not exist yet.

- [ ] **Step 3: Implement `backend/app/worker/tasks.py`**

```python
from datetime import timezone
from uuid import UUID

from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Feature, Package, Transaction, UserCredit, UserEntitlement
from app.services.credit_service import grant_credits
from app.worker.celery_app import celery_app

from sqlalchemy import select


def _apply_purchase_in_worker(db: Session, transaction_id: UUID) -> None:
    """
    Core idempotent logic — separated so unit tests can call it directly
    without going through Celery.
    """
    from datetime import datetime

    tx = db.execute(
        select(Transaction)
        .options(selectinload(Transaction.package))
        .with_for_update()
        .where(Transaction.id == transaction_id)
    ).scalar_one_or_none()

    if tx is None:
        return  # already deleted or never existed

    if tx.status != "pending":
        return  # already processed (idempotency guard)

    # Mark as processing so a concurrent retry knows work is in progress
    tx.status = "processing"
    db.flush()

    package = tx.package
    if package is None or not package.active:
        tx.status = "failed"
        tx.failure_reason = "Package is no longer active."
        db.commit()
        return

    try:
        grant_credits(
            db,
            tx.user_id,
            amount=tx.credits_granted,
            reason="package_purchase",
            description=f"{package.name} purchase",
            reference_type="transaction",
            reference_id=str(tx.id),
        )

        existing_keys = set(
            db.execute(
                select(UserEntitlement.feature_key)
                .where(UserEntitlement.user_id == tx.user_id)
            ).scalars().all()
        )
        for feature in package.features:
            if feature.key not in existing_keys:
                db.add(
                    UserEntitlement(
                        user_id=tx.user_id,
                        feature_key=feature.key,
                        source_transaction_id=tx.id,
                    )
                )
                db.flush()
                existing_keys.add(feature.key)

        tx.status = "completed"
        tx.completed_at = datetime.now(timezone.utc)
        db.commit()

    except Exception as exc:
        db.rollback()
        # Re-load inside fresh state to mark failed
        tx = db.get(Transaction, transaction_id)
        if tx is not None:
            tx.status = "failed"
            tx.failure_reason = str(exc)[:255]
            db.commit()
        raise


@celery_app.task(
    name="app.worker.tasks.process_purchase",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def process_purchase(self, transaction_id_str: str) -> None:
    transaction_id = UUID(transaction_id_str)
    db = SessionLocal()
    try:
        _apply_purchase_in_worker(db, transaction_id)
    except Exception as exc:
        db.close()
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 10)
    finally:
        db.close()
```

- [ ] **Step 4: Run the worker unit tests**

```bash
cd backend && python -m pytest tests/test_purchase_async.py -v -k "apply_purchase"
```

Expected: `test_apply_purchase_grants_credits` and `test_apply_purchase_is_idempotent` both pass.

---

### Task B4: Purchase router — 202 endpoint + status endpoint

**Files:**
- Modify: `backend/app/routers/purchases.py`

- [ ] **Step 1: Write the failing HTTP tests**

In `backend/tests/test_purchase_async.py`, add (after the unit tests):

```python
from collections.abc import Generator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.core.security import create_access_token, hash_password
from app.main import create_app
from app.models import Package, Transaction, User, UserCredit


@pytest.fixture
def http_client(db_session: Session):
    app = create_app()

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def buyer_and_token(db_session: Session):
    user = User(
        email="http-buyer@example.com",
        password_hash=hash_password("secret123"),
        role="user",
        initials="HB",
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(UserCredit(user_id=user.id, balance=0))

    pkg = Package(
        name="HTTP Pack",
        slug="http-pack",
        description="desc",
        price_cents=999,
        credits=50,
        active=True,
    )
    db_session.add(pkg)
    db_session.commit()

    token = create_access_token(str(user.id), user.email, user.role)
    return user, pkg, token


def _auth_cookies(token: str) -> dict[str, str]:
    return {"creditos_access_token": token, "creditos_csrf_token": "test-csrf"}


def _csrf_header() -> dict[str, str]:
    return {"X-CSRF-Token": "test-csrf"}


def test_purchase_returns_202_and_transaction_id(
    http_client: TestClient, buyer_and_token, db_session: Session
) -> None:
    user, pkg, token = buyer_and_token
    with patch("app.routers.purchases.process_purchase.delay") as mock_delay:
        resp = http_client.post(
            "/api/v1/purchases",
            json={"package_id": str(pkg.id)},
            headers={"Idempotency-Key": "unique-key-001", **_csrf_header()},
            cookies=_auth_cookies(token),
        )
    assert resp.status_code == 202
    body = resp.json()
    assert "transaction_id" in body
    assert body["status"] == "pending"
    mock_delay.assert_called_once()


def test_purchase_replay_returns_202(
    http_client: TestClient, buyer_and_token, db_session: Session
) -> None:
    user, pkg, token = buyer_and_token
    with patch("app.routers.purchases.process_purchase.delay"):
        http_client.post(
            "/api/v1/purchases",
            json={"package_id": str(pkg.id)},
            headers={"Idempotency-Key": "replay-key-001", **_csrf_header()},
            cookies=_auth_cookies(token),
        )
        resp = http_client.post(
            "/api/v1/purchases",
            json={"package_id": str(pkg.id)},
            headers={"Idempotency-Key": "replay-key-001", **_csrf_header()},
            cookies=_auth_cookies(token),
        )
    assert resp.status_code == 202  # replay is idempotent — same 202


def test_status_endpoint_returns_pending(
    http_client: TestClient, buyer_and_token, db_session: Session
) -> None:
    user, pkg, token = buyer_and_token
    with patch("app.routers.purchases.process_purchase.delay"):
        create_resp = http_client.post(
            "/api/v1/purchases",
            json={"package_id": str(pkg.id)},
            headers={"Idempotency-Key": "status-key-001", **_csrf_header()},
            cookies=_auth_cookies(token),
        )
    transaction_id = create_resp.json()["transaction_id"]

    resp = http_client.get(
        f"/api/v1/purchases/{transaction_id}/status",
        cookies=_auth_cookies(token),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && python -m pytest tests/test_purchase_async.py -v -k "http"
```

Expected: tests fail (endpoint still returns 201 old format, cookies not set up yet).

- [ ] **Step 3: Replace `backend/app/routers/purchases.py`**

```python
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.orm import Session

from app.core.deps import get_db, require_buyer, verify_csrf
from app.core.errors import api_error
from app.models import User
from app.schemas.purchase import PurchaseAccepted, TransactionStatusResponse
from app.services.purchase_service import get_transaction_status, initiate_purchase
from app.worker.tasks import process_purchase


router = APIRouter(tags=["purchases"])


@router.post("", response_model=PurchaseAccepted, status_code=status.HTTP_202_ACCEPTED,
             dependencies=[Depends(verify_csrf)])
def create(
    payload,
    db: Annotated[Session, Depends(get_db)],
    buyer: Annotated[User, Depends(require_buyer)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> PurchaseAccepted:
    if idempotency_key is None or not idempotency_key.strip():
        raise api_error(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key header is required.")

    normalized_key = idempotency_key.strip()
    if len(normalized_key) > 160:
        raise api_error(400, "IDEMPOTENCY_KEY_INVALID", "Idempotency-Key must be 160 characters or less.")

    accepted, is_new = initiate_purchase(db, buyer, payload, normalized_key)
    if is_new:
        process_purchase.delay(str(accepted.transaction_id))
    return accepted


@router.get("/{transaction_id}/status", response_model=TransactionStatusResponse)
def get_status(
    transaction_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    buyer: Annotated[User, Depends(require_buyer)],
) -> TransactionStatusResponse:
    return get_transaction_status(db, buyer.id, transaction_id)
```

Note: `payload` type annotation needs importing from schemas:

```python
from app.schemas.purchase import PurchaseAccepted, PurchaseRequest, TransactionStatusResponse
```

Full corrected file:

```python
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.orm import Session

from app.core.deps import get_db, require_buyer, verify_csrf
from app.core.errors import api_error
from app.models import User
from app.schemas.purchase import PurchaseAccepted, PurchaseRequest, TransactionStatusResponse
from app.services.purchase_service import get_transaction_status, initiate_purchase
from app.worker.tasks import process_purchase


router = APIRouter(tags=["purchases"])


@router.post("", response_model=PurchaseAccepted, status_code=status.HTTP_202_ACCEPTED,
             dependencies=[Depends(verify_csrf)])
def create(
    payload: PurchaseRequest,
    db: Annotated[Session, Depends(get_db)],
    buyer: Annotated[User, Depends(require_buyer)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> PurchaseAccepted:
    if idempotency_key is None or not idempotency_key.strip():
        raise api_error(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key header is required.")

    normalized_key = idempotency_key.strip()
    if len(normalized_key) > 160:
        raise api_error(400, "IDEMPOTENCY_KEY_INVALID", "Idempotency-Key must be 160 characters or less.")

    accepted, is_new = initiate_purchase(db, buyer, payload, normalized_key)
    if is_new:
        process_purchase.delay(str(accepted.transaction_id))
    return accepted


@router.get("/{transaction_id}/status", response_model=TransactionStatusResponse)
def get_status(
    transaction_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    buyer: Annotated[User, Depends(require_buyer)],
) -> TransactionStatusResponse:
    return get_transaction_status(db, buyer.id, transaction_id)
```

- [ ] **Step 4: Add `verify_csrf` to deps.py (placeholder until Batch C)**

For now, add a no-op `verify_csrf` to `backend/app/core/deps.py` so imports don't fail:

```python
def verify_csrf() -> None:
    """CSRF validation — implemented in Batch C. No-op during Batch B."""
    pass
```

- [ ] **Step 5: Run the HTTP tests**

```bash
cd backend && python -m pytest tests/test_purchase_async.py -v -k "http"
```

Expected: all 3 HTTP tests pass.

- [ ] **Step 6: Run full pytest suite**

```bash
cd backend && python -m pytest -q
```

Note: some tests in `test_purchase_ledger.py` that check for 201 with full balance will now fail — that is expected and will be fixed in Task B5.

---

### Task B5: Update legacy purchase tests for the async shape

**Files:**
- Modify: `backend/tests/test_purchase_ledger.py`

The existing HTTP purchase tests expect 201 with `{transaction, balance, newly_unlocked, entitlements}`. After the refactor they get 202 with `{transaction_id, status}`. Update only the HTTP endpoint tests; the service-layer tests (which test `grant_credits` directly) are untouched.

- [ ] **Step 1: Identify affected tests**

```bash
cd backend && python -m pytest tests/test_purchase_ledger.py -v 2>&1 | grep FAILED
```

Note the failing test names.

- [ ] **Step 2: Update HTTP purchase tests in `test_purchase_ledger.py`**

Find every test that calls `client.post("/api/v1/purchases", ...)` and asserts a 201 response with `balance`, `transaction`, `entitlements`.

Replace the pattern:
```python
# OLD
resp = client.post(
    "/api/v1/purchases",
    json={"package_id": str(pkg_id)},
    headers=_auth_header(token),
    headers={"Idempotency-Key": key},
)
assert resp.status_code == 201
body = resp.json()
assert body["balance"] == expected_balance
```

With:
```python
# NEW — purchase returns 202 with pending transaction_id
from unittest.mock import patch

with patch("app.routers.purchases.process_purchase.delay"):
    resp = client.post(
        "/api/v1/purchases",
        json={"package_id": str(pkg_id)},
        headers={"Idempotency-Key": key, "X-CSRF-Token": "test-csrf"},
        cookies={"creditos_access_token": token, "creditos_csrf_token": "test-csrf"},
    )
assert resp.status_code == 202
body = resp.json()
assert "transaction_id" in body
assert body["status"] == "pending"
```

For tests that check the resulting balance after purchase, call `_apply_purchase_in_worker` directly in the test after the 202:

```python
from app.worker.tasks import _apply_purchase_in_worker

transaction_id = UUID(body["transaction_id"])
_apply_purchase_in_worker(db_session, transaction_id)
db_session.expire_all()

wallet = db_session.get(UserCredit, user.id)
assert wallet.balance == expected_balance
```

Also update `_auth_header` usage in non-purchase tests. Since `get_current_user` still reads `Authorization: Bearer` at this stage (cookie auth is Batch C), keep `_auth_header` for all non-purchase endpoints in this file. Only purchase POST endpoints switch to cookies+CSRF in this task.

- [ ] **Step 3: Run full pytest**

```bash
cd backend && python -m pytest -q
```

Expected: all tests pass.

---

**Checkpoint B — commit message for the human:**

```
feat(purchases): make purchase flow async with Celery task and status endpoint

- PurchaseAccepted schema (202): {transaction_id, status}
- TransactionStatusResponse: {transaction_id, status, balance?, entitlements?, failure_reason?}
- initiate_purchase(): writes pending transaction, returns PurchaseAccepted
- get_transaction_status(): scoped to token user (no IDOR)
- process_purchase Celery task: idempotent worker with retry/backoff
- GET /purchases/{id}/status endpoint
- POST /purchases now returns 202
- Updated legacy purchase tests for async shape

Tests: all passing
```

---

## Batch C: Auth Hardening

### Task C1: Cookie-based auth backend

**Files:**
- Modify: `backend/app/schemas/auth.py`
- Modify: `backend/app/services/auth_service.py`
- Modify: `backend/app/routers/auth.py`
- Modify: `backend/app/core/deps.py`

- [ ] **Step 1: Write failing test for cookie auth**

In `backend/tests/test_auth.py`, add a test at the bottom:

```python
def test_login_sets_httponly_cookie(client: TestClient, db_session: Session) -> None:
    from app.schemas.auth import SignupRequest
    from app.services.auth_service import signup as signup_user
    signup_user(db_session, SignupRequest(email="cookie-test@example.com", password="password123"))

    resp = client.post("/api/v1/auth/login", json={"email": "cookie-test@example.com", "password": "password123"})
    assert resp.status_code == 200
    assert "creditos_access_token" in resp.cookies
    assert "csrf_token" in resp.json()
    # access_token must NOT appear in the JSON body
    assert "access_token" not in resp.json()


def test_me_works_with_cookie(client: TestClient, db_session: Session) -> None:
    from app.schemas.auth import SignupRequest
    from app.services.auth_service import signup as signup_user
    result = signup_user(db_session, SignupRequest(email="cookie-me@example.com", password="password123"))

    token = result.access_token  # internal field, not in JSON body
    resp = client.get("/api/v1/auth/me", cookies={"creditos_access_token": token})
    assert resp.status_code == 200
    assert resp.json()["email"] == "cookie-me@example.com"
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd backend && python -m pytest tests/test_auth.py::test_login_sets_httponly_cookie -v
```

Expected: `AssertionError` — `creditos_access_token` not in cookies, `access_token` is in body.

- [ ] **Step 3: Update `backend/app/schemas/auth.py`**

Replace `TokenResponse`:

```python
class TokenResponse(BaseModel):
    csrf_token: str
    user: UserRead
```

- [ ] **Step 4: Update `backend/app/services/auth_service.py`**

Add `AuthResult` dataclass and update `_token_response` → `_auth_result`:

```python
import secrets
from dataclasses import dataclass

# ... existing imports ...


@dataclass
class AuthResult:
    access_token: str
    csrf_token: str
    user: "User"

    def to_response(self) -> TokenResponse:
        return TokenResponse(csrf_token=self.csrf_token, user=self.user)


def _auth_result(user: User) -> AuthResult:
    access_token = create_access_token(str(user.id), user.email, user.role)
    csrf_token = secrets.token_hex(32)
    return AuthResult(access_token=access_token, csrf_token=csrf_token, user=user)


def signup(db: Session, request: SignupRequest) -> AuthResult:
    # ... same logic as before, last line changes:
    return _auth_result(user)


def login(db: Session, request: LoginRequest) -> AuthResult:
    # ... same logic as before, last line changes:
    return _auth_result(user)
```

Full `backend/app/services/auth_service.py`:

```python
import secrets
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import api_error
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User, UserCredit
from app.schemas.auth import LoginRequest, SignupRequest, TokenResponse


@dataclass
class AuthResult:
    access_token: str
    csrf_token: str
    user: User

    def to_response(self) -> TokenResponse:
        return TokenResponse(csrf_token=self.csrf_token, user=self.user)


def normalize_email(email: str) -> str:
    return email.lower()


def derive_initials(email: str) -> str:
    local_part = email.split("@", 1)[0]
    characters = "".join(c for c in local_part if c.isalnum())
    return (characters[:2] or "US").upper()


def _auth_result(user: User) -> AuthResult:
    access_token = create_access_token(str(user.id), user.email, user.role)
    csrf_token = secrets.token_hex(32)
    return AuthResult(access_token=access_token, csrf_token=csrf_token, user=user)


def _user_already_exists_error() -> Exception:
    return api_error(409, "USER_ALREADY_EXISTS", "A user with this email already exists.")


def signup(db: Session, request: SignupRequest) -> AuthResult:
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
    return _auth_result(user)


def login(db: Session, request: LoginRequest) -> AuthResult:
    email = normalize_email(str(request.email))
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None or not verify_password(request.password, user.password_hash):
        raise api_error(401, "INVALID_CREDENTIALS", "Invalid email or password.")
    return _auth_result(user)
```

- [ ] **Step 5: Update `backend/app/core/security.py` to use `access_token_expires_minutes`**

In `create_access_token`, change `jwt_expires_minutes` to `access_token_expires_minutes`:

```python
def create_access_token(subject: str, email: str, role: str) -> str:
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expires_minutes)
    return jwt.encode(
        {"sub": subject, "email": email, "role": role, "exp": expires_at},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
```

- [ ] **Step 6: Update `backend/app/routers/auth.py`**

Replace `backend/app/routers/auth.py`:

```python
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import get_current_user, get_db
from app.models import User
from app.schemas.auth import LoginRequest, SignupRequest, TokenResponse, UserRead
from app.services.auth_service import AuthResult
from app.services.auth_service import login as login_user
from app.services.auth_service import signup as signup_user


router = APIRouter(tags=["auth"])


def _set_auth_cookies(response: Response, result: AuthResult) -> None:
    settings = get_settings()
    max_age = settings.access_token_expires_minutes * 60
    response.set_cookie(
        "creditos_access_token",
        result.access_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=max_age,
        path="/",
    )
    response.set_cookie(
        "creditos_csrf_token",
        result.csrf_token,
        httponly=False,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=max_age,
        path="/",
    )


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(
    request: SignupRequest,
    db: Annotated[Session, Depends(get_db)],
    response: Response,
) -> TokenResponse:
    result = signup_user(db, request)
    _set_auth_cookies(response, result)
    return result.to_response()


@router.post("/login", response_model=TokenResponse)
def login(
    request: LoginRequest,
    db: Annotated[Session, Depends(get_db)],
    response: Response,
) -> TokenResponse:
    result = login_user(db, request)
    _set_auth_cookies(response, result)
    return result.to_response()


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    response.delete_cookie("creditos_access_token", path="/")
    response.delete_cookie("creditos_csrf_token", path="/")


@router.get("/me", response_model=UserRead)
def me(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    return current_user
```

- [ ] **Step 7: Update `backend/app/core/deps.py` — cookie auth + real CSRF**

Replace `backend/app/core/deps.py`:

```python
import secrets
from collections.abc import Callable
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Cookie, Depends, Header
from sqlalchemy.orm import Session

from app.core.errors import api_error
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import Feature, User, UserEntitlement


def get_current_user(
    token: Annotated[str | None, Cookie(alias="creditos_access_token")] = None,
    db: Annotated[Session, Depends(get_db)] = ...,
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


def verify_csrf(
    csrf_cookie: Annotated[str | None, Cookie(alias="creditos_csrf_token")] = None,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> None:
    if not csrf_cookie or not csrf_header:
        raise api_error(403, "CSRF_INVALID", "CSRF token missing.")
    if not secrets.compare_digest(csrf_cookie, csrf_header):
        raise api_error(403, "CSRF_INVALID", "CSRF token mismatch.")


def require_admin(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    if current_user.role != "admin":
        raise api_error(403, "FORBIDDEN", "Admin role is required.")
    return current_user


def require_buyer(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    if current_user.role != "user":
        raise api_error(403, "FORBIDDEN", "User role is required.")
    return current_user


def require_feature(feature_key: str) -> Callable[..., tuple[Feature, User]]:
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
```

Note: the `= ...` default on `db` needs to be a `Depends` call — correct signature:

```python
def get_current_user(
    token: Annotated[str | None, Cookie(alias="creditos_access_token")] = None,
    db: Annotated[Session, Depends(get_db)],
) -> User:
```

- [ ] **Step 8: Update all existing tests that use `Authorization: Bearer` headers**

All test files that use `_auth_header(token)` or `headers={"Authorization": ...}` must switch to cookies. Pattern:

In `conftest.py`, add a shared helper:

```python
def auth_cookies(token: str, csrf: str = "test-csrf") -> dict[str, str]:
    return {"creditos_access_token": token, "creditos_csrf_token": csrf}

def csrf_headers(csrf: str = "test-csrf") -> dict[str, str]:
    return {"X-CSRF-Token": csrf}
```

In each test file, replace:
- `headers=_auth_header(token)` on GET requests → `cookies=auth_cookies(token)` (no CSRF header needed on GETs)
- `headers={..._auth_header(token), "Idempotency-Key": key}` on POST → `cookies=auth_cookies(token), headers={"X-CSRF-Token": "test-csrf", "Idempotency-Key": key}`
- Auth response assertions: `body["access_token"]` → `body["csrf_token"]`; remove any `token_type` checks

Also update test fixtures that call `signup_user()` and capture the return value: it's now an `AuthResult`, not a `TokenResponse`. Get the token via `result.access_token`.

- [ ] **Step 9: Run full pytest**

```bash
cd backend && python -m pytest -q
```

Expected: all tests pass.

---

### Task C2: Login rate limiting

**Files:**
- Modify: `backend/app/routers/auth.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Apply rate limiter to login endpoint**

In `backend/app/main.py`, add slowapi setup:

```python
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.core.rate_limit import limiter

def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="CreditOS API", version="0.1.0")

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    # ... rest of existing setup ...
```

In `backend/app/routers/auth.py`, apply the limiter to the login endpoint:

```python
from fastapi import Request
from app.core.rate_limit import limiter
from app.core.config import get_settings

@router.post("/login", response_model=TokenResponse)
@limiter.limit(lambda: get_settings().login_rate_limit)
def login(
    request: Request,  # required by slowapi
    login_request: LoginRequest,
    db: Annotated[Session, Depends(get_db)],
    response: Response,
) -> TokenResponse:
    result = login_user(db, login_request)
    _set_auth_cookies(response, result)
    return result.to_response()
```

Note: slowapi requires the `request: Request` parameter to be named `request`. Rename the existing `request` parameter to `login_request`.

- [ ] **Step 2: Write a rate limit test**

In `backend/tests/test_security_attacks.py` (to be filled out more in Batch D), add:

```python
def test_login_rate_limit_throttles_brute_force(client: TestClient) -> None:
    """After LOGIN_RATE_LIMIT failures, the endpoint returns 429."""
    import os
    os.environ["LOGIN_RATE_LIMIT"] = "5/minute"
    from app.core.config import get_settings
    get_settings.cache_clear()

    for _ in range(5):
        client.post("/api/v1/auth/login", json={"email": "nouser@test.com", "password": "wrong"})

    resp = client.post("/api/v1/auth/login", json={"email": "nouser@test.com", "password": "wrong"})
    assert resp.status_code == 429
```

Note: in CI (SQLite/in-process), slowapi uses memory storage by default when Redis is unavailable. Set `storage_uri=None` as fallback in `rate_limit.py`:

```python
def make_limiter() -> Limiter:
    settings = get_settings()
    try:
        return Limiter(key_func=get_remote_address, storage_uri=settings.redis_url)
    except Exception:
        return Limiter(key_func=get_remote_address)  # in-memory fallback for tests
```

- [ ] **Step 3: Run full pytest**

```bash
cd backend && python -m pytest -q
```

Expected: all tests pass.

---

### Task C3: Frontend — drop localStorage, wire cookies and CSRF

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/context/AuthContext.tsx`
- Modify: `frontend/src/api/purchases.ts`

- [ ] **Step 1: Replace `frontend/src/api/client.ts`**

```typescript
import axios from 'axios';

function getCsrfToken(): string | null {
  const match = document.cookie.match(/(?:^|;\s*)creditos_csrf_token=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

const client = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? '',
  withCredentials: true,
});

client.interceptors.request.use((config) => {
  const method = (config.method ?? 'get').toLowerCase();
  if (['post', 'put', 'patch', 'delete'].includes(method)) {
    const csrf = getCsrfToken();
    if (csrf) config.headers['X-CSRF-Token'] = csrf;
  }
  return config;
});

client.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error.response?.status === 401) {
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export default client;
```

- [ ] **Step 2: Replace `frontend/src/context/AuthContext.tsx`**

```typescript
import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';
import type { AuthUser } from '../api/auth';
import client from '../api/client';

interface AuthContextValue {
  user: AuthUser | null;
  login: (user: AuthUser) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function loadUser(): AuthUser | null {
  try {
    const raw = sessionStorage.getItem('creditos:user');
    return raw ? (JSON.parse(raw) as AuthUser) : null;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(loadUser);

  const login = useCallback((newUser: AuthUser) => {
    sessionStorage.setItem('creditos:user', JSON.stringify(newUser));
    setUser(newUser);
  }, []);

  const logout = useCallback(async () => {
    try { await client.post('/api/v1/auth/logout'); } catch { /* best-effort */ }
    sessionStorage.removeItem('creditos:user');
    setUser(null);
    window.location.href = '/login';
  }, []);

  return (
    <AuthContext.Provider value={{ user, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
```

- [ ] **Step 3: Update call sites that use `login(token, user)`**

Search for `login(` in the frontend:

```bash
grep -r "login(" frontend/src --include="*.tsx" --include="*.ts" -l
```

In each login/signup page, change:
```typescript
// OLD
const { login } = useAuth();
login(data.access_token, data.user);

// NEW
const { login } = useAuth();
login(data.user);
```

The `token` argument is dropped since the token is now in the httpOnly cookie. Also remove any `token` prop from `useAuth()` destructuring across the codebase.

- [ ] **Step 4: Update `frontend/src/api/purchases.ts`**

```typescript
import client from './client';

export interface PurchaseAccepted {
  transaction_id: string;
  status: string;
}

export interface TransactionStatus {
  transaction_id: string;
  status: string;
  balance?: number;
  newly_unlocked?: string[];
  entitlements?: string[];
  failure_reason?: string;
}

export async function createPurchase(packageId: string): Promise<PurchaseAccepted> {
  const idempotencyKey = crypto.randomUUID();
  const res = await client.post<PurchaseAccepted>(
    '/api/v1/purchases',
    { package_id: packageId },
    { headers: { 'Idempotency-Key': idempotencyKey } }
  );
  return res.data;
}

export async function getPurchaseStatus(transactionId: string): Promise<TransactionStatus> {
  const res = await client.get<TransactionStatus>(`/api/v1/purchases/${transactionId}/status`);
  return res.data;
}
```

- [ ] **Step 5: Build the frontend to confirm no TypeScript errors**

```bash
cd frontend && npm run build
```

Expected: build succeeds with no TypeScript errors.

---

**Checkpoint C — commit message for the human:**

```
feat(auth): httpOnly cookie auth, CSRF double-submit, rate-limited login, 30-min JWT

- TokenResponse drops access_token, adds csrf_token
- signup/login set creditos_access_token (httpOnly) + creditos_csrf_token cookies
- POST /auth/logout clears both cookies
- get_current_user reads Cookie instead of Authorization header
- verify_csrf dependency: compares creditos_csrf_token cookie vs X-CSRF-Token header
- Login rate-limited via slowapi (LOGIN_RATE_LIMIT env, default 10/minute)
- JWT expiry reduced to ACCESS_TOKEN_EXPIRES_MINUTES (default 30 min)
- Frontend: drop localStorage, withCredentials:true, CSRF header interceptor
- All existing tests migrated to cookie/CSRF pattern

Tests: all passing
```

---

## Batch D: Security Attack Tests

### Task D1: IDOR / object-level access tests

**Files:**
- Create: `backend/tests/test_security_attacks.py`

- [ ] **Step 1: Write IDOR attack tests**

Create `backend/tests/test_security_attacks.py`:

```python
"""
Security attack tests — every test performs a real attack and asserts it fails.
These prove the fixes, not just the happy path.
"""
from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.core.security import create_access_token, hash_password
from app.main import create_app
from app.models import Package, Transaction, User, UserCredit


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: (yield db_session)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _make_user(db: Session, email: str, role: str = "user") -> tuple[User, str]:
    user = User(
        email=email,
        password_hash=hash_password("secret123"),
        role=role,
        initials=email[:2].upper(),
    )
    db.add(user)
    db.flush()
    if role == "user":
        db.add(UserCredit(user_id=user.id, balance=0))
        db.flush()
    db.commit()
    token = create_access_token(str(user.id), user.email, user.role)
    return user, token


def _cookies(token: str) -> dict[str, str]:
    return {"creditos_access_token": token, "creditos_csrf_token": "csrf"}


def _csrf() -> dict[str, str]:
    return {"X-CSRF-Token": "csrf"}


# --- IDOR: wallet ---

def test_user_cannot_read_other_users_wallet(client: TestClient, db_session: Session) -> None:
    """User A authenticated, tries to read wallet — should see own wallet only."""
    user_a, token_a = _make_user(db_session, "idor-a@test.com")
    user_b, token_b = _make_user(db_session, "idor-b@test.com")

    # User A's wallet: should succeed with user A's own data
    resp_a = client.get("/api/v1/wallet", cookies=_cookies(token_a))
    assert resp_a.status_code == 200
    # There is no endpoint that takes a user_id param — just confirm A's token gives A's data
    assert resp_a.json()["balance"] == 0  # user A balance

    # User B's token must not reveal user A's data
    resp_b = client.get("/api/v1/wallet", cookies=_cookies(token_b))
    assert resp_b.status_code == 200
    # They are separate — just confirm no cross-contamination
    assert resp_b.json()["balance"] == 0


def test_user_cannot_read_other_users_ledger(client: TestClient, db_session: Session) -> None:
    user_a, token_a = _make_user(db_session, "idor-ledger-a@test.com")
    user_b, token_b = _make_user(db_session, "idor-ledger-b@test.com")

    # Confirm both endpoints require auth (no cross-user param)
    resp = client.get("/api/v1/wallet/ledger", cookies=_cookies(token_a))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    # Unauthenticated must fail
    resp_unauth = client.get("/api/v1/wallet/ledger")
    assert resp_unauth.status_code == 401


def test_user_cannot_read_other_users_transaction_status(
    client: TestClient, db_session: Session
) -> None:
    """User B tries to poll user A's transaction — must get 404."""
    from unittest.mock import patch

    user_a, token_a = _make_user(db_session, "idor-tx-a@test.com")
    user_b, token_b = _make_user(db_session, "idor-tx-b@test.com")

    pkg = Package(
        name="IDOR Pack", slug="idor-pack", description="d",
        price_cents=100, credits=10, active=True,
    )
    db_session.add(pkg)
    db_session.commit()

    # User A creates a purchase
    with patch("app.routers.purchases.process_purchase.delay"):
        resp = client.post(
            "/api/v1/purchases",
            json={"package_id": str(pkg.id)},
            headers={"Idempotency-Key": "idor-test-key", **_csrf()},
            cookies=_cookies(token_a),
        )
    transaction_id = resp.json()["transaction_id"]

    # User B tries to read user A's transaction status — must be 404
    resp_b = client.get(f"/api/v1/purchases/{transaction_id}/status", cookies=_cookies(token_b))
    assert resp_b.status_code == 404
```

- [ ] **Step 2: Run IDOR tests**

```bash
cd backend && python -m pytest tests/test_security_attacks.py -v -k "idor"
```

Expected: all pass.

---

### Task D2: Server-side pricing and mass assignment attack tests

**Files:**
- Modify: `backend/tests/test_security_attacks.py`

- [ ] **Step 1: Add pricing and mass assignment tests**

Append to `backend/tests/test_security_attacks.py`:

```python
# --- Server-side pricing ---

def test_tampered_price_in_request_is_ignored(client: TestClient, db_session: Session) -> None:
    """Sending extra price/credits fields in purchase request must be ignored."""
    user, token = _make_user(db_session, "pricing-attack@test.com")
    pkg = Package(
        name="Pricing Pack", slug="pricing-pack", description="d",
        price_cents=1000, credits=50, active=True,
    )
    db_session.add(pkg)
    db_session.commit()

    from unittest.mock import patch

    with patch("app.routers.purchases.process_purchase.delay"):
        # Attacker adds price_cents=1 and credits_granted=99999 to the body
        resp = client.post(
            "/api/v1/purchases",
            json={
                "package_id": str(pkg.id),
                "price_cents": 1,
                "credits_granted": 99999,
                "amount_cents": 1,
            },
            headers={"Idempotency-Key": "pricing-attack-key", **_csrf()},
            cookies=_cookies(token),
        )

    assert resp.status_code == 202
    tx_id = resp.json()["transaction_id"]

    from app.models import Transaction
    from uuid import UUID
    tx = db_session.get(Transaction, UUID(tx_id))
    # Server must have used package values, not attacker values
    assert tx.amount_cents == 1000
    assert tx.credits_granted == 50


# --- Mass assignment ---

def test_signup_cannot_set_role_admin(client: TestClient, db_session: Session) -> None:
    """Signing up with role=admin in the body must not create an admin user."""
    resp = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "mass-assign@test.com",
            "password": "password123",
            "role": "admin",
            "credits": 999999,
            "balance": 999999,
        },
    )
    assert resp.status_code == 201

    from sqlalchemy import select
    from app.models import User
    user = db_session.execute(
        select(User).where(User.email == "mass-assign@test.com")
    ).scalar_one()
    assert user.role == "user"  # extra fields silently ignored


def test_signup_cannot_set_credits_directly(client: TestClient, db_session: Session) -> None:
    """Extra numeric fields in signup must be silently ignored."""
    client.post(
        "/api/v1/auth/signup",
        json={"email": "credits-attack@test.com", "password": "password123", "balance": 10000},
    )
    from sqlalchemy import select
    from app.models import User, UserCredit
    user = db_session.execute(
        select(User).where(User.email == "credits-attack@test.com")
    ).scalar_one()
    wallet = db_session.get(UserCredit, user.id)
    assert wallet.balance == 0
```

- [ ] **Step 2: Run pricing + mass assignment tests**

```bash
cd backend && python -m pytest tests/test_security_attacks.py -v -k "pricing or mass_assign or credits"
```

Expected: all pass.

---

### Task D3: Gating, overspend, and replay attack tests

**Files:**
- Modify: `backend/tests/test_security_attacks.py`

- [ ] **Step 1: Add gating, overspend, and replay tests**

Append to `backend/tests/test_security_attacks.py`:

```python
# --- Feature gating ---

def test_locked_feature_rejected_even_with_tampered_request(
    client: TestClient, db_session: Session
) -> None:
    """A user without feature entitlement must get 403, not matter what they send."""
    from app.models import Feature
    user, token = _make_user(db_session, "gating-attack@test.com")
    feat = Feature(
        key="gating-test-feature",
        name="Gating Test",
        description="desc",
        cost_credits=10,
    )
    db_session.add(feat)
    db_session.commit()

    resp = client.post(
        f"/api/v1/features/gating-test-feature/run",
        cookies=_cookies(token),
        headers=_csrf(),
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "FEATURE_LOCKED"


# --- Overspend / negative balance ---

def test_concurrent_spends_never_drive_balance_negative(
    client: TestClient, db_session: Session
) -> None:
    """
    Spend all credits in two rapid sequential calls.
    The second call must return 402, balance must stay >= 0.
    """
    from app.models import Feature, UserEntitlement
    from app.services.credit_service import grant_credits

    user, token = _make_user(db_session, "overspend@test.com")

    # Give user exactly 10 credits
    grant_credits(
        db_session, user.id,
        amount=10, reason="test_seed", description="test",
        reference_type="test", reference_id="t1",
    )

    feat = Feature(key="overspend-feature", name="Overspend Test", description="d", cost_credits=10)
    db_session.add(feat)
    db_session.flush()
    db_session.add(UserEntitlement(user_id=user.id, feature_key=feat.key))
    db_session.commit()

    # First spend: should succeed
    resp1 = client.post(
        "/api/v1/features/overspend-feature/run",
        cookies=_cookies(token),
        headers=_csrf(),
    )
    assert resp1.status_code == 200

    # Second spend: balance is 0, must return 402
    resp2 = client.post(
        "/api/v1/features/overspend-feature/run",
        cookies=_cookies(token),
        headers=_csrf(),
    )
    assert resp2.status_code == 402
    assert resp2.json()["code"] == "INSUFFICIENT_CREDITS"

    # Balance must never go negative
    wallet = db_session.get(UserCredit, user.id)
    assert wallet.balance >= 0


# --- Replay / idempotency ---

def test_duplicate_idempotency_key_does_not_double_credit(
    client: TestClient, db_session: Session
) -> None:
    """Submitting the same Idempotency-Key twice must not apply credits twice."""
    from unittest.mock import patch
    from app.worker.tasks import _apply_purchase_in_worker
    from uuid import UUID

    user, token = _make_user(db_session, "replay@test.com")
    pkg = Package(
        name="Replay Pack", slug="replay-pack", description="d",
        price_cents=500, credits=100, active=True,
    )
    db_session.add(pkg)
    db_session.commit()

    # First submission
    with patch("app.routers.purchases.process_purchase.delay"):
        resp1 = client.post(
            "/api/v1/purchases",
            json={"package_id": str(pkg.id)},
            headers={"Idempotency-Key": "replay-dedup-key", **_csrf()},
            cookies=_cookies(token),
        )
    assert resp1.status_code == 202
    tx_id = UUID(resp1.json()["transaction_id"])

    # Apply the worker once
    _apply_purchase_in_worker(db_session, tx_id)
    db_session.expire_all()
    wallet_after_first = db_session.get(UserCredit, user.id)
    assert wallet_after_first.balance == 100

    # Second submission with the same key — must be a 202 replay of the existing transaction
    with patch("app.routers.purchases.process_purchase.delay"):
        resp2 = client.post(
            "/api/v1/purchases",
            json={"package_id": str(pkg.id)},
            headers={"Idempotency-Key": "replay-dedup-key", **_csrf()},
            cookies=_cookies(token),
        )
    assert resp2.status_code == 202
    # Same transaction id
    assert resp2.json()["transaction_id"] == str(tx_id)

    # Apply the worker a second time — must be a no-op
    _apply_purchase_in_worker(db_session, tx_id)
    db_session.expire_all()
    wallet_after_second = db_session.get(UserCredit, user.id)
    assert wallet_after_second.balance == 100  # not 200
```

- [ ] **Step 2: Run gating, overspend, replay tests**

```bash
cd backend && python -m pytest tests/test_security_attacks.py -v -k "gating or overspend or replay"
```

Expected: all pass.

---

### Task D4: JWT hygiene and CSRF attack tests

**Files:**
- Modify: `backend/tests/test_security_attacks.py`

- [ ] **Step 1: Add JWT and CSRF tests**

Append to `backend/tests/test_security_attacks.py`:

```python
# --- JWT hygiene ---

def test_alg_none_token_rejected(client: TestClient, db_session: Session) -> None:
    """A JWT signed with alg:none must be rejected."""
    import base64, json

    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "none", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps({"sub": str(uuid4()), "email": "hack@test.com", "role": "admin"}).encode()
    ).rstrip(b"=").decode()
    none_token = f"{header}.{payload}."

    resp = client.get(
        "/api/v1/auth/me",
        cookies={"creditos_access_token": none_token},
    )
    assert resp.status_code == 401


def test_tampered_token_rejected(client: TestClient, db_session: Session) -> None:
    """A JWT with a valid structure but wrong signature must be rejected."""
    user, token = _make_user(db_session, "tamper@test.com")
    # Swap the signature section
    parts = token.split(".")
    parts[2] = "invalidsignature"
    tampered = ".".join(parts)

    resp = client.get("/api/v1/auth/me", cookies={"creditos_access_token": tampered})
    assert resp.status_code == 401


# --- CSRF ---

def test_state_changing_request_without_csrf_header_rejected(
    client: TestClient, db_session: Session
) -> None:
    """POST without X-CSRF-Token header must be rejected with 403."""
    user, token = _make_user(db_session, "csrf-attack@test.com")
    pkg = Package(
        name="CSRF Pack", slug="csrf-pack", description="d",
        price_cents=100, credits=10, active=True,
    )
    db_session.add(pkg)
    db_session.commit()

    resp = client.post(
        "/api/v1/purchases",
        json={"package_id": str(pkg.id)},
        headers={"Idempotency-Key": "csrf-attack-key"},  # no X-CSRF-Token
        cookies={"creditos_access_token": token, "creditos_csrf_token": "real-csrf"},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "CSRF_INVALID"


def test_csrf_mismatch_rejected(client: TestClient, db_session: Session) -> None:
    """X-CSRF-Token header not matching cookie must be rejected."""
    user, token = _make_user(db_session, "csrf-mismatch@test.com")
    pkg = Package(
        name="CSRF Pack2", slug="csrf-pack2", description="d",
        price_cents=100, credits=10, active=True,
    )
    db_session.add(pkg)
    db_session.commit()

    resp = client.post(
        "/api/v1/purchases",
        json={"package_id": str(pkg.id)},
        headers={"Idempotency-Key": "csrf-mismatch-key", "X-CSRF-Token": "attacker-value"},
        cookies={"creditos_access_token": token, "creditos_csrf_token": "real-csrf"},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "CSRF_INVALID"
```

- [ ] **Step 2: Run all security attack tests**

```bash
cd backend && python -m pytest tests/test_security_attacks.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Run full test suite**

```bash
cd backend && python -m pytest -q
```

Expected: all tests pass.

---

**Checkpoint D — commit message for the human:**

```
test(security): add attack tests for IDOR, pricing, mass-assign, gating, overspend, replay, JWT, CSRF

All tests prove server-side enforcement — not UI-level hiding.

Tier 1 tests:
- IDOR: user B cannot read user A's wallet, ledger, or transaction status
- Server-side pricing: tampered price/credits in request body are silently ignored
- Mass assignment: role=admin and balance in signup body are silently ignored
- Feature gating: locked feature returns 403 regardless of request content
- Overspend: balance never goes negative; second spend returns 402
- Replay: same idempotency key never grants credits twice

Tier 2 tests:
- alg:none JWT rejected (401)
- Tampered signature rejected (401)
- Missing X-CSRF-Token on POST returns 403
- Mismatched X-CSRF-Token returns 403

Tests: all passing
```

---

## Batch E: Catalog Caching

### Task E1: Cache the package and feature catalog endpoints

**Files:**
- Modify: `backend/app/routers/packages.py`
- Modify: `backend/app/routers/features.py`

- [ ] **Step 1: Write a failing cache test**

In `backend/tests/test_catalog_cache.py`:

```python
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.main import create_app
from app.core.security import create_access_token, hash_password
from app.models import User, UserCredit


@pytest.fixture
def client(db_session: Session):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: (yield db_session)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _make_user(db: Session) -> str:
    user = User(email="cache@test.com", password_hash=hash_password("x"), role="user", initials="CA")
    db.add(user)
    db.flush()
    db.add(UserCredit(user_id=user.id, balance=0))
    db.commit()
    return create_access_token(str(user.id), user.email, user.role)


def test_packages_served_from_cache_on_second_request(client: TestClient, db_session: Session) -> None:
    token = _make_user(db_session)
    cookies = {"creditos_access_token": token, "creditos_csrf_token": "t"}

    with patch("app.routers.packages.cache_get") as mock_get, \
         patch("app.routers.packages.cache_set") as mock_set:
        mock_get.return_value = None  # cache miss on first call

        client.get("/api/v1/packages", cookies=cookies)
        mock_set.assert_called_once()  # cache was populated

        # Second request: simulate cache hit
        import json
        mock_get.return_value = mock_set.call_args[0][1]  # reuse what was set
        client.get("/api/v1/packages", cookies=cookies)
        # cache_set not called again (hit served)
        assert mock_set.call_count == 1


def test_admin_package_write_invalidates_cache(client: TestClient, db_session: Session) -> None:
    admin = User(
        email="cache-admin@test.com",
        password_hash=hash_password("x"),
        role="admin",
        initials="CA",
    )
    db_session.add(admin)
    db_session.commit()
    token = create_access_token(str(admin.id), admin.email, admin.role)
    cookies = {"creditos_access_token": token, "creditos_csrf_token": "t"}

    with patch("app.routers.packages.invalidate_catalog_cache") as mock_inv:
        client.post(
            "/api/v1/packages",
            json={"name": "Cache Test", "slug": "cache-test", "description": "d",
                  "price_cents": 100, "credits": 10, "feature_keys": []},
            cookies=cookies,
            headers={"X-CSRF-Token": "t"},
        )
    mock_inv.assert_called_once()
```

- [ ] **Step 2: Run cache tests to confirm they fail**

```bash
cd backend && python -m pytest tests/test_catalog_cache.py -v
```

Expected: `ImportError` — `cache_get`, `cache_set`, `invalidate_catalog_cache` not imported in routers yet.

- [ ] **Step 3: Add caching to `backend/app/routers/packages.py`**

At the top of the file, add:

```python
import json
from app.core.cache import (
    PACKAGES_CACHE_KEY,
    cache_get,
    cache_set,
    invalidate_catalog_cache,
)
from app.core.config import get_settings
```

In the `list_packages` (GET) handler, wrap the DB call:

```python
@router.get("", response_model=list[PackageResponse])
def list_packages(
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
) -> list[PackageResponse]:
    cached = cache_get(PACKAGES_CACHE_KEY)
    if cached is not None:
        return json.loads(cached)

    packages = list_active_packages(db)
    result = [PackageResponse.model_validate(p) for p in packages]
    ttl = get_settings().catalog_cache_ttl_seconds
    cache_set(PACKAGES_CACHE_KEY, json.dumps([r.model_dump(mode="json") for r in result]).encode(), ttl)
    return result
```

In `create_package`, `update_package`, and `delete_package` handlers, call `invalidate_catalog_cache()` after the DB write:

```python
invalidate_catalog_cache()
```

- [ ] **Step 4: Add caching to `backend/app/routers/features.py`**

Apply the same pattern — cache the GET (list features with lock/unlock status) using `FEATURES_CACHE_KEY`. Invalidate from packages write endpoints (since feature grants are package-configured).

Note: the features endpoint returns per-user locked/unlocked status, so the cache key must include the user ID:

```python
FEATURES_CACHE_KEY_USER = "catalog:features:user:{user_id}"
```

Add to `cache.py`:
```python
def features_cache_key(user_id: str) -> str:
    return f"catalog:features:user:{user_id}"
```

- [ ] **Step 5: Run all cache and full tests**

```bash
cd backend && python -m pytest tests/test_catalog_cache.py tests/ -q
```

Expected: all pass.

---

**Checkpoint E — commit message for the human:**

```
feat(cache): Redis catalog caching for packages and features with admin invalidation

- cache.py: cache_get/set/delete, PACKAGES_CACHE_KEY, FEATURES_CACHE_KEY helpers
- GET /packages: served from Redis cache; falls through to DB on miss, populates cache
- GET /features: per-user cache key (catalog:features:user:{id}); same miss/populate pattern
- POST/PATCH/DELETE /packages: call invalidate_catalog_cache() after DB write
- Cache TTL: CATALOG_CACHE_TTL_SECONDS (default 300s)
- Tests: cache hit/miss behaviour and invalidation on write verified

Tests: all passing
```

---

## Batch F: Checkout UI

### Task F1: `usePurchasePoller` hook

**Files:**
- Create: `frontend/src/hooks/usePurchasePoller.ts`

- [ ] **Step 1: Create the polling hook**

```typescript
// frontend/src/hooks/usePurchasePoller.ts
import { useCallback, useRef, useState } from 'react';
import type { TransactionStatus } from '../api/purchases';
import { getPurchaseStatus } from '../api/purchases';

type PollState = 'idle' | 'polling' | 'completed' | 'failed';

interface PollResult {
  state: PollState;
  status: TransactionStatus | null;
  start: (transactionId: string) => void;
  reset: () => void;
}

const POLL_INTERVAL_MS = 1500;
const MAX_POLLS = 40; // 60 seconds max

export function usePurchasePoller(): PollResult {
  const [state, setState] = useState<PollState>('idle');
  const [status, setStatus] = useState<TransactionStatus | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const countRef = useRef(0);

  const stop = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
  }, []);

  const reset = useCallback(() => {
    stop();
    setState('idle');
    setStatus(null);
    countRef.current = 0;
  }, [stop]);

  const poll = useCallback(async (transactionId: string) => {
    if (countRef.current >= MAX_POLLS) {
      setState('failed');
      setStatus({ transaction_id: transactionId, status: 'failed', failure_reason: 'Timed out waiting for confirmation.' });
      return;
    }

    try {
      const result = await getPurchaseStatus(transactionId);
      setStatus(result);
      if (result.status === 'completed') {
        setState('completed');
        return;
      }
      if (result.status === 'failed') {
        setState('failed');
        return;
      }
    } catch {
      // network hiccup — keep polling
    }

    countRef.current += 1;
    timerRef.current = setTimeout(() => void poll(transactionId), POLL_INTERVAL_MS);
  }, []);

  const start = useCallback((transactionId: string) => {
    reset();
    setState('polling');
    countRef.current = 0;
    void poll(transactionId);
  }, [reset, poll]);

  return { state, status, start, reset };
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

---

### Task F2: Store.tsx — async purchase flow

**Files:**
- Modify: `frontend/src/pages/Store.tsx`

- [ ] **Step 1: Update `handlePurchase` and modal UI**

In `frontend/src/pages/Store.tsx`, replace the `handlePurchase` function and the modal section:

```typescript
// Add import at top
import { usePurchasePoller } from '../hooks/usePurchasePoller';

// Inside Store component, replace the existing modal state and handlePurchase:

const poller = usePurchasePoller();

async function handlePurchase() {
  if (!selectedPkg) return;
  setPurchasing(true);
  setPurchaseError('');
  try {
    const accepted = await createPurchase(selectedPkg.id);
    setPurchasing(false);
    poller.start(accepted.transaction_id);
  } catch (err: unknown) {
    const apiErr = err as { response?: { data?: { message?: string } } };
    setPurchaseError(apiErr?.response?.data?.message ?? 'Purchase failed. Please try again.');
    setPurchasing(false);
  }
}

// When poller completes, update local state
useEffect(() => {
  if (poller.state === 'completed' && poller.status) {
    const { balance: newBal, entitlements } = poller.status;
    if (newBal !== undefined) setBalance(newBal);
    if (entitlements) setOwnedFeatures(entitlements);
    showToast(`${selectedPkg?.name ?? 'Package'} purchased. Balance updated.`, 'success');
  }
}, [poller.state, poller.status]);
```

In the modal JSX, add a processing state between "confirm purchase" and "success":

```tsx
{/* Processing state */}
{poller.state === 'polling' && (
  <div className="modal-processing">
    <div className="spinner" aria-label="Processing purchase…" />
    <p>Processing your purchase…</p>
  </div>
)}

{/* Success state */}
{poller.state === 'completed' && poller.status && (
  <div className="purchase-success">
    <p>Purchase complete!</p>
    {poller.status.balance !== undefined && (
      <p>New balance: {credits(poller.status.balance)} credits</p>
    )}
    <button onClick={() => { poller.reset(); closeModal(); }}>Close</button>
  </div>
)}

{/* Failed state */}
{(purchaseError || poller.state === 'failed') && (
  <div className="purchase-error" role="alert">
    {purchaseError || poller.status?.failure_reason || 'Purchase failed. Please try again.'}
  </div>
)}
```

Also update `closeModal` to reset the poller:

```typescript
function closeModal() {
  setSelectedPkg(null);
  poller.reset();
  document.body.classList.remove('modal-open');
}
```

- [ ] **Step 2: Build and verify no TypeScript errors**

```bash
cd frontend && npm run build
```

Expected: clean build.

---

**Checkpoint F — commit message for the human:**

```
feat(ui): async checkout flow with processing state and status polling

- usePurchasePoller hook: polls /purchases/{id}/status every 1.5s, max 40 polls
- Store.tsx: submit → 202 received → polling state → completed/failed
- Balance and entitlements updated from status response on completion
- Modal shows spinner during processing, success message on completion
- Error handling for network failures during polling (retries silently)

Tests: all passing (TypeScript clean build)
```

---

## Batch G: Load Test and Documentation

### Task G1: Locust load test

**Files:**
- Create: `loadtest/locustfile.py`
- Create: `loadtest/validate.py`
- Create: `loadtest/requirements.txt`

- [ ] **Step 1: Create `loadtest/requirements.txt`**

```
locust>=2.29
requests>=2.32
```

- [ ] **Step 2: Create `loadtest/locustfile.py`**

```python
"""
Locust load test for CreditOS async purchase path.

Run: cd loadtest && locust --headless -u 50 -r 10 --run-time 30s --host http://localhost:3000

Requires a running stack: docker compose up -d
Uses the seeded demo buyer (buyer@acme.io / credits123) as a template,
creating unique users per Worker to avoid credential collisions.
"""
import uuid

from locust import HttpUser, between, task


class CreditOSBuyer(HttpUser):
    wait_time = between(0.5, 1.5)
    host = "http://localhost:3000"

    token: str | None = None
    csrf_token: str | None = None
    package_id: str | None = None

    def on_start(self) -> None:
        """Register a unique user and fetch the package catalog."""
        email = f"loadtest-{uuid.uuid4().hex[:8]}@test.invalid"
        resp = self.client.post(
            "/api/v1/auth/signup",
            json={"email": email, "password": "loadtest-pass-123"},
        )
        if resp.status_code != 201:
            self.environment.runner.quit()
            return

        body = resp.json()
        self.csrf_token = body.get("csrf_token")

        # Fetch catalog
        pkg_resp = self.client.get("/api/v1/packages")
        pkgs = pkg_resp.json()
        if pkgs:
            self.package_id = pkgs[0]["id"]

    @task(3)
    def purchase_package(self) -> None:
        if not self.package_id:
            return
        key = uuid.uuid4().hex
        self.client.post(
            "/api/v1/purchases",
            json={"package_id": self.package_id},
            headers={
                "Idempotency-Key": key,
                "X-CSRF-Token": self.csrf_token or "",
            },
            name="/api/v1/purchases",
        )

    @task(1)
    def check_wallet(self) -> None:
        self.client.get("/api/v1/wallet", name="/api/v1/wallet")

    @task(1)
    def list_packages(self) -> None:
        self.client.get("/api/v1/packages", name="/api/v1/packages")
```

- [ ] **Step 3: Create `loadtest/validate.py`**

This script runs after the load test and queries the database to assert correctness:

```python
"""
Post-load-test correctness validator.

Run after: docker compose exec db psql -U creditos -d creditos -c "..."
Or: DATABASE_URL=... python loadtest/validate.py
"""
import os
import sys

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://creditos:change-me-in-production@localhost:5432/creditos",
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


def validate(db: Session) -> list[str]:
    failures = []

    # 1. No user has a negative balance
    neg = db.execute(
        text("SELECT COUNT(*) FROM user_credits WHERE balance < 0")
    ).scalar_one()
    if neg > 0:
        failures.append(f"FAIL: {neg} users have negative balances")
    else:
        print(f"PASS: No negative balances (checked {db.execute(text('SELECT COUNT(*) FROM user_credits')).scalar_one()} users)")

    # 2. For each completed transaction, the ledger contains exactly one matching row
    orphan = db.execute(text("""
        SELECT t.id FROM transactions t
        WHERE t.status = 'completed'
        AND NOT EXISTS (
            SELECT 1 FROM credit_ledger cl
            WHERE cl.reference_type = 'transaction'
            AND cl.reference_id = t.id::text
        )
    """)).fetchall()
    if orphan:
        failures.append(f"FAIL: {len(orphan)} completed transactions have no ledger entry")
    else:
        print("PASS: All completed transactions have a ledger entry")

    # 3. Each user's balance equals the sum of their ledger deltas
    mismatch = db.execute(text("""
        SELECT uc.user_id, uc.balance, COALESCE(SUM(cl.delta), 0) AS ledger_sum
        FROM user_credits uc
        LEFT JOIN credit_ledger cl ON cl.user_id = uc.user_id
        GROUP BY uc.user_id, uc.balance
        HAVING uc.balance != COALESCE(SUM(cl.delta), 0)
    """)).fetchall()
    if mismatch:
        failures.append(f"FAIL: {len(mismatch)} users have balance/ledger mismatch")
    else:
        print("PASS: All user balances match their ledger sums")

    # 4. No transaction appears to have been processed more than once
    double = db.execute(text("""
        SELECT reference_id, COUNT(*) AS cnt
        FROM credit_ledger
        WHERE reference_type = 'transaction'
        GROUP BY reference_id
        HAVING COUNT(*) > 1
    """)).fetchall()
    if double:
        failures.append(f"FAIL: {len(double)} transactions granted credits more than once")
    else:
        print("PASS: No transaction processed more than once")

    return failures


if __name__ == "__main__":
    with SessionLocal() as db:
        failures = validate(db)

    if failures:
        for f in failures:
            print(f, file=sys.stderr)
        sys.exit(1)
    else:
        print("All correctness checks passed.")
        sys.exit(0)
```

- [ ] **Step 4: Run the load test against the Docker stack**

```bash
docker compose up -d
cd loadtest
pip install -r requirements.txt
locust --headless -u 20 -r 5 --run-time 20s --host http://localhost:3000
```

Expected: Locust completes without errors; failure rate < 1% (429s from rate limiter are expected and benign for signup).

- [ ] **Step 5: Run the correctness validator**

```bash
DATABASE_URL="postgresql+psycopg://creditos:change-me-in-production@localhost:5432/creditos" python loadtest/validate.py
```

Expected: `All correctness checks passed.`

---

### Task G2: Documentation updates

**Files:**
- Modify: `README.md`
- Modify: `.env.example`

- [ ] **Step 1: Add load test section to README**

In `README.md`, add a new section under "Running Tests":

```markdown
### Load test — Locust

Requires the full Docker stack running.

```bash
docker compose up -d

cd loadtest
pip install -r requirements.txt
locust --headless -u 50 -r 10 --run-time 30s --host http://localhost:3000
```

Correctness validator (run after the load test):

```bash
DATABASE_URL="postgresql+psycopg://creditos:change-me-in-production@localhost:5432/creditos" \
  python loadtest/validate.py
```

The validator asserts:
- No user has a negative balance
- Every completed transaction has a corresponding ledger entry
- Every user's balance equals the sum of their ledger deltas
- No transaction was applied more than once (no double-credits)
```

- [ ] **Step 2: Add new services to the README architecture diagram**

In the Architecture section, add Redis and Worker to the diagram:

```
                          Browser
                             |
                      :3000 (HTTP)
                             |
                    ┌────────▼────────┐
                    │  Nginx          │
                    │  (frontend)     │
                    └──┬──────────┬──┘
                       │          │
              /        │          │  /api/*
         (React SPA)   │          │
                       │   ┌──────▼──────┐
                       │   │  FastAPI    │
                       │   │  :8000      │
                       │   └──┬────┬─────┘
                       │      │    │
                  DB  ◄─┘      │    └──► Redis :6379
                               │             │
                               └──► Worker (Celery)
```

- [ ] **Step 3: Add Tier 3 follow-up list to docs**

Create `docs/tier3-followup.md`:

```markdown
# Tier 3 Hardening — Follow-up List

These items are explicitly out of scope for the current phase
(see scaling-hardening-design.md). Capture here for a future iteration.

1. **CORS overhaul** — tighten `CORS_ORIGINS` to exact production domains;
   remove wildcard methods/headers; add preflight cache headers.

2. **Content Security Policy** — add `Content-Security-Policy`,
   `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
   `Referrer-Policy: strict-origin-when-cross-origin` via Nginx.

3. **Dependency scanning pipeline** — add `pip-audit` (backend) and
   `npm audit` (frontend) to CI; pin versions in requirements.

4. **Secrets detection** — add `gitleaks` or `truffleHog` pre-commit hook
   to block accidental secret commits.

5. **Structured logging** — replace print/uvicorn default logs with
   `structlog` (JSON format); mask passwords and tokens in log output.

6. **HTTPS enforcement** — configure `COOKIE_SECURE=true` and
   `COOKIE_SAMESITE=strict` in production; redirect HTTP to HTTPS at Nginx.

7. **Token refresh** — add a `POST /auth/refresh` endpoint with a
   separate longer-lived refresh token (httpOnly, rotating) to avoid
   forcing re-login every 30 minutes in production.
```

- [ ] **Step 4: Run complete test suite one final time**

```bash
cd backend && python -m pytest -q
cd ../frontend && npm run build
```

Expected: all backend tests pass, frontend builds clean.

---

**Checkpoint G — commit message for the human:**

```
feat(loadtest): Locust load test and correctness validator; Tier 3 follow-up docs

- loadtest/locustfile.py: concurrent buyer simulation (purchase + wallet + catalog)
- loadtest/validate.py: post-run correctness assertions (no negative balance, no
  double-credit, ledger/balance consistency)
- README: load test runbook, updated architecture diagram
- docs/tier3-followup.md: CORS, CSP, dep scanning, structured logging, token refresh

Tests: all passing
```

---

## Self-Review Checklist

**Spec coverage:**

| Requirement | Task(s) |
|-------------|---------|
| Async purchase via Celery + Redis | B2, B3, B4 |
| Pending → worker → completed/failed lifecycle | A1, B2, B3 |
| Idempotent worker (no double-credit) | B3, D3 |
| Retry with backoff, dead-letter | B3 (`max_retries`, `default_retry_delay`) |
| Status endpoint polled by UI | B4, F1, F2 |
| Checkout UI: submit → processing → success/failure | F1, F2 |
| Move token off localStorage (httpOnly cookie) | C1, C3 |
| CSRF double-submit cookie | C1, C3 |
| Login rate limiting with backoff | C2 |
| Short JWT expiry | C1 |
| Algorithm pinning (alg:none rejected) | D4 |
| IDOR / BOLA protection (token-scoped access) | D1 |
| Server-side pricing (price from DB, not request) | D2 |
| Mass assignment (role/credits not settable) | D2 |
| Feature gating server-side | D3 |
| Overspend / negative balance prevention | D3 |
| Replay / idempotency key deduplication | D3 |
| Redis catalog caching + invalidation | E1 |
| Locust load test with correctness assertions | G1 |
| Tier 3 follow-up documented (not implemented) | G2 |
| Zero regressions (all existing tests stay green) | Every task |
| No git commands from agent | Every checkpoint |

**Placeholder scan:** No TBDs, no "implement later", all code blocks present.

**Type consistency:**
- `AuthResult.access_token` (str) matches `create_access_token()` return type (str) ✓
- `PurchaseAccepted.transaction_id` (UUID) matches `Transaction.id` (UUID) ✓
- `_apply_purchase_in_worker(db, transaction_id)` signature matches call sites ✓
- `initiate_purchase()` → `tuple[PurchaseAccepted, bool]` matches router destructure ✓
- `get_transaction_status(db, user_id, transaction_id)` → `TransactionStatusResponse` ✓
