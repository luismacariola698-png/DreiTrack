from sqlalchemy.orm import Session

from app.ai.context import (
    build_item_context,
)

from app.ai.local_model import (
    chat_with_local_model,
)

from app.ai.tools import (
    get_inventory_attention_items,
    get_overdue_purchase_orders,
)

from app.anomalies import (
    detect_item_anomalies,
)

from app.insights import (
    generate_item_insight,
)

from app.models import Item, Organization


# =========================================================
# SETTINGS
# =========================================================

MAX_QUESTION_LENGTH = 1000


# =========================================================
# AGENT ERRORS
# =========================================================

class DreiAgentError(Exception):
    """
    Base error for Drei agent problems.
    """


class DreiAgentInputError(
    DreiAgentError
):
    """
    Raised when the user's question is invalid.
    """


class DreiAgentItemNotFoundError(
    DreiAgentError
):
    """
    Raised when the selected inventory item
    cannot be found.
    """


# =========================================================
# QUESTION VALIDATION
# =========================================================

def validate_question(
    question: str,
) -> str:
    """
    Clean and validate a user's question.
    """

    clean_question = question.strip()


    if not clean_question:

        raise DreiAgentInputError(
            "A question is required."
        )


    if (
        len(clean_question)
        > MAX_QUESTION_LENGTH
    ):

        raise DreiAgentInputError(
            (
                "Questions must be "
                f"{MAX_QUESTION_LENGTH} "
                "characters or fewer."
            )
        )


    return clean_question




def organization_scope_text(db: Session) -> str:
    organization_id = db.info.get("organization_id")
    if organization_id is None:
        return "Organization scope: not available."

    organization = db.get(Organization, int(organization_id))
    if organization is None:
        return "Organization scope: not available."

    return f"Organization scope: {organization.name}."


# =========================================================
# GET VERIFIED ITEM INTELLIGENCE
# =========================================================

def get_item_intelligence(
    *,
    db: Session,
    item_id: int,
) -> dict:
    """
    Retrieve verified DreiTrack information
    for one inventory item.

    This function does not call the AI.
    """

    item = db.get(
        Item,
        item_id,
    )


    if item is None:

        raise DreiAgentItemNotFoundError(
            "The selected inventory item does not exist."
        )


    insight = generate_item_insight(
        db=db,
        item=item,
    )


    anomalies = detect_item_anomalies(
        db=db,
        item=item,
    )


    verified_context = build_item_context(
        insight=insight,
        anomalies=anomalies,
    )


    return {
        "item":
            item,

        "insight":
            insight,

        "anomalies":
            anomalies,

        "verified_context":
            verified_context,
    }


# =========================================================
# ASK DREI ABOUT ONE ITEM
# =========================================================

def ask_drei_about_item(
    *,
    db: Session,
    item_id: int,
    question: str,
) -> dict:
    """
    Ask Drei a question about one inventory item.
    """

    clean_question = validate_question(
        question
    )


    intelligence = get_item_intelligence(
        db=db,
        item_id=item_id,
    )


    verified_context = intelligence[
        "verified_context"
    ]


    messages = [
        {
            "role":
                "user",

            "content":
                (
                    f"{organization_scope_text(db)}\n\n"
                    "DreiTrack has supplied the following "
                    "current verified inventory data for this organization.\n\n"

                    f"{verified_context}\n\n"

                    "Use only the verified DreiTrack data "
                    "above when answering the question.\n\n"

                    "If the available information is not "
                    "enough to determine something, say so.\n\n"

                    "USER QUESTION\n"
                    f"{clean_question}"
                ),
        }
    ]


    answer = chat_with_local_model(
        messages
    )


    return {
        "answer":
            answer,

        "item":
            intelligence["item"],

        "insight":
            intelligence["insight"],

        "anomalies":
            intelligence["anomalies"],
    }


# =========================================================
# BUILD ATTENTION CONTEXT
# =========================================================

def build_attention_context(
    attention_items: list[dict],
) -> str:
    """
    Convert DreiTrack attention items into
    verified plain-text context for Drei.
    """

    if not attention_items:

        return (
            "DreiTrack currently has no inventory "
            "items requiring attention."
        )


    lines = []


    for item in attention_items:

        lines.append(
            (
                f"ITEM: {item['name']}\n"
                f"SKU: {item['sku']}\n"
                f"Available stock: "
                f"{item['available_stock']}\n"
                f"Minimum stock: "
                f"{item['minimum_stock']}\n"
                f"Stock on order: "
                f"{item['on_order']}\n"
                f"Projected stock: "
                f"{item['projected_stock']}\n"
                f"Suggested reorder quantity: "
                f"{item['suggested_reorder_quantity']}\n"
                f"Reorder recommended: "
                f"{item['reorder_recommended']}\n"
                f"Highest anomaly severity: "
                f"{item['highest_anomaly_severity']}\n"
                f"Anomaly count: "
                f"{item['anomaly_count']}\n"
                f"Reasons: "
                f"{'; '.join(item['attention_reasons'])}"
            )
        )


    return (
        "\n\n"
        "------------------------------\n\n"
    ).join(
        lines
    )


