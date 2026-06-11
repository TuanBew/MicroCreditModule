from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.models import Feature, User
from app.schemas.catalog import FeatureRead
from app.services.catalog_service import list_features


router = APIRouter(tags=["features"])


@router.get("", response_model=list[FeatureRead])
def index(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> list[Feature]:
    return list_features(db)
