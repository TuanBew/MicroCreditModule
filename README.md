# CreditOS

A full-stack portfolio prototype of a **credit-based feature-gating system** — the kind of monetisation primitive behind products like Runway, Replicate, or the OpenAI API. Users purchase credit packages, spend credits to run gated AI-style features, and track every transaction through a live wallet. Admins manage the package catalog through a dedicated UI.

No real payments. No real OAuth. Everything runs offline with a single `docker compose up`.

---

## Tech Stack

| Layer       | Technology                                                   |
|-------------|--------------------------------------------------------------|
| Frontend    | React 18, TypeScript, Vite, React Router 6, Axios            |
| Backend     | FastAPI (Python 3.12), SQLAlchemy 2 (async), Alembic         |
| Database    | PostgreSQL 16                                                |
| Auth        | JWT (HS256) — email + password only, no third-party OAuth    |
| Serving     | Nginx reverse-proxy in front of the React SPA                |
| Dev/deploy  | Docker Compose                                               |
| Testing     | pytest · Vitest + React Testing Library · Playwright         |

---

## Architecture

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
                       │   └──────┬──────┘
                       │          │
                       │   ┌──────▼──────┐
                       │   │  PostgreSQL │
                       │   │  :5432      │
                       │   └─────────────┘
```

All three services share a Docker Compose network (`creditos`). Only Nginx publishes a port (3000). API requests from the browser are reverse-proxied at the Nginx layer from `/api/` → `http://backend:8000/api/` — no CORS headers needed in Docker mode.

---

## Features

### Buyer flow

| Page               | What it does                                                                             |
|--------------------|------------------------------------------------------------------------------------------|
| **Login / Signup** | Email + password auth; JWT stored in `localStorage`                                      |
| **Store**          | Browse and purchase credit packages; idempotency-keyed so double-clicks are safe         |
| **Dashboard**      | Live credit balance, unlocked features, purchase history, full credit ledger             |
| **Playground**     | Run any of the four gated mock features; credits deducted per run; HTTP 402 when empty   |

### Admin flow

| Page               | What it does                                                                             |
|--------------------|------------------------------------------------------------------------------------------|
| **Admin → Packages** | Create, edit, and soft-delete packages; toggle active/inactive; assign feature grants  |

---

## Quick Start

### Prerequisite

