"""
CreditOS load test — simulates concurrent buyers browsing the catalog and purchasing packages.

Usage:
    pip install -r requirements.txt
    export LOADTEST_PACKAGE_ID=<uuid-of-starter-package>
    locust -f locustfile.py --host http://localhost:8000 --users 50 --spawn-rate 5 --run-time 2m --headless

The test user must exist in the database before running:
    INSERT INTO users (id, email, password_hash, role, initials)
    VALUES (gen_random_uuid(), 'loadtest@example.com', <bcrypt-hash-of-LoadTest123!>, 'user', 'LO');
    INSERT INTO user_credits (user_id, balance) SELECT id, 0 FROM users WHERE email = 'loadtest@example.com';
"""

import os
import time
import uuid

from locust import HttpUser, between, task

STARTER_PACKAGE_ID = os.environ.get("LOADTEST_PACKAGE_ID", "")

_POLL_INTERVAL = 1.5
_MAX_POLLS = 20


class CreditOSUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self) -> None:
        self.csrf_token = ""
        with self.client.post(
            "/api/v1/auth/login",
            json={"email": "loadtest@example.com", "password": "LoadTest123!"},
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"Login failed: {resp.status_code} {resp.text[:200]}")
                self.environment.runner.quit()
                return
            self.csrf_token = self.client.cookies.get("creditos_csrf_token", "")
            if not self.csrf_token:
                resp.failure("creditos_csrf_token cookie missing after login")
                self.environment.runner.quit()

    @task(3)
    def browse_packages(self) -> None:
        with self.client.get("/api/v1/packages", catch_response=True) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"GET /packages returned {resp.status_code}")

    @task(1)
    def buy_package(self) -> None:
        if not STARTER_PACKAGE_ID:
            return

        idempotency_key = str(uuid.uuid4())
        with self.client.post(
            "/api/v1/purchases",
            json={"package_id": STARTER_PACKAGE_ID},
            headers={
                "X-CSRF-Token": self.csrf_token,
                "Idempotency-Key": idempotency_key,
            },
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 202):
                resp.failure(f"POST /purchases returned {resp.status_code}: {resp.text[:200]}")
                return
            body = resp.json()
            transaction_id = body.get("transaction_id")
            if not transaction_id:
                resp.failure("POST /purchases response missing transaction_id")
                return

        self._poll_until_done(transaction_id)

    def _poll_until_done(self, transaction_id: str) -> None:
        for _ in range(_MAX_POLLS):
            time.sleep(_POLL_INTERVAL)
            with self.client.get(
                f"/api/v1/purchases/{transaction_id}/status",
                name="/api/v1/purchases/[id]/status",
                catch_response=True,
            ) as resp:
                if resp.status_code != 200:
                    resp.failure(f"Status poll returned {resp.status_code}")
                    return
                body = resp.json()
                tx_status = body.get("status")
                if tx_status == "completed":
                    resp.success()
                    return
                if tx_status == "failed":
                    resp.failure(f"Transaction failed: {body.get('failure_reason', 'unknown')}")
                    return
        # timed out
        with self.client.get(
            f"/api/v1/purchases/{transaction_id}/status",
            name="/api/v1/purchases/[id]/status",
            catch_response=True,
        ) as resp:
            resp.failure("Timed out waiting for transaction to complete")
