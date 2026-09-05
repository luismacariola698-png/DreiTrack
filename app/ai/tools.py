from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.anomalies import (
    generate_inventory_anomalies,
)

from app.insights import (
    generate_inventory_insights,
)

from app.models import (
    Item,
    PurchaseOrder,
    PurchaseOrderLine,
)


# =========================================================
# READ-ONLY DREITRACK TOOLS
# =========================================================


# =========================================================
# INVENTORY ATTENTION
# =========================================================

def get_inventory_attention_items(
    db: Session,
) -> list[dict]:
    """
    Return inventory items that currently require
    attention according to DreiTrack.

    An item requires attention when:

    - the planning engine recommends a reorder, or
    - the anomaly detector has flagged the item

    This function is read-only.

    It does not modify stock, purchase orders,
    requests or any other database records.
    """

    # -----------------------------------------------------
    # RUN EXISTING DREITRACK ENGINES
    # -----------------------------------------------------

    insights = generate_inventory_insights(
        db
    )

    anomalies = generate_inventory_anomalies(
        db
    )


    # -----------------------------------------------------
    # GROUP ANOMALIES BY ITEM
    # -----------------------------------------------------

    anomalies_by_item = defaultdict(
        list
    )


    for anomaly in anomalies:

        item_id = anomaly.get(
            "item_id"
        )


        if item_id is None:
            continue


        anomalies_by_item[
            item_id
        ].append(
            anomaly
        )


    # -----------------------------------------------------
    # BUILD ATTENTION LIST
    # -----------------------------------------------------

    attention_items = []


    for insight in insights:

        item_id = insight.get(
            "item_id"
        )


        item_anomalies = (
            anomalies_by_item.get(
                item_id,
                [],
            )
        )


        reorder_recommended = bool(
            insight.get(
                "reorder_recommended",
                False,
            )
        )


        has_anomalies = bool(
            item_anomalies
        )


        # If neither planning nor anomaly detection
        # requires attention, do not include the item.

        if (
            not reorder_recommended
            and
            not has_anomalies
        ):
            continue


        # -------------------------------------------------
        # FIND HIGHEST ANOMALY SEVERITY
        # -------------------------------------------------

        anomaly_severities = {
            anomaly.get(
                "severity"
            )
            for anomaly in item_anomalies
        }


        if "HIGH" in anomaly_severities:

            highest_severity = "HIGH"

        elif "MEDIUM" in anomaly_severities:

            highest_severity = "MEDIUM"

        elif "LOW" in anomaly_severities:

            highest_severity = "LOW"

        else:

            highest_severity = None


        # -------------------------------------------------
        # REASONS THIS ITEM REQUIRES ATTENTION
        # -------------------------------------------------

        attention_reasons = []


        if reorder_recommended:

            attention_reasons.append(
                (
                    "DreiTrack's planning engine "
                    "recommends a reorder."
                )
            )


        for anomaly in item_anomalies:

            title = anomaly.get(
                "title"
            )


            if title:

                attention_reasons.append(
                    (
                        "Anomaly detected: "
                        f"{title}."
                    )
                )


        # -------------------------------------------------
        # BUILD SAFE RESULT
        # -------------------------------------------------

        attention_items.append(
            {
                "item_id":
                    item_id,

                "sku":
                    insight.get(
                        "sku"
                    ),

                "name":
                    insight.get(
                        "name"
                    ),

                "available_stock":
                    insight.get(
                        "available_stock"
                    ),

                "minimum_stock":
                    insight.get(
                        "minimum_stock"
                    ),

                "on_order":
                    insight.get(
                        "on_order"
                    ),

                "projected_stock":
                    insight.get(
                        "projected_stock"
                    ),

                "suggested_reorder_quantity":
                    insight.get(
                        "suggested_reorder_quantity"
                    ),

                "reorder_recommended":
                    reorder_recommended,

                "highest_anomaly_severity":
                    highest_severity,

                "anomaly_count":
                    len(
                        item_anomalies
                    ),

                "attention_reasons":
                    attention_reasons,
            }
        )


    # -----------------------------------------------------
    # PRIORITY SORTING
    # -----------------------------------------------------

    severity_order = {
        "HIGH": 0,
        "MEDIUM": 1,
        "LOW": 2,
        None: 3,
    }


    attention_items.sort(
        key=lambda item: (
            severity_order.get(
                item[
                    "highest_anomaly_severity"
                ],
                99,
            ),

            0
            if item[
                "reorder_recommended"
            ]
            else 1,

            (
                item.get(
                    "name"
                )
                or ""
            ).lower(),
        )
    )


    return attention_items


