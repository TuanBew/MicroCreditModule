# CreditOS — Verification Report

## 1. Project Summary

CreditOS is a full-stack SaaS credit system built as a portfolio demonstration project. It models a real-world "buy credits, unlock features, spend credits" workflow: buyers purchase credit packages, receive feature entitlements, and consume credits by running gated AI-style features (image generation, auto-posting, bulk export, audience insights). The backend is a FastAPI + PostgreSQL service with a SQLAlchemy 2.0 ORM, Alembic migrations, and JWT authentication; the frontend is a React 18 + Vite TypeScript SPA served via nginx. The full stack ships as a three-service Docker Compose application and is covered by 52 pytest backend tests and 16 Playwright E2E tests.

---

## 2. Architecture Diagram

### Request Flow

```
Browser
  |
  | HTTP (port 3000)
  v
nginx (frontend container)
  |--- serves static React/Vite SPA (dist/)
  |--- proxies /api/* requests
  |
  | HTTP (internal Docker network: creditos)
  v
FastAPI (backend container, port 8000)
  |--- JWT auth middleware (PyJWT + bcrypt)
  |--- /api/v1/auth        (signup, login, /me)
  |--- /api/v1/features    (catalog list + feature run)
  |--- /api/v1/packages    (catalog CRUD, admin-gated)
  |--- /api/v1/purchases   (idempotent package purchase)
  |--- /api/v1/wallet      (balance, ledger, purchase history)
  |
  | SQLAlchemy 2.0 / psycopg3
  v
PostgreSQL 16 (db container, port 5432)
  |--- users, user_credits, user_entitlements
  |--- features, packages, package_features
  |--- transactions, credit_ledger, feature_runs
```

### Docker Compose Services

```
docker-compose.yml
├── db          postgres:16-alpine
│               volume: postgres_data
│               healthcheck: pg_isready
│
├── backend     python:3.12-slim
│               depends_on: db (healthy)
│               entrypoint: alembic upgrade head → uvicorn
│               exposes: 8000 (internal)
│
└── frontend    node:20-alpine (build) → nginx:alpine (serve)
                depends_on: backend
                publishes: 3000:80
```

---

## 3. Feature Inventory

| Feature | Layer | Description | Key Files |
|---|---|---|---|
| FastAPI app skeleton, health check | Backend | `GET /health` returns `{"status":"ok"}`; CORS, error handlers wired | `backend/app/main.py` |
| SQLAlchemy 2.0 models | Backend | 9 tables: users, features, packages, package_features, transactions, credit_ledger, user_credits, user_entitlements, feature_runs | `backend/app/models/` |
| Alembic migrations + seed data | Backend | Migrations auto-run on container start; seed inserts admin + demo buyer with full ledger history | `backend/alembic/`, `backend/app/db/seed.py` |
| JWT authentication | Backend | Signup (201, creates zero-balance wallet), login (200, returns bearer token), `/me` (returns current user); bcrypt passwords, 72-byte limit enforced | `backend/app/routers/auth.py`, `backend/app/services/auth_service.py`, `backend/app/core/security.py` |
| Role dependencies | Backend | `require_admin` → 403 FORBIDDEN for non-admins; `require_buyer` → 403 for admins; `require_feature` → 403/404 for locked/unknown features | `backend/app/core/deps.py` |
| Feature catalog API | Backend | `GET /api/v1/features` (authenticated, all roles) | `backend/app/routers/features.py` |
| Package catalog API | Backend | `GET /api/v1/packages` (buyers: active only; admins: all); `POST`, `PATCH`, `DELETE` (admin only, soft-delete deactivates) | `backend/app/routers/packages.py`, `backend/app/services/catalog_service.py` |
| Credit ledger | Backend | Append-only `credit_ledger` table; each row records delta, balance_after, reason, reference. `grant_credits` and `spend_credits` use `SELECT FOR UPDATE` on `user_credits` to prevent double-spend | `backend/app/services/credit_service.py` |
| Idempotent package purchase | Backend | `POST /api/v1/purchases` requires `Idempotency-Key` header; replays existing transaction on key reuse; 409 if same key used for different package | `backend/app/routers/purchases.py`, `backend/app/services/purchase_service.py` |
| Wallet API | Backend | `GET /api/v1/wallet` (balance + owned features); `GET /api/v1/wallet/purchases` (newest-first); `GET /api/v1/wallet/ledger` (newest-first) | `backend/app/routers/wallet.py`, `backend/app/services/wallet_service.py` |
| Feature gating + mock feature runs | Backend | `POST /api/v1/features/{key}/run`; checks entitlement (403 FEATURE_LOCKED), balance (402 INSUFFICIENT_CREDITS), existence (404 FEATURE_NOT_FOUND); records FeatureRun row and ledger entry; mock result payloads per feature key | `backend/app/routers/feature_runs.py`, `backend/app/services/feature_service.py` |
| React SPA — Login / Signup | Frontend | Pre-filled demo credentials; "Use admin demo" toggle; role-aware redirect (buyer → /dashboard, admin → /admin) | `frontend/src/pages/Login.tsx`, `frontend/src/pages/Signup.tsx` |
| React SPA — Dashboard | Frontend | Credit balance display; Purchase history tab + Credit activity (ledger) tab; Axios client with JWT Authorization interceptor | `frontend/src/pages/Dashboard.tsx`, `frontend/src/context/AuthContext.tsx` |
| React SPA — Store | Frontend | Package grid loaded from API; purchase modal with Pay button; idempotency key generated per attempt; success state shows new balance | `frontend/src/pages/Store.tsx` |
| React SPA — Playground | Frontend | 4 feature panels loaded from `/api/v1/wallet`; owned/affordable → Run button active; locked → "Go to Store" link; result card shown on success | `frontend/src/pages/Playground.tsx` |
| React SPA — Admin | Frontend | Package table (all packages including inactive); New package modal with feature checkbox list; edit / soft-delete | `frontend/src/pages/Admin.tsx` |
| Role-based protected routes | Frontend | `ProtectedRoute` redirects unauthenticated users to `/login`; redirects buyers away from `/admin` | `frontend/src/components/ProtectedRoute.tsx` |
| Docker Compose deployment | Infrastructure | Three-service compose; backend entrypoint runs migrations before starting uvicorn; frontend two-stage build (node → nginx); db healthcheck gates backend start | `docker-compose.yml`, `backend/Dockerfile`, `frontend/Dockerfile`, `backend/entrypoint.sh` |
| Playwright E2E tests | Testing | 16 tests across auth, dashboard, store, playground, and admin flows against the running full stack | `frontend/e2e/` |

