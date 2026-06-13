from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.csrf import verify_csrf
from app.core.deps import get_db, require_buyer
from app.models import User
from app.schemas.feature_run import FeatureRunRequest, FeatureRunResponse
from app.services import feature_service

router = APIRouter(tags=["feature-runs"])


@router.post("/{feature_key}/run", response_model=FeatureRunResponse, status_code=201, dependencies=[Depends(verify_csrf)])
def run(
    feature_key: str,
    body: FeatureRunRequest,
    db: Annotated[Session, Depends(get_db)],
    buyer: Annotated[User, Depends(require_buyer)],
) -> FeatureRunResponse:
    return feature_service.run_feature(db, buyer, feature_key, body)
