from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.errors import api_error
from app.models import Feature, FeatureRun, User, UserEntitlement
from app.schemas.feature_run import FeatureRunRequest, FeatureRunResponse
from app.services.credit_service import InsufficientCreditsError, spend_credits

_MOCK_RESULTS: dict[str, dict] = {
    "image-generation": {"url": "https://mock.creditos.dev/image/placeholder.png"},
    "auto-posting": {"scheduled_at": "mock", "status": "queued"},
    "bulk-export": {"file_url": "https://mock.creditos.dev/export/placeholder.zip", "count": 0},
    "audience-insights": {"score": 0.85, "segments": []},
}


def run_feature(
    db: Session,
    user: User,
    feature_key: str,
    payload: FeatureRunRequest,
) -> FeatureRunResponse:
    feature = db.get(Feature, feature_key)
    if feature is None:
        raise api_error(404, "FEATURE_NOT_FOUND", f"Feature '{feature_key}' does not exist.")

    entitlement = db.get(UserEntitlement, {"user_id": user.id, "feature_key": feature_key})
    if entitlement is None:
        raise api_error(403, "FEATURE_LOCKED", "Feature is not unlocked for this account.")

    # Pre-generate the run ID so it can be used as the ledger reference before db.add(run).
    # This avoids flushing the FeatureRun before spend_credits — if the spend fails, no row
    # was ever added to the session and no rollback is needed.
    run_id = uuid.uuid4()
    try:
        wallet = spend_credits(
            db,
            user.id,
            amount=feature.cost,
            reason="feature_run",
            description=f"Ran feature '{feature.name}'",
            reference_type="feature_run",
            reference_id=str(run_id),
        )
    except InsufficientCreditsError:
        raise api_error(402, "INSUFFICIENT_CREDITS", "Insufficient credits to run this feature.")

    run = FeatureRun(
        id=run_id,
        user_id=user.id,
        feature_key=feature_key,
        credits_spent=feature.cost,
        input_payload=payload.input_payload,
        result_payload=_MOCK_RESULTS.get(feature_key, {"result": "ok"}),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    db.refresh(wallet)

    return FeatureRunResponse(
        id=run.id,
        feature_key=run.feature_key,
        credits_spent=run.credits_spent,
        result_payload=run.result_payload,
        balance=wallet.balance,
        created_at=run.created_at,
    )