# =========================================================
# OVERDUE PURCHASE ORDERS
# =========================================================

def get_overdue_purchase_orders(
    db: Session,
) -> list[dict]:
    """
    Return open purchase orders whose expected
    delivery date has already passed and which
    still contain outstanding quantities.

    This function is read-only.

    It does not receive stock, change order status,
    create purchase orders or modify inventory.
    """

    today = datetime.now().date()


    # -----------------------------------------------------
    # GET OPEN PURCHASE ORDERS
    # -----------------------------------------------------

    purchase_orders = db.scalars(
        select(PurchaseOrder)
        .where(
            PurchaseOrder.status.in_(
                (
                    "ORDERED",
                    "PARTIALLY RECEIVED",
                )
            )
        )
        .order_by(
            PurchaseOrder.expected_delivery_date
        )
    ).all()


    overdue_orders = []


    # -----------------------------------------------------
    # REVIEW EACH PURCHASE ORDER
    # -----------------------------------------------------

    for purchase_order in purchase_orders:

        expected_delivery = (
            purchase_order.expected_delivery_date
        )


        # An order without an expected delivery date
        # cannot be classified as overdue.

        if expected_delivery is None:
            continue


        expected_date = (
            expected_delivery.date()
        )


        if expected_date >= today:
            continue


        days_overdue = (
            today - expected_date
        ).days


        # -------------------------------------------------
        # GET ORDER LINES
        # -------------------------------------------------

        order_lines = db.scalars(
            select(PurchaseOrderLine)
            .where(
                PurchaseOrderLine.purchase_order_id
                == purchase_order.id
            )
            .order_by(
                PurchaseOrderLine.id
            )
        ).all()


        line_results = []

        total_outstanding_units = 0


        for line in order_lines:

            quantity_outstanding = (
                line.quantity_ordered
                - line.quantity_received
            )


            # Fully received lines are not part of
            # the overdue quantity.

            if quantity_outstanding <= 0:
                continue


            item = db.get(
                Item,
                line.item_id,
            )


            total_outstanding_units += (
                quantity_outstanding
            )


            line_results.append(
                {
                    "line_id":
                        line.id,

                    "item_id":
                        line.item_id,

                    "sku": (
                        item.sku
                        if item
                        else None
                    ),

                    "item_name": (
                        item.name
                        if item
                        else "Unknown Item"
                    ),

                    "quantity_ordered":
                        line.quantity_ordered,

                    "quantity_received":
                        line.quantity_received,

                    "quantity_outstanding":
                        quantity_outstanding,
                }
            )


        # If every line was already received,
        # there is nothing overdue operationally.

        if not line_results:
            continue


        # -------------------------------------------------
        # BUILD VERIFIED PO RESULT
        # -------------------------------------------------

        overdue_orders.append(
            {
                "purchase_order_id":
                    purchase_order.id,

                "po_number":
                    purchase_order.po_number,

                "supplier":
                    purchase_order.supplier,

                "status":
                    purchase_order.status,

                "order_date":
                    purchase_order.order_date,

                "expected_delivery_date":
                    expected_delivery,

                "days_overdue":
                    days_overdue,

                "total_outstanding_units":
                    total_outstanding_units,

                "lines":
                    line_results,
            }
        )


    # -----------------------------------------------------
    # PRIORITY SORTING
    # -----------------------------------------------------

    # The most overdue orders appear first.

    overdue_orders.sort(
        key=lambda order: (
            -order[
                "days_overdue"
            ],

            (
                order.get(
                    "po_number"
                )
                or ""
            ).lower(),
        )
    )


    return overdue_orders