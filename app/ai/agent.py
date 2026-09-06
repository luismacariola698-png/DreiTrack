from sqlalchemy.orm import Session

from app.ai.context import build_item_context
from app.ai.local_model import chat_with_local_model
from app.ai.tools import get_inventory_attention_items, get_overdue_purchase_orders
from app.anomalies import detect_item_anomalies
from app.insights import generate_item_insight
from app.models import Item, Organization

MAX_QUESTION_LENGTH = 1000
SEPARATOR = "\n\n------------------------------\n\n"


class DreiAgentError(Exception):
    """Base error for Drei agent problems."""


class DreiAgentInputError(DreiAgentError):
    """Raised when the user's question is invalid."""


class DreiAgentItemNotFoundError(DreiAgentError):
    """Raised when the selected inventory item does not exist."""


def validate_question(question: str) -> str:
    question = question.strip()
    if not question:
        raise DreiAgentInputError("A question is required.")
    if len(question) > MAX_QUESTION_LENGTH:
        raise DreiAgentInputError(f"Questions must be {MAX_QUESTION_LENGTH} characters or fewer.")
    return question


def organization_scope_text(db: Session) -> str:
    organization_id = db.info.get("organization_id")
    organization = db.get(Organization, int(organization_id)) if organization_id is not None else None
    return f"Organization scope: {organization.name}." if organization else "Organization scope: not available."


def _ask(db: Session, question: str, verified_context: str, instructions: str) -> str:
    question = validate_question(question)
    content = (
        f"{organization_scope_text(db)}\n\n"
        f"{verified_context}\n\n"
        f"{instructions}\n\n"
        "USER QUESTION\n"
        f"{question}"
    )
    return chat_with_local_model([{"role": "user", "content": content}])


def get_item_intelligence(*, db: Session, item_id: int) -> dict:
    item = db.get(Item, item_id)
    if item is None:
        raise DreiAgentItemNotFoundError("The selected inventory item does not exist.")
    insight = generate_item_insight(db=db, item=item)
    anomalies = detect_item_anomalies(db=db, item=item)
    return {
        "item": item,
        "insight": insight,
        "anomalies": anomalies,
        "verified_context": build_item_context(insight=insight, anomalies=anomalies),
    }


def ask_drei_about_item(*, db: Session, item_id: int, question: str) -> dict:
    intelligence = get_item_intelligence(db=db, item_id=item_id)
    answer = _ask(
        db,
        question,
        "DreiTrack has supplied the following current verified inventory data for this organization.\n\n"
        + intelligence["verified_context"],
        "Use only the verified DreiTrack data above when answering the question.\n\n"
        "If the available information is not enough to determine something, say so.",
    )
    return {
        "answer": answer,
        "item": intelligence["item"],
        "insight": intelligence["insight"],
        "anomalies": intelligence["anomalies"],
    }


def build_attention_context(attention_items: list[dict]) -> str:
    if not attention_items:
        return "DreiTrack currently has no inventory items requiring attention."
    return SEPARATOR.join(
        "\n".join(
            (
                f"ITEM: {item['name']}",
                f"SKU: {item['sku']}",
                f"Available stock: {item['available_stock']}",
                f"Minimum stock: {item['minimum_stock']}",
                f"Stock on order: {item['on_order']}",
                f"Projected stock: {item['projected_stock']}",
                f"Suggested reorder quantity: {item['suggested_reorder_quantity']}",
                f"Reorder recommended: {item['reorder_recommended']}",
                f"Highest anomaly severity: {item['highest_anomaly_severity']}",
                f"Anomaly count: {item['anomaly_count']}",
                f"Reasons: {'; '.join(item['attention_reasons'])}",
            )
        )
        for item in attention_items
    )


def ask_drei_about_attention(*, db: Session, question: str) -> dict:
    items = get_inventory_attention_items(db)
    context = build_attention_context(items)
    answer = _ask(
        db,
        question,
        "DreiTrack has supplied the following verified list of inventory items that currently require attention for this organization.\n\n"
        + context,
        "Use only this verified information.\n\n"
        "Do not invent additional inventory problems or quantities.\n\n"
        "Prioritise the most important issues first and keep the answer practical.",
    )
    return {"answer": answer, "attention_items": items}


def build_overdue_po_context(overdue_orders: list[dict]) -> str:
    if not overdue_orders:
        return "DreiTrack currently has no overdue purchase orders with outstanding stock."

    blocks = []
    for order in overdue_orders:
        lines = "\n".join(
            f"- {line['item_name']} (SKU: {line['sku']}): {line['quantity_outstanding']} unit(s) outstanding "
            f"from {line['quantity_ordered']} ordered."
            for line in order["lines"]
        )
        blocks.append(
            "\n".join(
                (
                    f"PURCHASE ORDER: {order['po_number']}",
                    f"Supplier: {order['supplier']}",
                    f"Status: {order['status']}",
                    f"Expected delivery: {order['expected_delivery_date']}",
                    f"Days overdue: {order['days_overdue']}",
                    f"Total outstanding units: {order['total_outstanding_units']}",
                    "Outstanding items:",
                    lines,
                )
            )
        )
    return SEPARATOR.join(blocks)


def ask_drei_about_overdue_orders(*, db: Session, question: str) -> dict:
    orders = get_overdue_purchase_orders(db)
    context = build_overdue_po_context(orders)
    answer = _ask(
        db,
        question,
        "DreiTrack has supplied the following verified purchase-order information for this organization.\n\n" + context,
        "Use only the verified DreiTrack information above.\n\n"
        "Do not invent purchase orders, delivery dates, suppliers, quantities or reasons for delays.\n\n"
        "If there are no overdue orders, state that clearly.\n\n"
        "If orders are overdue, explain the most urgent ones first and identify what remains outstanding.",
    )
    return {"answer": answer, "overdue_orders": orders}
