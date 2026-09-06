from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.anomalies import generate_inventory_anomalies
from app.insights import generate_inventory_insights
from app.models import Item, PurchaseOrder, PurchaseOrderLine

SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, None: 3}
OPEN_PO_STATUSES = ("ORDERED", "PARTIALLY RECEIVED")


def get_inventory_attention_items(db: Session) -> list[dict]:
    """Return read-only planning/anomaly findings that currently need attention."""
    anomalies_by_item: dict[int, list[dict]] = defaultdict(list)
    for anomaly in generate_inventory_anomalies(db):
        if (item_id := anomaly.get("item_id")) is not None:
            anomalies_by_item[item_id].append(anomaly)

    attention_items = []
    for insight in generate_inventory_insights(db):
        item_id = insight.get("item_id")
        item_anomalies = anomalies_by_item.get(item_id, [])
        reorder = bool(insight.get("reorder_recommended", False))
        if not reorder and not item_anomalies:
            continue

        severities = {a.get("severity") for a in item_anomalies}
        highest = next((s for s in ("HIGH", "MEDIUM", "LOW") if s in severities), None)
        reasons = ["DreiTrack's planning engine recommends a reorder."] if reorder else []
        reasons += [f"Anomaly detected: {a['title']}." for a in item_anomalies if a.get("title")]

        attention_items.append(
            {
                "item_id": item_id,
                "sku": insight.get("sku"),
                "name": insight.get("name"),
                "available_stock": insight.get("available_stock"),
                "minimum_stock": insight.get("minimum_stock"),
                "on_order": insight.get("on_order"),
                "projected_stock": insight.get("projected_stock"),
                "suggested_reorder_quantity": insight.get("suggested_reorder_quantity"),
                "reorder_recommended": reorder,
                "highest_anomaly_severity": highest,
                "anomaly_count": len(item_anomalies),
                "attention_reasons": reasons,
            }
        )

    attention_items.sort(
        key=lambda item: (
            SEVERITY_ORDER.get(item["highest_anomaly_severity"], 99),
            0 if item["reorder_recommended"] else 1,
            (item.get("name") or "").lower(),
        )
    )
    return attention_items


def get_overdue_purchase_orders(db: Session) -> list[dict]:
    """Return read-only open POs past expected delivery with outstanding quantities."""
    today = datetime.now().date()
    orders = db.scalars(
        select(PurchaseOrder)
        .where(PurchaseOrder.status.in_(OPEN_PO_STATUSES))
        .order_by(PurchaseOrder.expected_delivery_date)
    ).all()

    overdue = []
    for order in orders:
        expected = order.expected_delivery_date
        if expected is None or expected.date() >= today:
            continue

        lines = []
        for line in db.scalars(
            select(PurchaseOrderLine)
            .where(PurchaseOrderLine.purchase_order_id == order.id)
            .order_by(PurchaseOrderLine.id)
        ).all():
            outstanding = line.quantity_ordered - line.quantity_received
            if outstanding <= 0:
                continue
            item = db.get(Item, line.item_id)
            lines.append(
                {
                    "line_id": line.id,
                    "item_id": line.item_id,
                    "sku": item.sku if item else None,
                    "item_name": item.name if item else "Unknown Item",
                    "quantity_ordered": line.quantity_ordered,
                    "quantity_received": line.quantity_received,
                    "quantity_outstanding": outstanding,
                }
            )
        if not lines:
            continue

        overdue.append(
            {
                "purchase_order_id": order.id,
                "po_number": order.po_number,
                "supplier": order.supplier,
                "status": order.status,
                "order_date": order.order_date,
                "expected_delivery_date": expected,
                "days_overdue": (today - expected.date()).days,
                "total_outstanding_units": sum(line["quantity_outstanding"] for line in lines),
                "lines": lines,
            }
        )

    overdue.sort(key=lambda order: (-order["days_overdue"], (order.get("po_number") or "").lower()))
    return overdue
