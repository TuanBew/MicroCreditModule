# CreditOS

A full-stack portfolio prototype of a **credit-based feature-gating system** — the kind of monetisation primitive behind products like Runway, Replicate, or the OpenAI API. Users purchase credit packages, spend credits to run gated AI-style features, and track every transaction through a live wallet. Admins manage the package catalog through a dedicated UI.

No real payments. No real OAuth. Everything runs offline with a single `docker compose up`.

---

## Tech Stack

| Layer       | Technology                                                                    |
|-------------|-------------------------------------------------------------------------------|
| Frontend    | React 18, TypeScript, Vite, React Router 6, Axios                             |
| Backend     | FastAPI (Python 3.12), SQLAlchemy 2, Alembic                                  |
| Database    | PostgreSQL 16                                                                 |
| Auth        | JWT (HS256) — httpOnly cookie + CSRF double-submit (Phase 2)                  |
| Queue       | Celery + Redis 7 — async purchase processing (Phase 2)                        |
| Serving     | Nginx reverse-proxy in front of the React SPA                                 |
| Dev/deploy  | Docker Compose                                                                |
| Testing     | pytest · Vitest + React Testing Library · Playwright · Locust (Phase 2)       |

---

## Architecture

```mermaid
flowchart LR
    subgraph client ["Browser"]
        browser["React SPA"]
    end
    subgraph gateway ["Nginx :3000"]
        nginx["Reverse Proxy"]
    end
    subgraph service ["Application Layer"]
        fastapi["FastAPI Backend"]
        worker["Celery Worker"]
    end
    subgraph datastore ["Data Stores"]
        postgres["PostgreSQL 16"]
        redisStore["Redis Cache"]
    end
    subgraph async ["Task Queue"]
        taskQueue["Purchase Task Queue"]
    end

    browser -->|"HTTPS"| nginx
    nginx -->|"Routes /api"| fastapi
    fastapi -->|"Read / Write"| postgres
    fastapi -->|"Cache / Rate limit"| redisStore
    fastapi -.->|"Enqueue purchase"| taskQueue
    taskQueue -.->|"Consume task"| worker
    worker -->|"Write credits"| postgres
```

