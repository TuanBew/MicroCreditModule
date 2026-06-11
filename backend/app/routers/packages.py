from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, require_admin
from app.models import User
from app.schemas.catalog import PackageCreate, PackageRead, PackageUpdate
from app.services.catalog_service import (
    create_package,
    deactivate_package,
    list_packages,
    update_package,
)


router = APIRouter(tags=["packages"])


@router.get("", response_model=list[PackageRead])
def index(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[PackageRead]:
    return list_packages(db, current_user)


@router.post("", response_model=PackageRead, status_code=status.HTTP_201_CREATED)
def create(
    payload: PackageCreate,
    db: Annotated[Session, Depends(get_db)],
    _admin: Annotated[User, Depends(require_admin)],
) -> PackageRead:
    return create_package(db, payload)


@router.patch("/{package_id}", response_model=PackageRead)
def patch(
    package_id: UUID,
    payload: PackageUpdate,
    db: Annotated[Session, Depends(get_db)],
    _admin: Annotated[User, Depends(require_admin)],
) -> PackageRead:
    return update_package(db, package_id, payload)


@router.delete("/{package_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    package_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    _admin: Annotated[User, Depends(require_admin)],
) -> Response:
    deactivate_package(db, package_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