[Docker Desktop](https://www.docker.com/products/docker-desktop/) 24+ — that's all you need for the Docker workflow.

### Run

```bash
# 1. Clone
git clone <repo-url>
cd CreditModule

# 2. Create your .env (all defaults work for local)
cp .env.example .env

# 3. Start everything
docker compose up --build
```

Open **http://localhost:3000** in your browser.

On first start Docker will:
1. Start PostgreSQL and wait for it to be healthy
2. Run Alembic migrations (`alembic upgrade head`)
3. Seed demo users, packages, features, and sample transactions
4. Serve the React SPA via Nginx on **port 3000**

```bash
# Stop
docker compose down

# Stop and wipe the database volume
docker compose down -v
```

---

## Demo Accounts

Two accounts are seeded automatically on first startup. Use them to explore every flow without creating new accounts.

### Buyer

| Field    | Value            |
|----------|------------------|
| Email    | `buyer@acme.io`  |
| Password | `credits123`     |
| Role     | buyer            |

Starts with **32 credits** and 4 unlocked features so the dashboard and playground are not empty on first login.

### Admin

| Field    | Value                  |
|----------|------------------------|
| Email    | `admin@creditos.app`   |
| Password | `credits123`           |
| Role     | admin                  |

Admin-role accounts are redirected to `/admin` on login. Only this role can access the package management UI.

> These credentials are intentionally public — they exist solely for portfolio review. Override them via `.env` for any non-throwaway deployment.

---

## Environment Variables

| Variable              | Default                                            | Notes                                              |
|-----------------------|----------------------------------------------------|----------------------------------------------------|
| `POSTGRES_USER`       | `creditos`                                         |                                                    |
| `POSTGRES_PASSWORD`   | `change-me-in-production`                          | Change for any real deployment                     |
| `POSTGRES_DB`         | `creditos`                                         |                                                    |
| `JWT_SECRET`          | `change-me-in-production-use-secrets-token-hex-32` | Generate: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `CORS_ORIGINS`        | `http://localhost:3000`                            | Comma-separated for multiple origins               |
| `SEED_ADMIN_EMAIL`    | `admin@creditos.app`                               | Override demo admin email                          |
| `SEED_ADMIN_PASSWORD` | `credits123`                                       | Override demo admin password                       |
| `SEED_USER_EMAIL`     | `buyer@acme.io`                                    | Override demo buyer email                          |
| `SEED_USER_PASSWORD`  | `credits123`                                       | Override demo buyer password                       |

---

## API Reference

**Docker base URL:** `http://localhost:3000/api/v1` (proxied through Nginx)  
**Direct backend URL:** `http://localhost:8000/api/v1` (local dev only)  
**Interactive docs (Swagger UI):** `http://localhost:8000/docs`

All protected endpoints require `Authorization: Bearer <token>`.

### Auth

| Method | Path           | Auth | Description                                  |
|--------|----------------|------|----------------------------------------------|
| POST   | `/auth/signup` | —    | Register; returns `{ access_token, user }`   |
| POST   | `/auth/login`  | —    | Authenticate; returns `{ access_token, user }` |
| GET    | `/auth/me`     | JWT  | Current user profile                         |

### Packages

| Method | Path             | Auth        | Description                                      |
|--------|------------------|-------------|--------------------------------------------------|
| GET    | `/packages`      | JWT         | List active packages                             |
| POST   | `/packages`      | JWT (admin) | Create package                                   |
| PATCH  | `/packages/{id}` | JWT (admin) | Update package name, price, credits, features    |
| DELETE | `/packages/{id}` | JWT (admin) | Soft-delete (sets `is_active = false`)           |

### Purchases

| Method | Path         | Auth | Description                                                               |
|--------|--------------|------|---------------------------------------------------------------------------|
| POST   | `/purchases` | JWT  | Buy a package. Requires `Idempotency-Key` header (max 160 chars). Returns HTTP 201 on creation, HTTP 200 on replay. |

### Features

| Method | Path                  | Auth | Description                                                      |
|--------|-----------------------|------|------------------------------------------------------------------|
| GET    | `/features`           | JWT  | All features with per-user `locked` / `unlocked` status          |
| POST   | `/features/{key}/run` | JWT  | Run a feature and deduct credits. HTTP 402 = insufficient credits, HTTP 403 = feature locked |

### Wallet

| Method | Path                | Auth | Description                                  |
|--------|---------------------|------|----------------------------------------------|
| GET    | `/wallet`           | JWT  | Current balance and list of unlocked features |
| GET    | `/wallet/purchases` | JWT  | Purchase history                             |
| GET    | `/wallet/ledger`    | JWT  | Full append-only credit ledger               |

### Health

| Method | Path      | Auth | Description                              |
|--------|-----------|------|------------------------------------------|
| GET    | `/health` | —    | Returns `{"status":"ok"}` (root path — not under `/api/v1`) |

---

## Running Tests

### Backend — 80 pytest tests

```bash
cd backend
pip install -r requirements.txt
python -m pytest -q
```

Or against the running Docker container:

```bash
docker compose exec backend python -m pytest -q
```

### Frontend unit tests — 12 Vitest tests

Tests cover the Admin Packages page: table rendering, status pills, feature chip display, create/edit/delete modal flows, and API call verification.

```bash
cd frontend
npm install
npx vitest run
```

### End-to-end — two Playwright packages

**`frontend/e2e/` — 15 tests** targeting the Vite dev server (`http://localhost:5173`):

```bash
# Start the backend + dev server first
cd frontend && npm run dev &

# Then run:
cd frontend
npx playwright install --with-deps
npx playwright test
```

Spec files: `auth.spec.ts`, `dashboard.spec.ts`, `store.spec.ts`, `playground.spec.ts`, `admin.spec.ts`

**`e2e/` — 11 tests** targeting the Docker Compose stack (`http://localhost:3000`):

```bash
docker compose up --build -d

cd e2e
npm install
npx playwright install --with-deps chromium
npm test
```

Spec files: `tests/auth-routing.spec.ts`, `tests/store-wallet-playground.spec.ts`, `tests/admin-packages.spec.ts`

Override the target URL: `E2E_BASE_URL=http://your-host npm test`

### Test summary

| Suite          | Count | Runner     |
|----------------|-------|------------|
| Backend        | 80    | pytest     |
| Frontend unit  | 12    | Vitest     |
| Frontend e2e   | 15    | Playwright |
| Standalone e2e | 11    | Playwright |
| **Total**      | **118** |          |

---

## Local Development (without Docker)

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export DATABASE_URL=postgresql+asyncpg://creditos:password@localhost:5432/creditos
export JWT_SECRET=dev-secret

alembic upgrade head
python -m app.db.seed        # seed demo data
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev    # http://localhost:5173
```

The Vite dev server proxies `/api/` → `http://localhost:8000/api/` (see `vite.config.ts`).

---

## Project Structure

```
.
├── backend/
│   ├── app/
│   │   ├── core/        # Config (pydantic-settings), JWT, security, error handlers
│   │   ├── db/          # Async session factory, seed script
│   │   ├── models/      # SQLAlchemy ORM models (User, Package, Feature, CreditLedger…)
│   │   ├── routers/     # FastAPI route handlers (auth, packages, purchases, features, wallet)
│   │   ├── schemas/     # Pydantic v2 request/response models
│   │   └── services/    # Business logic (wallet ops, feature gating, idempotency)
│   ├── alembic/         # Database migration scripts
│   ├── tests/           # pytest suite (80 tests)
│   ├── Dockerfile
│   └── entrypoint.sh    # Runs migrations + seed + uvicorn
├── frontend/
│   ├── src/
│   │   ├── api/         # Axios modules (one per domain: auth, packages, wallet…)
│   │   ├── components/  # Shared UI components
│   │   ├── contexts/    # AuthContext (JWT state + user profile)
│   │   ├── pages/       # Login, Signup, Dashboard, Store, Playground, Admin
│   │   └── __tests__/   # Vitest unit tests
│   ├── e2e/             # Playwright tests targeting the Vite dev server
│   ├── nginx.conf       # Reverse-proxy + SPA fallback config
│   └── Dockerfile       # Multi-stage: Vite build → Nginx serve
├── e2e/                 # Standalone Playwright tests targeting the Docker stack
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Design Decisions

### Append-only credit ledger

Every balance change appends a new row to `credit_ledger` recording the delta, reason, reference ID, and resulting balance. The `user_credits` table holds a denormalised running total for fast reads; the ledger is the audit trail. This mirrors how real billing systems work — historical records are never mutated.

### Idempotent purchases

`POST /purchases` requires an `Idempotency-Key` header stored with a unique-per-user constraint. A duplicate key replays the original response without creating a second charge. A concurrent duplicate that loses the race to the DB `INSERT` catches the `IntegrityError`, rolls back, and replays the original — making the endpoint safe under client retries and network timeouts.

### Feature gating at the service layer

Lock/unlock state is derived at query time by joining `user_features` (what the user has purchased) with the `features` table — no materialised flag to get out of sync. The credit deduction and the feature-run record are written in the same database transaction, so a crash between them is impossible.

### Credits cannot go negative

The service checks `balance >= cost` before deducting. Failure returns HTTP 402 (`INSUFFICIENT_CREDITS`). If the feature is not unlocked at all the endpoint returns HTTP 403 (`FEATURE_LOCKED`).

### Soft deletes on packages

Deleting a package sets `is_active = false` rather than removing the row. Historical purchase records keep their foreign-key reference valid. Both the buyer store and the admin catalog filter on `is_active = true`.

---



## License

Portfolio project. No licence is granted for production use.
