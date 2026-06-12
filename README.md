# CreditOS

A full-stack portfolio prototype demonstrating a **credit-based feature-gating system**. Users buy credit packages, spend credits to run gated features, and view their transaction history through a wallet dashboard. Admins manage the package catalog. No real payments, no real OAuth -- all simulated.

**Tech stack:** FastAPI (Python 3.12) + React 18 / Vite / TypeScript + PostgreSQL 16 + Docker Compose

---

## Architecture

```
                        +-----------+
                        |  Browser  |
                        +-----+-----+
                              |
                        :3000 (HTTP)
                              |
                     +--------v--------+
                     |  Nginx (frontend)|
                     |  Static SPA      |
                     +---+----------+---+
                         |          |
                   /     |          | /api/*
              (React SPA)|          |
                         |   +------v------+
                         |   | FastAPI     |
                         |   | (backend)   |
                         |   | :8000       |
                         |   +------+------+
                         |          |
                         |   +------v------+
                         |   | PostgreSQL  |
                         |   | (db) :5432  |
                         |   +-------------+
                         |
                   index.html
```

All three services run inside a single Docker Compose network (`creditos`). The frontend Nginx container is the only one with a published port (3000). API requests are reverse-proxied from `/api/` to the backend on port 8000.

---

## Prerequisites

| Tool             | Version | Notes                           |
|------------------|---------|---------------------------------|
| Docker Desktop   | 24+     | Required for `docker compose`   |
| Node.js          | 20+     | Only for local frontend dev     |
| Python           | 3.12+   | Only for local backend dev      |

For the Docker-only workflow you only need Docker Desktop.

---

## Environment Setup

1. Copy the example env file:

   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and set values. The defaults work for local development:

   ```dotenv
   POSTGRES_USER=creditos
   POSTGRES_PASSWORD=change-me-in-production
   POSTGRES_DB=creditos
   JWT_SECRET=change-me-in-production-use-secrets-token-hex-32
   CORS_ORIGINS=http://localhost:3000
   ```

   To generate a strong JWT secret:

   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

---

## Docker Run Instructions

```bash
docker compose up --build
```

This will:

1. Start PostgreSQL 16 and wait for it to be healthy
2. Run Alembic migrations (`alembic upgrade head`)
3. Seed demo data (admin user, buyer user, packages, features, sample purchases)
4. Start the FastAPI server on port 8000 (internal)
5. Build the React SPA and serve it via Nginx on **port 3000**

