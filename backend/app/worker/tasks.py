from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import SessionLocal
from app.models import Package, Transaction, UserCredit, UserEntitlement
from app.services.credit_service import grant_credits
from app.worker.celery_app import celery_app


def _apply_purchase_in_worker(db: Session, transaction_id: UUID) -> None:
    """
    Idempotent purchase processor. Safe to call multiple times.
    If the transaction is not in "pending" state, this is a no-op.
    """
    tx = db.execute(
        select(Transaction)
        .options(selectinload(Transaction.package))
        .with_for_update()
        .where(Transaction.id == transaction_id)
    ).scalar_one_or_none()

    if tx is None:
        return

    if tx.status != "pending":
        return  # already processed — idempotency guard

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

        existing_keys: set[str] = set(
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
                existing_keys.add(feature.key)
        db.flush()

        tx.status = "completed"
        tx.completed_at = datetime.now(timezone.utc)
        db.commit()

    except Exception as exc:
        db.rollback()
        try:
            tx = db.get(Transaction, transaction_id)
            if tx is not None:
                tx.status = "failed"
                tx.failure_reason = str(exc)[:255]
                db.commit()
        except Exception:
            pass  # best-effort status update; original exc is re-raised below
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
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 10)
    finally:
        db.close()