# =========================================================
# ASK DREI WHAT NEEDS ATTENTION
# =========================================================

def ask_drei_about_attention(
    *,
    db: Session,
    question: str,
) -> dict:
    """
    Ask Drei about inventory items that currently
    require attention.

    DreiTrack decides which items require attention.
    Drei only explains the verified findings.
    """

    clean_question = validate_question(
        question
    )


    attention_items = (
        get_inventory_attention_items(
            db
        )
    )


    attention_context = (
        build_attention_context(
            attention_items
        )
    )


    messages = [
        {
            "role":
                "user",

            "content":
                (
                    f"{organization_scope_text(db)}\n\n"
                    "DreiTrack has supplied the following "
                    "verified list of inventory items that "
                    "currently require attention for this organization.\n\n"

                    f"{attention_context}\n\n"

                    "Use only this verified information.\n\n"

                    "Do not invent additional inventory "
                    "problems or quantities.\n\n"

                    "Prioritise the most important issues "
                    "first and keep the answer practical.\n\n"

                    "USER QUESTION\n"
                    f"{clean_question}"
                ),
        }
    ]


    answer = chat_with_local_model(
        messages
    )


    return {
        "answer":
            answer,

        "attention_items":
            attention_items,
    }


# =========================================================
# BUILD OVERDUE PO CONTEXT
# =========================================================

def build_overdue_po_context(
    overdue_orders: list[dict],
) -> str:
    """
    Convert verified overdue purchase-order data
    into bounded plain text for Drei.
    """

    if not overdue_orders:

        return (
            "DreiTrack currently has no overdue "
            "purchase orders with outstanding stock."
        )


    order_blocks = []


    for order in overdue_orders:

        line_details = []


        for line in order[
            "lines"
        ]:

            line_details.append(
                (
                    f"- {line['item_name']} "
                    f"(SKU: {line['sku']}): "
                    f"{line['quantity_outstanding']} "
                    "unit(s) outstanding "
                    f"from {line['quantity_ordered']} "
                    "ordered."
                )
            )


        order_blocks.append(
            (
                f"PURCHASE ORDER: "
                f"{order['po_number']}\n"

                f"Supplier: "
                f"{order['supplier']}\n"

                f"Status: "
                f"{order['status']}\n"

                f"Expected delivery: "
                f"{order['expected_delivery_date']}\n"

                f"Days overdue: "
                f"{order['days_overdue']}\n"

                f"Total outstanding units: "
                f"{order['total_outstanding_units']}\n"

                "Outstanding items:\n"
                f"{chr(10).join(line_details)}"
            )
        )


    return (
        "\n\n"
        "------------------------------\n\n"
    ).join(
        order_blocks
    )


# =========================================================
# ASK DREI ABOUT OVERDUE PURCHASE ORDERS
# =========================================================

def ask_drei_about_overdue_orders(
    *,
    db: Session,
    question: str,
) -> dict:
    """
    Ask Drei about overdue purchase orders.

    DreiTrack determines which purchase orders
    are actually overdue.

    Drei only explains the verified findings.
    """

    clean_question = validate_question(
        question
    )


    overdue_orders = (
        get_overdue_purchase_orders(
            db
        )
    )


    overdue_context = (
        build_overdue_po_context(
            overdue_orders
        )
    )


    messages = [
        {
            "role":
                "user",

            "content":
                (
                    f"{organization_scope_text(db)}\n\n"
                    "DreiTrack has supplied the following "
                    "verified purchase-order information for this organization.\n\n"

                    f"{overdue_context}\n\n"

                    "Use only the verified DreiTrack "
                    "information above.\n\n"

                    "Do not invent purchase orders, "
                    "delivery dates, suppliers, quantities "
                    "or reasons for delays.\n\n"

                    "If there are no overdue orders, "
                    "state that clearly.\n\n"

                    "If orders are overdue, explain the "
                    "most urgent ones first and identify "
                    "what remains outstanding.\n\n"

                    "USER QUESTION\n"
                    f"{clean_question}"
                ),
        }
    ]


    answer = chat_with_local_model(
        messages
    )


    return {
        "answer":
            answer,

        "overdue_orders":
            overdue_orders,
    }