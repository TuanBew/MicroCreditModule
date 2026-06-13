# CreditOS — Scaling & Security Hardening Design

**Date:** 2026-06-13  
**Branch:** `feat/scaling-and-hardening` (human-authored)  
**Status:** Approved — ready for planning

---

## 0. Scope

This document covers Step 2 of the CreditOS build. Step 1 delivered the full working application (auth, packages, purchases, ledger, gating, wallet, playground, admin, docker-compose, tests). Step 2 adds:

1. **Async purchase flow** — Celery + Redis, pending-transaction-then-enqueue, idempotent worker, status endpoint, UI polling.
2. **Tier 1 security hardening** — attack tests proving IDOR protection, server-side pricing, server-side gating, mass-assignment rejection, overspend prevention, and replay safety.
3. **Tier 2 auth hardening** — httpOnly cookie token storage, 30-min JWT expiry, login rate limiting.
4. **Catalog caching** — Redis cache for read-heavy package and feature endpoints, invalidated on admin writes.
5. **Locust load test** — concurrent-buyer spike with correctness assertions.

**Out of scope this phase:** real payment gateway, OAuth, S3, Tier 3 hardening (CORS overhaul, CSP suite, dependency scanning). These are documented as follow-ups in Section 9.

---

## 1. Transaction Status Lifecycle

### 1.1 New status values

```
pending → processing → completed
                   ↘ failed
```

`pending` — transaction row written, task enqueued, API returned 202.  
`processing` — worker has picked up the task and begun simulated payment.  
`completed` — credits granted, entitlements recorded, balance updated.  
`failed` — worker exhausted retries; no credits granted.

### 1.2 Additive Alembic migration

New columns on `transactions` (all nullable, no existing rows affected):

| Column | Type | Notes |
|--------|------|-------|
| `completed_at` | `DateTime(timezone=True)` nullable | Set when status reaches `completed` or `failed` |
| `failure_reason` | `String(255)` nullable | Set on `failed` |

The `status` column default changes from `"completed"` to `"pending"` for new rows only. No existing data is touched.

---

## 2. Async Purchase Flow

### 2.1 Full sequence

```
Browser                   FastAPI                Celery Worker              Postgres / Redis
  │                          │                        │                        │
  │ POST /api/v1/purchases   │                        │                        │
  │ Idempotency-Key: <uuid>  │                        │                        │
  │ ─────────────────────── ▶│                        │                        │
  │                          │ validate key (len, present)                     │
  │                          │ replay check ──────────────────────────────── ▶│
  │                          │ load package ──────────────────────────────── ▶│
  │                          │ INSERT Transaction(status="pending") ─────────▶│
  │                          │ enqueue process_purchase(transaction_id) ─────▶│ Redis
  │                          │ commit ────────────────────────────────────── ▶│
  │◀ 202 {transaction_id,    │                        │                        │
  │        status:"pending"} │                        │                        │
  │                          │                ◀ consume task                  │
  │                          │                        │ load Transaction ─────▶│
  │                          │                        │ if status ≠ "pending": noop
  │                          │                        │ status = "processing" ▶│
  │                          │                        │ commit ───────────────▶│
  │                          │                        │ simulate payment (0.5s sleep)
  │                          │                        │ grant_credits() ──────▶│
  │                          │                        │ add entitlements ─────▶│
  │                          │                        │ status = "completed"  │
  │                          │                        │ completed_at = now()  │
  │                          │                        │ commit ───────────────▶│
  │                          │                        │                        │
  │ GET /purchases/{id}/status │                      │                        │
  │ ─────────────────────── ▶│                        │                        │
  │◀ {status:"completed",    │                        │                        │
  │   balance, entitlements} │                        │                        │
```

### 2.2 Replay on the async path

A duplicate `POST /purchases` with the same idempotency key hits the existing replay check (unchanged) and returns the existing transaction including its current status. The caller can use the returned `transaction_id` to resume polling.

### 2.3 Idempotent worker

The worker is safe to run twice on the same `transaction_id`:

```python
def process_purchase(transaction_id: str) -> None:
    with db_session() as db:
        tx = db.get(Transaction, transaction_id, with_for_update=True)
        if tx is None or tx.status != "pending":
            return  # already processed or unknown — no-op
        tx.status = "processing"
        db.commit()

    # simulated payment (outside the lock)
    time.sleep(0.5)

    with db_session() as db:
        tx = db.get(Transaction, transaction_id, with_for_update=True)
        if tx.status != "processing":
            return  # raced with another worker instance — no-op
        grant_credits(db, ...)
        add_entitlements(db, ...)
        tx.status = "completed"
        tx.completed_at = utcnow()
        db.commit()
```

