"""
CreditOS post-load-test correctness validator.

Connects to PostgreSQL and checks three invariants that must hold after any load run:
  1. No user has a negative credit balance.
  2. No (user_id, idempotency_key) pair has more than one completed transaction
     (would indicate double-credit application).
  3. No purchase-type ledger entry has a negative delta (credits_granted must be > 0).

Exit 0 on clean, exit 1 on any violation.

Usage:
    export DATABASE_URL=postgresql://creditos:creditos@localhost:5432/creditos
    python validate.py
"""

import os
import sys

import psycopg2

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://creditos:creditos@localhost:5432/creditos",
)


def main() -> None:
    try:
        conn = psycopg2.connect(DATABASE_URL)
    except Exception as exc:
        print(f"FAIL: could not connect to database: {exc}")
        sys.exit(1)

    failures: list[str] = []

    with conn:
        with conn.cursor() as cur:
            # Check 1: negative balances
            cur.execute("SELECT COUNT(*) FROM user_credits WHERE balance < 0")
            (count,) = cur.fetchone()
            if count > 0:
                failures.append(f"negative balance: {count} row(s) in user_credits have balance < 0")

            # Check 2: double-credit — same (user_id, idempotency_key) completed more than once
            cur.execute("""
                SELECT user_id, idempotency_key, COUNT(*) AS n
                FROM transactions
                WHERE status = 'completed'
                GROUP BY user_id, idempotency_key
                HAVING COUNT(*) > 1
            """)
            rows = cur.fetchall()
            if rows:
                failures.append(
                    f"double-credit: {len(rows)} (user_id, idempotency_key) pair(s) "
                    f"have multiple completed transactions"
                )

            # Check 3: negative purchase credits in ledger
            cur.execute("""
                SELECT COUNT(*)
                FROM credit_ledger
                WHERE reason = 'purchase' AND delta < 0
            """)
            (count,) = cur.fetchone()
            if count > 0:
                failures.append(
                    f"negative purchase credit: {count} ledger row(s) have reason='purchase' and delta < 0"
                )

    conn.close()

    if failures:
        for msg in failures:
            print(f"FAIL: {msg}")
        sys.exit(1)

    print("PASS: no correctness violations found")
    sys.exit(0)


if __name__ == "__main__":
    main()
