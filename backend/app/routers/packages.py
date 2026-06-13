import json
import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.cache import (
    PACKAGES_CACHE_KEY,
    cache_get,
    cache_set,
    invalidate_catalog_cache,
)
from app.core.config import get_settings
from app.core.csrf import verify_csrf
from app.core.deps import get_current_user, get_db, require_admin
from app.models import User
from app.schemas.catalog import PackageCreate, PackageRead, PackageUpdate
from app.services.catalog_service import (
    create_package,
    deactivate_package,
    list_packages,
    update_package,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["packages"])


@router.get("", response_model=list[PackageRead])
def index(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[PackageRead]:
    # Only serve cached results for non-admin users (admins see inactive too)
    if current_user.role != "admin":
        cached = cache_get(PACKAGES_CACHE_KEY)
        if cached is not None:
            return [PackageRead(**item) for item in json.loads(cached)]

    result = list_packages(db, current_user)

    if current_user.role != "admin":
        serialized = json.dumps(
            [r.model_dump(mode="json") for r in result]
        ).encode()  # encode() required: redis client uses decode_responses=False
        cache_set(PACKAGES_CACHE_KEY, serialized, get_settings().catalog_cache_ttl_seconds)

    return result


@router.post("", response_model=PackageRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(verify_csrf)])
def create(
    payload: PackageCreate,
    db: Annotated[Session, Depends(get_db)],
    _admin: Annotated[User, Depends(require_admin)],
) -> PackageRead:
    result = create_package(db, payload)
    invalidate_catalog_cache()
    return result


@router.patch("/{package_id}", response_model=PackageRead, dependencies=[Depends(verify_csrf)])
def patch(
    package_id: UUID,
    payload: PackageUpdate,
    db: Annotated[Session, Depends(get_db)],
    _admin: Annotated[User, Depends(require_admin)],
) -> PackageRead:
    result = update_package(db, package_id, payload)
    invalidate_catalog_cache()
    return result


@router.delete("/{package_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(verify_csrf)])
def delete(
    package_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    _admin: Annotated[User, Depends(require_admin)],
) -> Response:
    deactivate_package(db, package_id)
    invalidate_catalog_cache()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