Open [http://localhost:3000](http://localhost:3000) in your browser.

To stop:

```bash
docker compose down
```

To stop and remove the database volume:

```bash
docker compose down -v
```

---

## Demo Credentials

| Role  | Email                          | Password      |
|-------|--------------------------------|---------------|
| Admin | `admin@creditos.app`           | `credits123`  |
| Buyer | `buyer@acme.io`                | `credits123`  |

These are seeded automatically on first startup. The buyer account comes pre-loaded with credits and sample purchase history so the dashboard is not empty.

The email/password values can be overridden via the `SEED_ADMIN_EMAIL`, `SEED_USER_EMAIL`, `SEED_ADMIN_PASSWORD`, and `SEED_USER_PASSWORD` environment variables.

---

## API Summary

Base path: `/api/v1`

### Auth

| Method | Path               | Description              |
|--------|--------------------|--------------------------|
| POST   | `/auth/signup`     | Create account, get JWT  |
| POST   | `/auth/login`      | Authenticate, get JWT    |
| GET    | `/auth/me`         | Current user profile     |

### Packages (catalog)

| Method | Path                  | Description                        |
|--------|-----------------------|------------------------------------|
| GET    | `/packages`           | List all active packages           |
| POST   | `/packages`           | Create package (admin only)        |
| PATCH  | `/packages/{id}`      | Update package (admin only)        |
| DELETE | `/packages/{id}`      | Soft-delete package (admin only)   |

### Purchases

| Method | Path           | Description                                   |
|--------|----------------|-----------------------------------------------|
| POST   | `/purchases`   | Buy a package (requires `Idempotency-Key` header) |

### Features

| Method | Path                        | Description                     |
|--------|-----------------------------|---------------------------------|
| GET    | `/features`                 | List all features with lock status |
| POST   | `/features/{key}/run`       | Run a gated feature (spends credits) |

### Wallet

| Method | Path                 | Description                     |
|--------|----------------------|---------------------------------|
| GET    | `/wallet`            | Current balance and unlocked features |
| GET    | `/wallet/purchases`  | Purchase history                |
| GET    | `/wallet/ledger`     | Full credit ledger              |

### Health

| Method | Path       | Description   |
|--------|------------|---------------|
| GET    | `/health`  | Returns `{"status": "ok"}` |

---

## Design Decisions

### Credit Ledger

Every credit change (purchase top-up or feature spend) writes an append-only row to the `credit_ledger` table. Each row records the delta, reason, reference ID, and the resulting balance. The wallet balance in `user_credits` is the running total; the ledger is the audit trail.

### Idempotency

The `POST /purchases` endpoint requires an `Idempotency-Key` header (max 160 characters). The key is stored on the `transactions` table with a unique constraint per user. If a duplicate key is received, the original response is replayed (HTTP 200 instead of 201). If a race condition causes an `IntegrityError`, the service catches it, rolls back, and replays the original transaction.

### Feature Gating

Features are unlocked per-user when they purchase a package that grants that feature's entitlement. Running a feature checks (1) the user has the entitlement and (2) the user has enough credits. Credits are deducted atomically in the same database transaction as the feature run record.

---

## OAuth Note

Login and signup use email + password only. Google OAuth buttons may appear in the UI but are non-functional placeholders. OAuth integration is outside the scope of this prototype.

---

## Test Commands

### Backend (pytest) -- 80 tests

```bash
cd backend
pip install -r requirements.txt
python -m pytest -q
```

Or via Docker:

```bash
docker compose exec backend python -m pytest -q
```

### Frontend (Vitest) -- 12 tests

```bash
cd frontend
npm install
npx vitest run
```

### End-to-End (Playwright)

The e2e tests live in `frontend/e2e/` and require the full stack to be running:

```bash
docker compose up --build -d
cd frontend
npx playwright install --with-deps
npx playwright test
```

Test files: `auth.spec.ts`, `dashboard.spec.ts`, `store.spec.ts`, `playground.spec.ts`, `admin.spec.ts`

---

## Troubleshooting

### Port 3000 already in use

Another process is using port 3000. Either stop it or change the published port in `docker-compose.yml`:

```yaml
ports:
  - "3001:80"  # use 3001 instead
```

### Backend exits with "PostgreSQL is unavailable"

The database health check has a 10-second start period. If your machine is slow, increase `start_period` in `docker-compose.yml` under the `db` service healthcheck.

### Seed data not appearing

The seed script runs on every startup but is idempotent -- it skips rows that already exist. If you suspect stale data, remove the volume and restart:

```bash
docker compose down -v
docker compose up --build
```

### Alembic migration errors after schema changes

If you pulled new code with schema changes and the database volume has old data:

```bash
docker compose down -v
docker compose up --build
```

### CORS errors in the browser console

Make sure `CORS_ORIGINS` in your `.env` file includes the URL you are accessing the frontend from (default: `http://localhost:3000`).

---

## Project Structure

```
.
├── backend/
│   ├── app/
│   │   ├── core/         # Config, security, dependencies, error handling
│   │   ├── db/           # Session factory, seed script
│   │   ├── models/       # SQLAlchemy models
│   │   ├── routers/      # FastAPI route handlers
│   │   ├── schemas/      # Pydantic request/response models
│   │   └── services/     # Business logic layer
│   ├── alembic/          # Database migrations
│   ├── tests/            # pytest test suite (80 tests)
│   ├── Dockerfile
│   └── entrypoint.sh
├── frontend/
│   ├── src/              # React/TypeScript source
│   ├── e2e/              # Playwright end-to-end tests
│   ├── nginx.conf        # Reverse proxy config
│   └── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## License

This is a portfolio project. No license is granted for production use.
