"""One-time migration to DreiTrack's organization-scoped schema.

Run from the project root:
    python migrate_multicompany.py

The migration:
- creates Organizations, Sites, Storage Locations, Users and Asset Types
- scopes existing operational data to a default organization
- adds location-aware movement/request fields
- rebuilds uniqueness rules so SKU/asset code/PO number can repeat in different organizations
- creates a timestamped backup before replacing the database

If the organizations table already exists, the script exits without changing data.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import shutil
import sqlite3

from sqlalchemy import create_engine

from app.database import Base
from app.models import *  # noqa: F401,F403 - load all table metadata
from app.security import hash_password


DB_PATH = Path("dreitrack.db")
DEFAULT_ADMIN_EMAIL = "admin@demo.dreitrack"
DEFAULT_ADMIN_PASSWORD = "ChangeMe123!"


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        is not None
    )


def clean_code(value: str, fallback: str, used: set[str]) -> str:
    base = re.sub(r"[^A-Z0-9]+", "-", (value or "").upper()).strip("-")
    base = base[:70] or fallback
    candidate = base
    counter = 2
    while candidate in used:
        candidate = f"{base}-{counter}"
        counter += 1
    used.add(candidate)
    return candidate


def row_dicts(connection: sqlite3.Connection, table: str) -> list[dict]:
    if not table_exists(connection, table):
        return []
    return [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY id")]


def migrate() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH.resolve()}")

    source = sqlite3.connect(DB_PATH)
    source.row_factory = sqlite3.Row

    try:
        if table_exists(source, "organizations"):
            print("Organization-scoped schema already present. Nothing to migrate.")
            return

        required = {
            "items",
            "assets",
            "transactions",
            "asset_components",
            "stock_requests",
            "purchase_orders",
            "purchase_order_lines",
        }
        missing = sorted(table for table in required if not table_exists(source, table))
        if missing:
            raise SystemExit(f"Cannot migrate: missing tables {missing}")

        data = {table: row_dicts(source, table) for table in required}
    finally:
        source.close()

    backup = DB_PATH.with_name(
        f"{DB_PATH.stem}_before_multicompany_{datetime.now():%Y%m%d_%H%M%S}.db"
    )
    shutil.copy2(DB_PATH, backup)
    print(f"Backup created: {backup.name}")

    temp_path = DB_PATH.with_name(f"{DB_PATH.stem}_multicompany_build.db")
    if temp_path.exists():
        temp_path.unlink()

    temp_engine = create_engine(f"sqlite:///{temp_path}")
    Base.metadata.create_all(bind=temp_engine)
    temp_engine.dispose()

    target = sqlite3.connect(temp_path)
    target.row_factory = sqlite3.Row
    target.execute("PRAGMA foreign_keys = ON")

    try:
        target.execute("BEGIN")

        now = datetime.now().isoformat(sep=" ")
        target.execute(
            """
            INSERT INTO organizations (id, name, slug, is_active, created_at)
            VALUES (1, ?, ?, 1, ?)
            """,
            ("Demo Organization", "demo-organization", now),
        )

        target.execute(
            """
            INSERT INTO sites (id, organization_id, code, name, address, is_active, created_at)
            VALUES (1, 1, 'MAIN', 'Main Site', NULL, 1, ?)
            """,
            (now,),
        )

        # Build storage locations from the existing item location labels.
        used_location_codes: set[str] = set()
        location_map: dict[str, int] = {}
        next_location_id = 1

        distinct_locations: list[str] = []
        for item in data["items"]:
            label = (item.get("location") or "Main Stores").strip() or "Main Stores"
            if label not in distinct_locations:
                distinct_locations.append(label)

        if not distinct_locations:
            distinct_locations = ["Main Stores"]

        for label in distinct_locations:
            code = clean_code(label, f"LOC-{next_location_id:03d}", used_location_codes)
            target.execute(
                """
                INSERT INTO storage_locations
                    (id, organization_id, site_id, code, name, location_type, is_active, created_at)
                VALUES (?, 1, 1, ?, ?, 'STORAGE', 1, ?)
                """,
                (next_location_id, code, label, now),
            )
            location_map[label] = next_location_id
            next_location_id += 1

        # Asset types are organization-managed, seeded from existing values plus useful defaults.
        existing_asset_types = []
        for asset in data["assets"]:
            value = (asset.get("asset_type") or "Equipment").strip() or "Equipment"
            if value not in existing_asset_types:
                existing_asset_types.append(value)

        defaults = [
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
        ]
        for value in defaults:
            if value not in existing_asset_types:
                existing_asset_types.append(value)

        asset_type_map: dict[str, int] = {}
        for asset_type_id, name in enumerate(existing_asset_types, start=1):
            target.execute(
                """
                INSERT INTO asset_types
                    (id, organization_id, name, description, is_active, created_at)
                VALUES (?, 1, ?, NULL, 1, ?)
                """,
                (asset_type_id, name, now),
            )
            asset_type_map[name] = asset_type_id

        target.execute(
            """
            INSERT INTO app_users
                (id, organization_id, email, display_name, password_hash, role, is_active, created_at)
            VALUES (1, 1, ?, 'Demo Administrator', ?, 'ADMIN', 1, ?)
            """,
            (
                DEFAULT_ADMIN_EMAIL,
                hash_password(DEFAULT_ADMIN_PASSWORD),
                now,
            ),
        )

        # Items
        item_location_map: dict[int, int] = {}
        for row in data["items"]:
            label = (row.get("location") or "Main Stores").strip() or "Main Stores"
            location_id = location_map[label]
            item_location_map[row["id"]] = location_id
            target.execute(
                """
                INSERT INTO items
                    (id, organization_id, sku, name, category,
                     default_storage_location_id, location, min_stock, supplier,
                     unit_cost, lead_time_days, lead_time_mode, created_at)
                VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"], row["sku"], row["name"], row["category"],
                    location_id, label, row["min_stock"], row.get("supplier"),
                    row.get("unit_cost"), row.get("lead_time_days", 14),
                    row.get("lead_time_mode") or "AUTOMATIC", row["created_at"],
                ),
            )

        # Assets
        for row in data["assets"]:
            asset_type_name = (row.get("asset_type") or "Equipment").strip() or "Equipment"
            target.execute(
                """
                INSERT INTO assets
                    (id, organization_id, code, name, asset_type_id, asset_type,
                     site_id, serial_number, location, status, notes, created_at)
                VALUES (?, 1, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"], row["code"], row.get("name"),
                    asset_type_map[asset_type_name], asset_type_name,
                    row.get("serial_number"), row.get("location"),
                    row.get("status") or "ACTIVE", row.get("notes"), row["created_at"],
                ),
            )

        # Transactions
        for row in data["transactions"]:
            location_id = item_location_map.get(row["item_id"])
            target.execute(
                """
                INSERT INTO transactions
                    (id, organization_id, item_id, asset_id, storage_location_id,
                     transaction_type, quantity, movement_date, reason, actor,
                     reference, notes, created_at)
                VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"], row["item_id"], row.get("asset_id"), location_id,
                    row["transaction_type"], row["quantity"], row["movement_date"],
                    row["reason"], row.get("actor"), row.get("reference"),
                    row.get("notes"), row["created_at"],
                ),
            )

        # Asset components
        for row in data["asset_components"]:
            target.execute(
                """
                INSERT INTO asset_components
                    (id, organization_id, asset_id, item_id,
                     quantity_required, quantity_assigned, created_at)
                VALUES (?, 1, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"], row["asset_id"], row["item_id"],
                    row["quantity_required"], row["quantity_assigned"], row["created_at"],
                ),
            )

        # Stock requests
        for row in data["stock_requests"]:
            location_id = item_location_map.get(row["item_id"])
            target.execute(
                """
                INSERT INTO stock_requests
                    (id, organization_id, item_id, asset_id, storage_location_id,
                     quantity, requested_by, reason, request_date, status,
                     approved_by, approved_at, collected_at, notes)
                VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"], row["item_id"], row.get("asset_id"), location_id,
                    row["quantity"], row["requested_by"], row["reason"],
                    row["request_date"], row["status"], row.get("approved_by"),
                    row.get("approved_at"), row.get("collected_at"), row.get("notes"),
                ),
            )

        # Purchase orders and lines
        for row in data["purchase_orders"]:
            target.execute(
                """
                INSERT INTO purchase_orders
                    (id, organization_id, po_number, supplier, order_date,
                     expected_delivery_date, status, created_by, notes, created_at)
                VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"], row["po_number"], row["supplier"], row["order_date"],
                    row.get("expected_delivery_date"), row["status"],
                    row.get("created_by"), row.get("notes"), row["created_at"],
                ),
            )

        for row in data["purchase_order_lines"]:
            target.execute(
                """
                INSERT INTO purchase_order_lines
                    (id, organization_id, purchase_order_id, item_id,
                     quantity_ordered, quantity_received, unit_cost)
                VALUES (?, 1, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"], row["purchase_order_id"], row["item_id"],
                    row["quantity_ordered"], row["quantity_received"], row.get("unit_cost"),
                ),
            )

        target.commit()
    except Exception:
        target.rollback()
        raise
    finally:
        target.close()

    DB_PATH.unlink()
    temp_path.replace(DB_PATH)

    print("Organization-scope migration complete.")
    print(f"Default organization: Demo Organization")
    print(f"Default administrator: {DEFAULT_ADMIN_EMAIL}")
    print(f"Temporary password: {DEFAULT_ADMIN_PASSWORD}")
    print("Change the password after signing in.")


if __name__ == "__main__":
    migrate()
