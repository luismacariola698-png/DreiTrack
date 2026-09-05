from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AssetType, Organization, Site, StorageLocation


DEFAULT_ASSET_TYPES = (
    "Equipment",
    "Machine",
    "Robot",
    "Vehicle",
    "3D Printer",
    "Production Line",
    "Test Rig",
    "Laboratory Equipment",
    "Electrical Equipment",
    "Tooling",
)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "organization"


def unique_organization_slug(db: Session, name: str) -> str:
    base = slugify(name)
    candidate = base
    counter = 2

    while db.scalar(select(Organization).where(Organization.slug == candidate)):
        candidate = f"{base}-{counter}"
        counter += 1

    return candidate


def current_organization_id(db: Session) -> int:
    organization_id = db.info.get("organization_id")
    if organization_id is None:
        raise ValueError("No organization is active for this database session.")
    return int(organization_id)


def create_organization_defaults(
    db: Session,
    organization: Organization,
) -> tuple[Site, StorageLocation]:
    site = Site(
        organization_id=organization.id,
        code="MAIN",
        name="Main Site",
        is_active=True,
    )
    db.add(site)
    db.flush()

    location = StorageLocation(
        organization_id=organization.id,
        site_id=site.id,
        code="MAIN-STORES",
        name="Main Stores",
        location_type="STORAGE",
        is_active=True,
    )
    db.add(location)

    for name in DEFAULT_ASSET_TYPES:
        db.add(
            AssetType(
                organization_id=organization.id,
                name=name,
                is_active=True,
            )
        )

    db.flush()
    return site, location


def location_label(db: Session, location_id: int | None) -> str:
    if location_id is None:
        return "-"

    location = db.get(StorageLocation, location_id)
    if location is None:
        return "-"

    site = db.get(Site, location.site_id)
    if site is not None:
        return f"{site.code} / {location.code} - {location.name}"

    return f"{location.code} - {location.name}"
