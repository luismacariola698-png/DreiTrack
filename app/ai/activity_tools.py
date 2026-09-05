from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Asset, Item, Site, StorageLocation, Transaction


# =========================================================
# RECENT INVENTORY ACTIVITY
# =========================================================


def get_recent_inventory_movements(
    db: Session,
    days: int = 7,
    limit: int = 50,
) -> list[dict]:
    """Return recent organization-scoped inventory movements.

    Tenant isolation is applied automatically by the scoped SQLAlchemy session.
    This function is read-only.
    """

    days = max(1, min(days, 90))
    limit = max(1, min(limit, 200))
    start_date = datetime.now() - timedelta(days=days)

    transactions = db.scalars(
        select(Transaction)
        .where(Transaction.movement_date >= start_date)
        .order_by(Transaction.movement_date.desc())
        .limit(limit)
    ).all()

    results = []

    for transaction in transactions:
        item = db.get(Item, transaction.item_id)
        asset = db.get(Asset, transaction.asset_id) if transaction.asset_id else None
        location = (
            db.get(StorageLocation, transaction.storage_location_id)
            if transaction.storage_location_id
            else None
        )
        site = db.get(Site, location.site_id) if location else None

        results.append(
            {
                "transaction_id": transaction.id,
                "movement_date": transaction.movement_date,
                "transaction_type": transaction.transaction_type,
                "quantity": transaction.quantity,
                "reason": transaction.reason,
                "reference": transaction.reference,
                "actor": transaction.actor,
                "item_id": transaction.item_id,
                "sku": item.sku if item else None,
                "item_name": item.name if item else "Unknown Item",
                "asset_id": transaction.asset_id,
                "asset_code": asset.code if asset else None,
                "asset_name": asset.name if asset else None,
                "asset_type": asset.asset_type if asset else None,
                "storage_location_id": transaction.storage_location_id,
                "storage_location_code": location.code if location else None,
                "storage_location_name": location.name if location else None,
                "site_code": site.code if site else None,
                "site_name": site.name if site else None,
            }
        )

    return results