The credit grant, ledger write, entitlement union, balance update, and status transition are committed in a single `db.commit()`.

### 2.4 Retry and dead-letter

Celery task configuration:
- `max_retries = 3`
- `default_retry_delay = 2` (seconds, with `retry_backoff=True` → 2s, 4s, 8s)
- On `MaxRetriesExceededError`: set `status = "failed"`, `failure_reason = str(exc)`, `completed_at = now()`, commit. No credits granted.

The `failed` DB row is the dead-letter record. No separate broker DLQ is needed.

### 2.5 Status endpoint contract

```
GET /api/v1/purchases/{transaction_id}/status
Authorization: cookie creditos_access_token

200 OK — while pending or processing:
{
  "transaction_id": "uuid",
  "status": "pending" | "processing"
}

200 OK — on completion:
{
  "transaction_id": "uuid",
  "status": "completed",
  "balance": 132,
  "newly_unlocked": ["image-generation"],
  "entitlements": ["image-generation", "bulk-export"]
}

200 OK — on failure:
{
  "transaction_id": "uuid",
  "status": "failed",
  "failure_reason": "Simulated gateway timeout"
}

404 — transaction belongs to a different user (no information leakage)
```

---

## 3. Infrastructure Changes

### 3.1 New Docker Compose services

```yaml
redis:
  image: redis:7-alpine
  restart: unless-stopped
  networks: [creditos]
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]
    interval: 10s
    timeout: 5s
    retries: 5

worker:
  build:
    context: ./backend
    dockerfile: Dockerfile
  command: celery -A app.workers.celery_app worker --loglevel=info --concurrency=4
  restart: unless-stopped
  environment:
    DATABASE_URL: "postgresql+psycopg://..."
    REDIS_URL: ${REDIS_URL:-redis://redis:6379/0}
    JWT_SECRET: ${JWT_SECRET}
    CORS_ORIGINS: ${CORS_ORIGINS}
  depends_on:
    db:
      condition: service_healthy
    redis:
      condition: service_healthy
  networks: [creditos]
```

`backend` service also gains `REDIS_URL` env var. `worker` depends on `redis: service_healthy`.

### 3.2 New Python dependencies

Added to `pyproject.toml` `[project.dependencies]`:
- `celery[redis]>=5.4.0`
- `redis>=5.0.0`
- `slowapi>=0.1.9`

Added to `[project.optional-dependencies]` `loadtest`:
- `locust>=2.29.0`

### 3.3 SQLAlchemy pool sizing

Both `backend` and `worker` set `pool_size=4, max_overflow=2` on the async engine. Worst case: 4 API connections + 4 worker connections = 8 active, well under Postgres's default limit of 100. PgBouncer is noted as a future step.

### 3.4 New file layout

```
backend/app/
  workers/
    __init__.py
    celery_app.py      # Celery instance, broker/result/serializer config
    tasks.py           # process_purchase task with retry/backoff
  core/
    cache.py           # Redis client singleton, get/set/delete helpers
    rate_limit.py      # SlowAPI limiter instance and login dependency
loadtest/
  locustfile.py        # HttpUser with buyer and catalog tasks
  validate.py          # post-run correctness assertions (pytest)
  README.md
```

---

## 4. Auth Hardening

### 4.1 Token storage: httpOnly cookie + CSRF (Option A)

**Why Option A over Option B (in-memory + refresh token):** Option B's refresh-token security depends on token rotation and revocation — half-implementing these is worse than not doing them. Option A is simpler, provably correct, and appropriate for a single-origin SPA.

**Backend — login/signup response changes:**

`POST /auth/login` and `POST /auth/signup`:
- Set cookie: `creditos_access_token=<jwt>; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=<expiry_seconds>`
- Return JSON: `{ "csrf_token": "<32-byte-hex>", "user": { id, email, role, initials } }` — access token removed from body
- Store CSRF token in Redis: `csrf:<user_id>` → `<csrf_token>`, TTL = JWT expiry

`POST /auth/logout` (new):
- Clear cookie (set `Max-Age=0`)
- Delete `csrf:<user_id>` from Redis

**Backend — request validation:**

`get_current_user` reads token from `request.cookies["creditos_access_token"]` instead of the `Authorization` header. `OAuth2PasswordBearer` is removed.

