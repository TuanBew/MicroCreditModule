from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.errors import api_error
from app.models import Feature, Package, User
from app.schemas.catalog import PackageCreate, PackageRead, PackageUpdate


def _package_read(package: Package) -> PackageRead:
    return PackageRead(
        id=package.id,
        slug=package.slug,
        name=package.name,
        badge=package.badge,
        description=package.description,
        price_cents=package.price_cents,
        credits=package.credits,
        active=package.active,
        features=[feature.key for feature in package.features],
    )


def _validate_positive(value: int | None, field_name: str) -> None:
    if value is not None and value <= 0:
        raise api_error(422, "INVALID_PACKAGE", f"{field_name} must be positive.")


def _validate_non_empty(value: str | None, field_name: str) -> None:
    if value is not None and not value.strip():
        raise api_error(422, "INVALID_PACKAGE", f"{field_name} is required.")


def _load_features(db: Session, feature_keys: list[str]) -> list[Feature]:
    if not feature_keys:
        raise api_error(422, "INVALID_PACKAGE", "At least one feature is required.")

    features = db.execute(select(Feature).where(Feature.key.in_(feature_keys))).scalars().all()
    features_by_key = {feature.key: feature for feature in features}
    unknown_keys = [feature_key for feature_key in feature_keys if feature_key not in features_by_key]
    if unknown_keys:
        raise api_error(
            422,
            "UNKNOWN_FEATURE",
            "One or more features do not exist.",
            {"feature_keys": unknown_keys},
        )
    return [features_by_key[feature_key] for feature_key in feature_keys]


def _get_package(db: Session, package_id: UUID) -> Package:
    package = db.execute(
        select(Package).options(selectinload(Package.features)).where(Package.id == package_id)
    ).scalar_one_or_none()
    if package is None:
        raise api_error(404, "PACKAGE_NOT_FOUND", "Package was not found.")
    return package


def list_features(db: Session) -> list[Feature]:
    return db.execute(select(Feature).order_by(Feature.key)).scalars().all()


def list_packages(db: Session, current_user: User) -> list[PackageRead]:
    statement = select(Package).options(selectinload(Package.features)).order_by(Package.slug)
    if current_user.role != "admin":
        statement = statement.where(Package.active.is_(True))
    packages = db.execute(statement).scalars().all()
    return [_package_read(package) for package in packages]


def create_package(db: Session, payload: PackageCreate) -> PackageRead:
    _validate_non_empty(payload.slug, "slug")
    _validate_non_empty(payload.name, "name")
    _validate_non_empty(payload.badge, "badge")
    _validate_non_empty(payload.description, "description")
    _validate_positive(payload.price_cents, "price_cents")
    _validate_positive(payload.credits, "credits")
    features = _load_features(db, payload.feature_keys)

    existing_package = db.execute(select(Package).where(Package.slug == payload.slug)).scalar_one_or_none()
    if existing_package is not None:
        raise api_error(409, "PACKAGE_SLUG_EXISTS", "Package slug already exists.")

    package = Package(
        slug=payload.slug,
        name=payload.name,
        badge=payload.badge,
        description=payload.description,
        price_cents=payload.price_cents,
        credits=payload.credits,
        active=payload.active,
    )
    package.features = features
    db.add(package)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise api_error(409, "PACKAGE_SLUG_EXISTS", "Package slug already exists.")
    db.refresh(package)
    return _package_read(package)


def update_package(db: Session, package_id: UUID, payload: PackageUpdate) -> PackageRead:
    package = _get_package(db, package_id)
    update_data = payload.model_dump(exclude_unset=True)

    _validate_non_empty(update_data.get("slug"), "slug")
    _validate_non_empty(update_data.get("name"), "name")
    _validate_non_empty(update_data.get("badge"), "badge")
    _validate_non_empty(update_data.get("description"), "description")
    _validate_positive(update_data.get("price_cents"), "price_cents")
    _validate_positive(update_data.get("credits"), "credits")

    if "slug" in update_data and update_data["slug"] != package.slug:
        existing_package = db.execute(
            select(Package).where(Package.slug == update_data["slug"])
        ).scalar_one_or_none()
        if existing_package is not None:
            raise api_error(409, "PACKAGE_SLUG_EXISTS", "Package slug already exists.")

    if "feature_keys" in update_data:
        package.features = _load_features(db, update_data.pop("feature_keys"))

    for field_name, value in update_data.items():
        setattr(package, field_name, value)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise api_error(409, "PACKAGE_SLUG_EXISTS", "Package slug already exists.")
    db.refresh(package)
    return _package_read(package)


def deactivate_package(db: Session, package_id: UUID) -> None:
    package = _get_package(db, package_id)
    package.active = False
    db.commit()
