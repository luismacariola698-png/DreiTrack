from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, Session, mapped_column, with_loader_criteria

from app.database import Base


# =========================================================
# COMPANY DATA BOUNDARY
# =========================================================


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Site(Base):
    __tablename__ = "sites"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_site_org_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class StorageLocation(Base):
    __tablename__ = "storage_locations"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "code",
            name="uq_storage_location_org_code",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    location_type: Mapped[str] = mapped_column(String(60), default="STORAGE")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class AppUser(Base):
    __tablename__ = "app_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(500), nullable=False)
    role: Mapped[str] = mapped_column(String(30), default="VIEWER", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class AssetType(Base):
    __tablename__ = "asset_types"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "name",
            name="uq_asset_type_org_name",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


# =========================================================
# OPERATIONAL DATA
# =========================================================


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("organization_id", "sku", name="uq_item_org_sku"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    sku: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    default_storage_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("storage_locations.id"), nullable=True
    )
    # Kept as a display/legacy-friendly field. New records derive this from
    # default_storage_location_id so old templates/integrations stay readable.
    location: Mapped[str] = mapped_column(String(120), nullable=False)
    min_stock: Mapped[int] = mapped_column(Integer, default=0)
    supplier: Mapped[str | None] = mapped_column(String(160), nullable=True)
    unit_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    lead_time_days: Mapped[int] = mapped_column(Integer, default=14)
    lead_time_mode: Mapped[str] = mapped_column(String(20), default="AUTOMATIC")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_asset_org_code"),
        UniqueConstraint(
            "organization_id",
            "serial_number",
            name="uq_asset_org_serial",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    asset_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset_types.id"), nullable=True
    )
    # Denormalized label retained for simple exports and AI context.
    asset_type: Mapped[str] = mapped_column(String(100), nullable=False)
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id"), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    location: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="ACTIVE")
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("assets.id"), nullable=True
    )
    storage_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("storage_locations.id"), nullable=True
    )
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    movement_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    reason: Mapped[str] = mapped_column(String(160), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class AssetComponent(Base):
    __tablename__ = "asset_components"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "asset_id",
            "item_id",
            name="uq_asset_component_org_asset_item",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    quantity_required: Mapped[int] = mapped_column(Integer, default=0)
    quantity_assigned: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class StockRequest(Base):
    __tablename__ = "stock_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("assets.id"), nullable=True
    )
    storage_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("storage_locations.id"), nullable=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_by: Mapped[str] = mapped_column(String(120), nullable=False)
    reason: Mapped[str] = mapped_column(String(160), nullable=False)
    request_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    approved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "po_number",
            name="uq_purchase_order_org_number",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    po_number: Mapped[str] = mapped_column(String(100), nullable=False)
    supplier: Mapped[str] = mapped_column(String(160), nullable=False)
    order_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    expected_delivery_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="ORDERED")
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id"), nullable=False
    )
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    quantity_ordered: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_received: Mapped[int] = mapped_column(Integer, default=0)
    unit_cost: Mapped[float | None] = mapped_column(Float, nullable=True)


TENANT_SCOPED_MODELS = (
    Site,
    StorageLocation,
    AppUser,
    AssetType,
    Item,
    Asset,
    Transaction,
    AssetComponent,
    StockRequest,
    PurchaseOrder,
    PurchaseOrderLine,
)


@event.listens_for(Session, "do_orm_execute")
def _scope_queries_to_organization(execute_state) -> None:
    """Automatically isolate tenant-scoped SELECT queries by organization.

    Sessions used by authenticated requests set ``session.info['organization_id']``.
    Migration/setup sessions do not set it and therefore remain unscoped.
    """

    if not execute_state.is_select:
        return

    if execute_state.execution_options.get("include_all_tenants"):
        return

    organization_id = execute_state.session.info.get("organization_id")
    if organization_id is None:
        return

    statement = execute_state.statement

    for model in TENANT_SCOPED_MODELS:
        statement = statement.options(
            with_loader_criteria(
                model,
                model.organization_id == organization_id,
                include_aliases=True,
            )
        )

    execute_state.statement = statement