New FastAPI dependency `require_csrf`:
- Applied to all `POST`, `PATCH`, `DELETE` routes
- Reads `X-CSRF-Token` header
- Validates against `csrf:<user_id>` in Redis
- Returns 403 on mismatch or missing

`GET` requests are exempt from CSRF validation.

**Frontend changes:**

`AuthContext.tsx`:
- Drops all `localStorage.setItem/getItem` for the token
- Stores only `user` object in React state
- On page reload, calls `GET /auth/me` (cookie is sent automatically) to rehydrate user state
- Stores `csrf_token` in a module-level variable (not in state — no re-render needed)

`client.ts`:
- Adds `withCredentials: true` to the axios instance (cookie sent in dev Vite proxy mode)
- Removes `Authorization` header interceptor
- Adds request interceptor: for non-GET requests, sets `X-CSRF-Token: <stored_csrf_token>`
- Keeps 401 interceptor (redirects to `/login`)

`TokenResponse` schema updated: `access_token` field replaced with `csrf_token`.

### 4.2 JWT hardening

| Setting | Before | After |
|---------|--------|-------|
| `jwt_expires_minutes` | 1440 (24h) | 30 (configurable via `ACCESS_TOKEN_EXPIRES_MINUTES`) |
| Algorithm pinning | `algorithms=[settings.jwt_algorithm]` ✓ | Unchanged — already correct |
| `JWT_SECRET` from env | ✓ | Unchanged |
| `alg: none` rejection | Implicit via pinned list ✓ | Confirmed by test |

Cookie `Max-Age` is derived from `jwt_expires_minutes * 60`.

### 4.3 Login rate limiting

`slowapi` wraps `POST /auth/login` only. Default: `LOGIN_RATE_LIMIT = "10/minute"` per IP, configurable via env. Breaching returns HTTP 429 with the standard API error envelope:

```json
{ "error": "RATE_LIMITED", "message": "Too many login attempts. Try again later." }
```

The `SlowAPI` limiter uses Redis as its store (same instance, key prefix `ratelimit:`).

---

## 5. Tier 1 Security Audit Results & Attack Tests

All Tier 1 gaps were audited against the current code. The table below records each finding and the attack test that proves the fix.

| Item | Gap found? | Fix | Attack test |
|------|-----------|-----|-------------|
| IDOR / BOLA | None — all wallet/ledger/purchase endpoints derive user from token only | Confirmed by audit; status endpoint follows same pattern | User B's token → user A's transaction ID → assert 404 |
| Server-side pricing | None — `PurchaseRequest` has only `package_id` | No code change; test confirms extras ignored | POST with extra `amount_cents=1, credits_granted=999999` → assert real values recorded |
| Server-side gating | None — `require_feature` is a server dep | No code change | User with no entitlements → `POST /features/image-generation/run` → assert 403 |
| Mass assignment | None — `SignupRequest` has only `email+password` | No code change | POST `/auth/signup` with extra `role=admin, balance=9999` → assert `role="user"`, `balance=0` |
| Overspend / negative balance | None — `WITH FOR UPDATE` + balance check in `spend_credits` | No code change | 5 concurrent spends of 10 credits from a 10-credit wallet → assert balance=0, never negative, one success |
| Replay / double-credit | None — `UniqueConstraint` + IntegrityError replay path | No code change | Same idempotency key twice → assert HTTP 200 on second call, credits granted once |

---

## 6. Catalog Caching

### 6.1 Cache keys and TTL

| Key | Source endpoint | Admin endpoint | TTL |
|-----|----------------|----------------|-----|
| `catalog:packages:active` | `GET /packages` (buyer) | — | `CATALOG_CACHE_TTL_SECONDS` (default 60) |
| `catalog:features` | `GET /features` | — | same TTL |

Admin `GET /packages` (all packages, including inactive) is never cached.

### 6.2 Invalidation

All three admin package write operations delete `catalog:packages:active` and `catalog:features`:
- `POST /packages` (create)
- `PATCH /packages/{id}` (update)
- `DELETE /packages/{id}` (soft-delete)

### 6.3 Cache helper

`backend/app/core/cache.py` exposes:
```python
get_redis() -> Redis          # module-level singleton from REDIS_URL
cache_get(key: str) -> Any | None
cache_set(key: str, value: Any, ttl: int) -> None
cache_delete(*keys: str) -> None
```

The catalog service functions accept `use_cache: bool = True` — tests pass `False` to skip Redis.

---

## 7. Locust Load Test

### 7.1 Scenario

`loadtest/locustfile.py` — one `HttpUser` class, two task groups:

**Task 1 — concurrent buyer spike (weight 3):**
1. Register a unique test user (inline, random email)
2. `GET /api/v1/packages` → pick the first active package
3. `POST /api/v1/purchases` with `Idempotency-Key: <uuid>`
4. Poll `GET /api/v1/purchases/{id}/status` every 500ms until `completed` or `failed` (max 30s)
5. `GET /api/v1/wallet` → record balance

**Task 2 — catalog read spike (weight 1):**
1. `GET /api/v1/packages`
2. `GET /api/v1/features`

### 7.2 Run command

```bash
cd loadtest
locust --headless --users 50 --spawn-rate 10 --run-time 60s \
       --host http://localhost:3000
```

### 7.3 Correctness assertions (post-run)

`loadtest/validate.py` queries Postgres after the run:

1. For each test user: `SUM(credits_granted WHERE status='completed') == current balance - starting balance`
2. `SELECT COUNT(*) FROM user_credits WHERE balance < 0` == 0
3. No duplicate ledger entries for the same `reference_id`

Run as `pytest loadtest/validate.py` — fails CI if any assertion breaks.

### 7.4 Acceptance bar

| Metric | Target |
|--------|--------|
| p95 latency `POST /purchases` | < 500ms |
| p95 latency `GET /purchases/{id}/status` | < 100ms |
| Correctness assertions | 0 failures |

---

## 8. Checkout UI Polling States

`Store.tsx` modal transitions:

| State | Trigger | User sees |
|-------|---------|-----------|
| `idle` | Initial open | "Pay $X" button |
| `submitting` | Button clicked | Spinner + "Submitting…" |
| `processing` | 202 received | Spinner + "Processing payment…" |
| `success` | Status = `completed` | Balance updated, links to Playground / Dashboard |
| `failed` | Status = `failed` or timeout | "Payment could not be processed. No charge was made." + retry |

A `usePurchasePoller` custom hook handles polling:
- Interval: 500ms
- Timeout: 30s → shows "still processing" fallback (not an error; user can close and check Dashboard)
- Returns `{ status, balance, entitlements, newlyUnlocked }`

`createPurchase` in `purchases.ts` returns `{ transaction_id, status }` (202 shape). The full grant result is received via the status endpoint when polling completes.

---

## 9. Risk Assessment

| Risk | Mitigation |
|------|------------|
| Feature-spend path broken | Migration is additive; `feature_service.py` untouched; existing tests cover it |
| Cookie not sent in Vite dev proxy | `withCredentials: true` on axios + `allow_credentials=True` in CORS middleware (already set) |
| Playwright tests break on auth flow change | Playwright's `page` sends cookies automatically; `APIRequestContext` also sends them with `withCredentials` |
| Tests that create tokens directly break | Test helpers switch to setting cookie on `TestClient` directly |
| 30-min expiry breaks long Playwright runs | `ACCESS_TOKEN_EXPIRES_MINUTES=60` in test env |
| Worker can't reach DB | Worker reuses backend image and `DATABASE_URL` env var |

---

## 10. Tier 3 Follow-Up List (Not In Scope This Phase)

To be addressed in a future hardening step:

- **CORS tightening**: Replace `allow_origins=["*"]` default with an explicit allowlist; remove `allow_methods=["*"]` and `allow_headers=["*"]`.
- **Security headers**: `Content-Security-Policy`, `Strict-Transport-Security`, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy` via Nginx or a FastAPI middleware.
- **Dependency scanning**: `pip-audit` and `npm audit` in CI on every push.
- **Secret scanning**: `git-secrets` or `trufflehog` in the pre-push hook.
- **Password complexity**: Enforce minimum complexity beyond length (e.g., at least one digit) server-side.
- **Refresh tokens**: If the app grows multi-tab or mobile, implement httpOnly refresh-token rotation (Option B from the design decision).
- **PgBouncer**: Connection pooler in front of Postgres for horizontal scale.

---

## 11. Environment Variables Added

Added to `.env.example`:

```bash
# Redis (Celery broker + result backend + catalog cache + rate limiter)
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1

# Auth token lifetime (minutes)
ACCESS_TOKEN_EXPIRES_MINUTES=30

# Login rate limit (slowapi format, per IP)
LOGIN_RATE_LIMIT=10/minute

# Catalog cache TTL (seconds)
CATALOG_CACHE_TTL_SECONDS=60

# Cookie settings (set COOKIE_SECURE=false for local dev without HTTPS)
COOKIE_SECURE=true
COOKIE_SAMESITE=strict
```