---

## 4. Test Coverage Summary

### Backend Tests (pytest)

| File | Tests | Covers |
|---|---|---|
| `test_health.py` | 1 | Health check endpoint returns 200 `{"status":"ok"}` |
| `test_models.py` | 1 | All 9 expected SQLAlchemy table names are registered in `Base.metadata` |
| `test_seed.py` | 6 | Seed data integrity: 4 features, 4 packages with correct values and feature mappings; demo buyer wallet state (balance=32, 3 entitlements, 2 transactions, 6 ledger rows); idempotent re-seeding; password hashes |
| `test_auth.py` | 13 | Password hashing and verification; JWT round-trip; signup (201, zero wallet, email normalization); duplicate signup (409); bcrypt 72-byte limit on signup and login; login (200/401); `/me` with and without token; admin-string email still creates buyer role |
| `test_catalog.py` | 12 | Feature list (authenticated/unauthenticated); package list filtered by role; admin create/patch/delete; buyer blocked from mutate operations (parametrized); validation rejects zero price/credits/empty features/unknown features |
| `test_purchase_ledger.py` | 19 | `grant_credits` / `spend_credits` service calls; SELECT FOR UPDATE lock assertion; insufficient spend raises `InsufficientCreditsError` without writing ledger; balance equals sum of ledger deltas; purchase endpoint (idempotency key required/oversized/conflict); active/inactive package; transaction + ledger written correctly; entitlements granted without duplicates; re-purchase stacks credits; idempotent replay returns 200; wallet GET/purchases/ledger endpoints |
| `test_feature_gating.py` | 23 | `run_feature` service: all four mock features (success payloads); 402 for insufficient balance; 403 for no entitlement; 404 for unknown key; balance floor; response fields; FeatureRun row persisted; CreditLedger row written; no FeatureRun row on failed spend; `require_feature` dependency (locked/not-found/success); HTTP endpoint (201 success, 404, 403, 402); sequential double-spend depletion (no overdraft) |

**Total backend test functions: 75**

### Playwright E2E Tests

| File | Tests | Covers |
|---|---|---|
| `auth.spec.ts` | 4 | Pre-filled buyer login → /dashboard; admin demo button → /admin; unauthenticated redirect to /login; logout |
| `dashboard.spec.ts` | 2 | Balance number visible after load; Purchase history / Credit activity tabs toggle correctly |
| `store.spec.ts` | 3 | Package grid loads; purchase modal opens; complete purchase shows success state and updated balance |
| `playground.spec.ts` | 3 | 4 feature panels visible; locked panel shows "Go to Store" link; available feature run produces result card |
| `admin.spec.ts` | 3 | Buyer redirected from /admin; admin sees "Manage credit packages" heading; admin creates new package via modal |

**Total E2E tests: 16**

---