> [View interactive architecture diagram in FigJam](https://www.figma.com/board/uEno7HDsjFsFJNXbY1fDPq)

All services share a Docker Compose network (`creditos`). Only Nginx publishes a port (3000). API requests from the browser are proxied at the Nginx layer from `/api/` → `http://backend:8000/api/`. The Celery worker shares the backend image and database connection but runs as a separate process consuming tasks from Redis.

---

## Features

### Buyer flow

| Page               | What it does                                                                             |
|--------------------|------------------------------------------------------------------------------------------|
| **Login / Signup** | Email + password auth; session stored in httpOnly cookie (no localStorage)               |
| **Store**          | Browse and purchase credit packages; async processing with live status polling           |
| **Dashboard**      | Live credit balance, unlocked features, purchase history, full credit ledger             |
| **Playground**     | Run any of the four gated mock features; credits deducted per run; HTTP 402 when empty   |

### Admin flow

| Page               | What it does                                                                             |
|--------------------|------------------------------------------------------------------------------------------|
| **Admin → Packages** | Create, edit, and soft-delete packages; toggle active/inactive; assign feature grants  |

---

## Phase 2: Scaling & Security Hardening

Phase 1 shipped a complete, working application. Phase 2 is about making it defensible and scalable — closing the gap between "it works in a demo" and "it holds up under real conditions."

### What problems this solves

**Synchronous purchases are a liability.** Phase 1's purchase endpoint granted credits inline, inside the HTTP request. That works in isolation, but payment gateways have latency, retry logic is error-prone, and a request timeout at the wrong moment can leave a transaction half-written. Async processing with idempotent workers separates "accept the purchase" from "fulfil the purchase," making each half simpler and independently reliable.

**`localStorage` is the wrong place for auth tokens.** Any injected JavaScript — from a compromised dependency, an ad script, a browser extension — can read `localStorage`. In a system where tokens authorise financial transactions, that trade-off is unacceptable. `httpOnly` cookies are inaccessible to scripts entirely. CSRF double-submit is the standard counterpart that protects against the one attack cookies open up.

**An unguarded login endpoint is an open door.** Without rate limiting, brute-forcing passwords is just a matter of time and bandwidth. Rate limiting per IP raises the bar enough to make credential stuffing impractical.

**Read-heavy endpoints shouldn't hit the database on every request.** The package catalog is loaded on every store visit, by every user, but changes only when an admin writes to it. Caching it in Redis with invalidation on writes removes the unnecessary load.

### Async purchase architecture

```mermaid
flowchart LR
    subgraph client ["Browser"]
        checkout["Checkout Click"]
        poller["Status Poller"]
    end
    subgraph gateway ["Nginx"]
        nginx["Reverse Proxy"]
    end
    subgraph service ["Backend"]
        purchaseApi["Purchase API"]
        purchaseWorker["Celery Worker"]
    end
    subgraph datastore ["Database"]
        postgres["PostgreSQL"]
    end
    subgraph async ["Task Queue"]
        purchaseQueue["Task Queue"]
    end

    checkout -->|"POST /purchases"| nginx
    poller -->|"GET /status"| nginx
    nginx -->|"Route"| purchaseApi
    purchaseApi -->|"Write pending tx"| postgres
    purchaseApi -.->|"Enqueue task"| purchaseQueue
    purchaseQueue -.->|"Consume"| purchaseWorker
    purchaseWorker -->|"Grant credits"| postgres
```

> [View async flow diagram in FigJam](https://www.figma.com/board/uEno7HDsjFsFJNXbY1fDPq)

**How it works:**

1. `POST /purchases` writes a `pending` transaction row and returns `202 Accepted` with the `transaction_id`. No credits are granted yet.
2. A Celery task (`process_purchase`) is enqueued with the transaction ID.
3. The browser polls `GET /purchases/{id}/status` every 1.5 seconds.
4. The worker picks up the task, acquires a row-level lock (`SELECT FOR UPDATE`), checks the status is still `"pending"` (idempotency guard), grants credits, and marks the transaction `"completed"`.
5. The next poll sees `"completed"` and the UI updates with the new balance.

The worker is safe to run twice: if a task is retried by Celery's at-least-once delivery, the status check (`!= "pending"`) makes the second run a no-op. Credits are never double-granted.

### Security design

**Token storage — httpOnly cookies + CSRF double-submit**

| | Before (Phase 1) | After (Phase 2) |
|--|---|---|
| Token location | `localStorage` | `httpOnly` cookie — inaccessible to JavaScript |
| CSRF protection | None needed (header-based auth) | Double-submit cookie: JS reads `creditos_csrf_token` cookie, sends as `X-CSRF-Token` header; backend compares with `secrets.compare_digest` |
| Token lifetime | 24 hours | 30 minutes (configurable) |
| Login protection | None | slowapi rate limiter — 10 requests/minute per IP |

**Why this matters:** An XSS attack that injects a script can exfiltrate a `localStorage` token silently. The same attack cannot read an `httpOnly` cookie. CSRF is the complementary risk: a malicious site can trigger cross-origin requests that carry the user's cookie — but it cannot read the CSRF token from a different origin, so the `X-CSRF-Token` header check blocks the attack.

**Server-side invariants (audited, no code changes needed):**

- IDOR protection — all wallet, ledger, and transaction endpoints derive the user from the JWT, never from request parameters
- Server-side pricing — `PurchaseRequest` carries only `package_id`; price and credits are always read from the database
- Mass assignment prevention — `SignupRequest` accepts only `email` and `password`; `role` and `balance` cannot be set by a client
- Overspend prevention — `spend_credits` uses `SELECT FOR UPDATE` + balance check; negative balances are structurally impossible
- Replay safety — idempotency key stored with a unique-per-user constraint; duplicates replay the original without creating a second charge

### Current progress

| Step | What it builds | Status |
|------|----------------|--------|
| **Step 1** — Infrastructure | Redis + Celery worker added to Docker Compose; Alembic migration for transaction status lifecycle (`pending → processing → completed / failed`); config, cache module, Celery app | ✅ Done |
| **Step 2** — Async purchase flow | `POST /purchases` → 202; idempotent Celery worker; `GET /purchases/{id}/status` endpoint; updated tests | ✅ Done |
| **Step 3** — Auth hardening | httpOnly cookie auth; CSRF double-submit on all state-changing endpoints; login rate limiting; frontend drops localStorage, adds CSRF interceptor | ✅ Done |
| **Step 4** — Attack tests | 13 pytest tests proving server-side enforcement: IDOR blocked, tampered prices rejected, mass assignment rejected, overspend blocked, JWT tampering rejected, CSRF bypass blocked | ✅ Done |
| **Step 5** — Catalog caching | Redis cache on `GET /packages` for buyer path; invalidated on admin POST/PATCH/DELETE; 6 cache-behaviour tests | ✅ Done |
| **Step 6** — Async store UI | `usePurchasePoller` hook (1.5 s poll, 60 s timeout, abort guard); Store modal transitions: idle → processing → success / failed | ✅ Done |
| **Step 7** — Load test | Locust concurrent-buyer simulation (50 users, `browse_packages` + `buy_package` tasks); correctness validator verifying no negative balances and no double-credits | ✅ Done |

---

## Quick Start

### Prerequisite

[Docker Desktop](https://www.docker.com/products/docker-desktop/) 24+ — that's all you need.

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
1. Start PostgreSQL and Redis, wait for both to be healthy
2. Run Alembic migrations (`alembic upgrade head`)
3. Seed demo users, packages, features, and sample transactions
4. Start the Celery worker (purchase processing)
5. Serve the React SPA via Nginx on **port 3000**

```bash
# Stop
docker compose down

# Stop and wipe the database volume
docker compose down -v
```

---

## Demo Accounts

Two accounts are seeded automatically on first startup.

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
| `REDIS_URL`           | `redis://redis:6379/0`                             | Used for Celery, catalog cache, and rate limiting  |
| `ACCESS_TOKEN_EXPIRES_MINUTES` | `30`                                    | JWT and cookie lifetime                            |
| `LOGIN_RATE_LIMIT`    | `10/minute`                                        | slowapi format, per IP                             |
| `CATALOG_CACHE_TTL_SECONDS` | `300`                                        | Redis TTL for package/feature catalog cache        |
| `COOKIE_SECURE`       | `false`                                            | Set `true` in production (requires HTTPS)          |
| `COOKIE_SAMESITE`     | `lax`                                              | `strict` recommended in production                 |
| `SEED_ADMIN_EMAIL`    | `admin@creditos.app`                               | Override demo admin email                          |
| `SEED_ADMIN_PASSWORD` | `credits123`                                       | Override demo admin password                       |
| `SEED_USER_EMAIL`     | `buyer@acme.io`                                    | Override demo buyer email                          |
| `SEED_USER_PASSWORD`  | `credits123`                                       | Override demo buyer password                       |

---

## API Reference

**Docker base URL:** `http://localhost:3000/api/v1` (proxied through Nginx)  
**Direct backend URL:** `http://localhost:8000/api/v1` (local dev only)  
**Interactive docs (Swagger UI):** `http://localhost:8000/docs`

All protected endpoints require the `creditos_access_token` cookie (set automatically on login). State-changing endpoints also require the `X-CSRF-Token` header (value from the `creditos_csrf_token` cookie).

### Auth

| Method | Path           | Auth | Description                                                          |
|--------|----------------|------|----------------------------------------------------------------------|
| POST   | `/auth/signup` | —    | Register; sets auth cookies; returns `{ csrf_token, user }`         |
| POST   | `/auth/login`  | —    | Authenticate; sets auth cookies; returns `{ csrf_token, user }`     |
| GET    | `/auth/me`     | Cookie | Current user profile                                               |

### Packages

| Method | Path             | Auth        | Description                                      |
|--------|------------------|-------------|--------------------------------------------------|
| GET    | `/packages`      | Cookie      | List active packages (Redis-cached, Phase 2)     |
| POST   | `/packages`      | Cookie + CSRF (admin) | Create package                        |
| PATCH  | `/packages/{id}` | Cookie + CSRF (admin) | Update package                        |
| DELETE | `/packages/{id}` | Cookie + CSRF (admin) | Soft-delete                           |

### Purchases

| Method | Path                          | Auth         | Description                                                              |
|--------|-------------------------------|--------------|--------------------------------------------------------------------------|
| POST   | `/purchases`                  | Cookie + CSRF | Buy a package. Returns HTTP 202 (new) or HTTP 200 (replay). Requires `Idempotency-Key` header. |
| GET    | `/purchases/{id}/status`      | Cookie       | Poll transaction status: `pending`, `processing`, `completed`, `failed` |

### Features

| Method | Path                  | Auth         | Description                                                      |
|--------|-----------------------|--------------|------------------------------------------------------------------|
| GET    | `/features`           | Cookie       | All features with per-user `locked` / `unlocked` status          |
| POST   | `/features/{key}/run` | Cookie + CSRF | Run a feature and deduct credits. HTTP 402 = insufficient, HTTP 403 = locked |

### Wallet

| Method | Path                | Auth   | Description                                  |
|--------|---------------------|--------|----------------------------------------------|
| GET    | `/wallet`           | Cookie | Current balance and list of unlocked features |
| GET    | `/wallet/purchases` | Cookie | Purchase history                             |
| GET    | `/wallet/ledger`    | Cookie | Full append-only credit ledger               |

### Health

| Method | Path      | Auth | Description                              |
|--------|-----------|------|------------------------------------------|
| GET    | `/health` | —    | Returns `{"status":"ok"}`                |

---

## Running Tests

### Backend — 87 pytest tests

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
cd frontend && npm run dev &
cd frontend
npx playwright install --with-deps
npx playwright test
```

**`e2e/` — 11 tests** targeting the Docker Compose stack (`http://localhost:3000`):

```bash
docker compose up --build -d
cd e2e
npm install
npx playwright install --with-deps chromium
npm test
```

### Load test (Locust)

Simulates 50 concurrent buyers: 75% catalog browsing, 25% full purchase + poll cycle.

```bash
# 1. Install dependencies
pip install -r loadtest/requirements.txt

# 2. Seed a load-test user in the running database
docker compose exec backend python -c "
from app.db.session import SessionLocal
from app.services.auth_service import signup
from app.schemas.auth import SignupRequest
db = SessionLocal()
signup(db, SignupRequest(email='loadtest@example.com', password='LoadTest123!'))
db.close()
print('done')
"

# 3. Look up the starter package ID
docker compose exec backend python -c "
from app.db.session import SessionLocal
from app.models import Package
db = SessionLocal()
pkg = db.query(Package).filter_by(slug='starter').first()
print(pkg.id)
db.close()
"

# 4. Run the load test (replace <uuid> with the id from step 3)
export LOADTEST_PACKAGE_ID=<uuid>
locust -f loadtest/locustfile.py \
  --host http://localhost:3000 \
  --users 50 --spawn-rate 5 --run-time 2m --headless

# 5. Validate correctness after the run
export DATABASE_URL=postgresql://creditos:change-me-in-production@localhost:5432/creditos
python loadtest/validate.py
```

Expected output from `validate.py`: `PASS: no correctness violations found`

### Test summary

| Suite          | Count | Runner     |
|----------------|-------|------------|
| Backend        | 106   | pytest     |
| Frontend unit  | 12    | Vitest     |
| Frontend e2e   | 15    | Playwright |
| Standalone e2e | 11    | Playwright |
| **Total**      | **144** |          |

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
export REDIS_URL=redis://localhost:6379/0

alembic upgrade head
python -m app.db.seed
uvicorn app.main:app --reload --port 8000

# In a second terminal — Celery worker
celery -A app.worker.celery_app worker --loglevel=info
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
│   │   ├── core/        # Config, JWT, security, CSRF, cache, rate limiter
│   │   ├── db/          # Session factory, seed script
│   │   ├── models/      # SQLAlchemy ORM models
│   │   ├── routers/     # FastAPI route handlers
│   │   ├── schemas/     # Pydantic v2 request/response models
│   │   ├── services/    # Business logic
│   │   └── worker/      # Celery app + tasks (Phase 2)
│   ├── alembic/         # Database migration scripts
│   ├── tests/           # pytest suite (87 tests)
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── api/         # Axios modules + CSRF interceptor
│   │   ├── components/  # Shared UI components
│   │   ├── context/     # AuthContext (cookie-based session)
│   │   ├── pages/       # Login, Signup, Dashboard, Store, Playground, Admin
│   │   └── __tests__/   # Vitest unit tests
│   ├── e2e/             # Playwright tests targeting the Vite dev server
│   ├── nginx.conf       # Reverse-proxy + SPA fallback config
│   └── Dockerfile
├── e2e/                 # Standalone Playwright tests targeting the Docker stack
├── loadtest/
│   ├── locustfile.py    # Locust concurrent-buyer simulation
│   ├── validate.py      # Post-run correctness validator (checks ledger integrity)
│   └── requirements.txt
├── docs/
│   ├── scaling-hardening-design.md   # Phase 2 design document
│   ├── scaling-hardening-plan.md     # Phase 2 implementation plan
│   └── tier3-followup.md             # Production hardening items out of scope for this prototype
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Design Decisions

### Append-only credit ledger

Every balance change appends a new row to `credit_ledger` recording the delta, reason, reference ID, and resulting balance. The `user_credits` table holds a denormalised running total for fast reads; the ledger is the audit trail. This mirrors how real billing systems work — historical records are never mutated.

### Idempotent purchases

`POST /purchases` requires an `Idempotency-Key` header stored with a unique-per-user constraint. A duplicate key replays the original response without creating a second charge. In Phase 2, the async worker adds a second layer of idempotency: it checks `tx.status != "pending"` before applying credits, making it safe under Celery's at-least-once delivery.

### httpOnly cookies over localStorage

Phase 1 stored the JWT in `localStorage` for simplicity. Phase 2 moves to `httpOnly` cookies because any XSS that can read `localStorage` can silently exfiltrate auth tokens. `httpOnly` cookies are structurally inaccessible to JavaScript. The CSRF double-submit pattern is the standard companion: JS reads a non-httpOnly `creditos_csrf_token` cookie and sends it as a header; the server compares using `secrets.compare_digest`. A cross-origin attacker can neither read the cookie value nor forge the header.

### Feature gating at the service layer

Lock/unlock state is derived at query time by joining `user_entitlements` with the `features` table — no materialised flag to get out of sync. The credit deduction and the feature-run record are written in the same database transaction.

### Soft deletes on packages

Deleting a package sets `active = false` rather than removing the row. Historical purchase records keep their foreign-key reference valid.

---

## Known Limitations (by design)

- **No real payments** — purchases accept any request and process credits directly.
- **No email verification or password reset** — out of scope for a portfolio prototype.
- **Google/OAuth buttons are non-functional UI placeholders** — no OAuth flow is wired.
- **Mock AI features** — the four gated features return simulated output, not real AI calls.
- **Phase 2 complete** — all hardening and scaling steps are implemented. Tier 3 production hardening (real payment gateway, Vault secrets, distributed tracing) is out of scope; see `docs/tier3-followup.md`.

---

## Troubleshooting

**Port 3000 already in use**  
Change the published port in `docker-compose.yml`: `"3001:80"`, then open `http://localhost:3001`.

**Backend exits immediately on startup**  
Run `docker compose logs backend`. Usually a migration error or Postgres not ready yet. Try:
```bash
docker compose down -v && docker compose up --build
```

**Worker not processing purchases**  
Check `docker compose logs worker`. Redis must be healthy before the worker starts. Try:
```bash
docker compose restart worker
```

**Seed data missing after changing SEED_* vars**  
The seed script is idempotent and skips existing rows. Wipe the volume so it re-seeds:
```bash
docker compose down -v && docker compose up --build
```

**`npm ci` fails during Docker build**  
`package-lock.json` must be generated on Linux. If you regenerated it on Windows, run:
```bash
docker run --rm -v "${PWD}/frontend:/app" -w /app node:20-alpine npm install
```
then rebuild.

---

## License

Portfolio project. No licence is granted for production use.
