# Tier 3 Hardening — Production Follow-up

CreditOS Phase 2 implements the hardening and scaling features appropriate for a portfolio prototype running in a controlled environment. The items below are the next logical step for a production-grade deployment. They are explicitly out of scope for this project.

---

## Payment and Financial Controls

**Real payment gateway integration**
Replace the simulated purchase flow with a real provider (e.g. Stripe). The existing async architecture (202 → Celery task → status poll) maps cleanly onto a Stripe PaymentIntent lifecycle. The idempotency key sent to the purchase endpoint would be forwarded to Stripe as its `idempotency_key` parameter.

**Webhook-based confirmation**
Rather than polling, a production system would receive a `payment_intent.succeeded` webhook from Stripe and trigger the Celery task on that event, eliminating polling latency entirely.

**Refund and reversal flows**
Append a debit row to `credit_ledger` with a negative `delta` and a `reason = "refund"`. The `user_credits.balance` constraint (`balance >= 0`) is the structural guard against over-refunding.

---

## Secrets and Infrastructure

**Vault or secrets manager for credentials**
`JWT_SECRET`, `POSTGRES_PASSWORD`, and `REDIS_URL` are currently passed as environment variables. In production, these should be fetched from HashiCorp Vault, AWS Secrets Manager, or equivalent at startup — never stored in `.env` files or image layers.

**TLS termination**
The Nginx configuration serves HTTP internally. In production, TLS must be terminated at the load balancer or at Nginx using a certificate from Let's Encrypt or an internal CA.

**`COOKIE_SECURE=true` and `COOKIE_SAMESITE=strict`**
These are set to `false` / `lax` for local development. Flip both for any HTTPS deployment.

---

## Observability

**Distributed tracing**
Instrument FastAPI request handlers and the Celery worker with OpenTelemetry. A trace that spans from the HTTP purchase request through the task queue into the worker makes it possible to diagnose latency spikes and failed tasks without reading raw logs.

**Structured logging**
Replace the current `logging.getLogger` calls with a structured JSON logger (e.g. `structlog`). Every log line should carry `user_id`, `transaction_id`, and `request_id` fields so logs can be correlated across services.

**Metrics**
Expose a `/metrics` endpoint (Prometheus format) tracking: request latency by endpoint, queue depth, task processing duration, cache hit/miss ratio.

---

## Auth and Session

**Email verification**
The signup flow currently creates an account immediately. In production, send a confirmation email and require verification before granting access.

**Password reset**
Requires email delivery (SMTP or a transactional email provider) and a short-lived signed token stored server-side.

**Refresh token rotation**
The current 30-minute JWT is short by design. A production system would issue a long-lived refresh token (stored as an httpOnly cookie, rotated on each use) alongside the short-lived access token, so sessions survive without forcing re-login.

**OAuth / SSO**
The Login and Signup pages have non-functional Google OAuth buttons. Wiring them requires a real OAuth provider registration and a backend callback endpoint.

---

## Scalability

**Horizontal worker scaling**
The Celery worker currently runs as a single container. Under load, run multiple worker replicas (Docker Compose `scale` or a Kubernetes Deployment). Task deduplication is already handled by the idempotency key.

**Database connection pooling**
Add PgBouncer in front of PostgreSQL if the worker count grows. SQLAlchemy's built-in pool handles a single service, but multiple worker replicas each holding their own pool can exhaust PostgreSQL's `max_connections`.

**Distributed rate limiting**
The current `slowapi` rate limiter is in-process. With multiple FastAPI replicas, each instance has its own counter. Move to a Redis-backed limiter (also `slowapi` supports this via a Redis store) so the limit applies across all instances.

---

## Testing

**Contract tests**
Add consumer-driven contract tests (e.g. Pact) between the frontend API client and the backend routers to catch interface drift early.

**Chaos / fault injection**
Test that the idempotency guard holds under Celery worker crashes and network partitions. Libraries like `pytest-celery` or Testcontainers make this feasible in CI.

**Performance regression suite**
Run the Locust load test in CI against a staging environment and fail the build if p95 latency exceeds a defined threshold.