## 5. API Endpoint Inventory

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/health` | None | Liveness probe — returns `{"status":"ok"}` |
| `POST` | `/api/v1/auth/signup` | None | Create account (role=user); returns JWT + user; creates zero-balance wallet |
| `POST` | `/api/v1/auth/login` | None | Verify credentials; returns JWT + user |
| `GET` | `/api/v1/auth/me` | Bearer (any role) | Return current user from JWT |
| `GET` | `/api/v1/features` | Bearer (any role) | List all features with key, name, description, cost, unlock_package_name |
| `POST` | `/api/v1/features/{feature_key}/run` | Bearer (buyer only) | Run a gated feature; charges credits; returns FeatureRunResponse with result_payload. Errors: 402 INSUFFICIENT_CREDITS, 403 FEATURE_LOCKED, 404 FEATURE_NOT_FOUND |
| `GET` | `/api/v1/packages` | Bearer (any role) | List packages — buyers receive active-only; admins receive all including inactive |
| `POST` | `/api/v1/packages` | Bearer (admin only) | Create a new credit package with feature assignments |
| `PATCH` | `/api/v1/packages/{package_id}` | Bearer (admin only) | Update package fields and/or feature assignments |
| `DELETE` | `/api/v1/packages/{package_id}` | Bearer (admin only) | Soft-delete (deactivate) a package; returns 204 |
| `POST` | `/api/v1/purchases` | Bearer (buyer only) | Purchase a package; `Idempotency-Key` header required; grants credits + entitlements; replays on key reuse |
| `GET` | `/api/v1/wallet` | Bearer (buyer only) | Current balance + list of all features with `owned` flag |
| `GET` | `/api/v1/wallet/purchases` | Bearer (buyer only) | Completed transactions, newest first |
| `GET` | `/api/v1/wallet/ledger` | Bearer (buyer only) | Credit ledger entries (grants and spends), newest first |

---

## 6. Key Design Decisions

- **Append-only credit ledger instead of a mutable counter.** Every credit movement writes a `credit_ledger` row with `delta`, `balance_after`, `reason`, and a typed `reference_id`. This gives an auditable history and allows balance reconstruction from the ledger sum. A denormalized `user_credits.balance` cache is kept for fast reads.

- **`SELECT FOR UPDATE` on `user_credits`.**  Both `grant_credits` and `spend_credits` lock the wallet row before reading the balance and writing the ledger entry. This prevents concurrent requests from reading the same stale balance and each approving a spend that would overdraft the account.

- **UUID pre-generated for `FeatureRun` before the credit spend.** The `feature_service` allocates the `FeatureRun` row's UUID before calling `spend_credits`, so the ledger entry can reference the run ID in `reference_id`. If the spend fails (402), the pre-allocated object is never flushed — no phantom run row is left in the database.

- **Idempotency key on purchases enforced at the HTTP layer.** The `Idempotency-Key` header is required (400 if absent) and capped at 160 characters. The service layer checks for a matching `Transaction` row; a replay returns the original response with HTTP 200 instead of 201. A key reused against a different package returns 409 `IDEMPOTENCY_KEY_CONFLICT`.

- **Soft-delete for packages.** Admin `DELETE /packages/{id}` sets `active=False` rather than removing the row. This preserves foreign-key references from historical `Transaction` rows and keeps the package visible to admins.

- **Role segregation via FastAPI dependencies.** `require_admin`, `require_buyer`, and `require_feature` are injectable dependencies that raise structured `ApiError` exceptions. This keeps router handlers free of role-check logic and makes the access model testable in isolation.

- **Structured error responses everywhere.** All errors — including FastAPI's built-in `RequestValidationError` — are caught by registered exception handlers and serialized as `{"code": "...", "message": "...", "details": {...}}`. Frontend code can match on `code` without parsing message strings.

- **Two-stage Docker build for the frontend.** The frontend Dockerfile uses a `node:20-alpine` builder stage to produce a `dist/` bundle, then copies it into `nginx:alpine`. The final image contains no Node.js toolchain, keeping the production image small.

- **Migrations run automatically at container startup.** The backend `entrypoint.sh` waits for PostgreSQL to pass `pg_isready`, runs `alembic upgrade head`, then starts uvicorn. This means a fresh `docker compose up --build` is fully self-initializing with no manual migration step.

---

## 7. How to Run

### Production-like (Docker Compose)

```bash
# 1. Copy environment template
cp .env.example .env
# Edit .env — at minimum set a strong JWT_SECRET

# 2. Build and start all services
docker compose up --build

# App is available at http://localhost:3000
# API is available at http://localhost:3000/api/v1 (proxied by nginx)
# or directly at http://localhost:8000/api/v1
```

### Local Development

**Backend (requires a running PostgreSQL instance):**

```bash
cd backend
pip install -e ".[test]"

# Set DATABASE_URL and JWT_SECRET in a local .env or as env vars
export DATABASE_URL="postgresql+psycopg://creditos:password@localhost:5432/creditos"
export JWT_SECRET="dev-secret"

alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

**Frontend:**

```bash
cd frontend
npm install
# Set VITE_API_BASE_URL in frontend/.env.local if backend is not at http://localhost:8000
npm run dev
# App available at http://localhost:5173
```

### Backend Tests

```bash
# From the repo root or backend/ directory
pytest backend/tests/

# With coverage (if pytest-cov is installed)
pytest backend/tests/ --cov=app
```

### E2E Tests (Playwright)

Playwright tests require the full stack to be running (both backend and frontend).

```bash
# Start the stack first (Docker Compose or local dev servers)
docker compose up --build -d

# Then run the tests
cd frontend
npx playwright test

# Run a specific spec
npx playwright test e2e/auth.spec.ts

# Open interactive UI mode
npx playwright test --ui
```
