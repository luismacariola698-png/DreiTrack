from collections import defaultdict
from datetime import datetime

from sqlalchemy.orm import Session

from app.ai.activity_tools import get_recent_inventory_movements
from app.ai.agent import organization_scope_text, validate_question
from app.ai.local_model import chat_with_local_model

NOTABLE_ADJUSTMENT_QUANTITY = 10
SEPARATOR = "\n\n------------------------------\n\n"


def format_movement_date(value) -> str:
    if value is None:
        return "Not recorded"
    return value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(value, datetime) else str(value)


def get_stock_effect(transaction_type: str, quantity: int) -> tuple[str, int]:
    transaction_type = (transaction_type or "").upper()
    if transaction_type == "IN":
        return "INCREASE", abs(quantity)
    if transaction_type == "OUT":
        return "DECREASE", abs(quantity)
    if transaction_type == "ADJUSTMENT":
        if quantity > 0:
            return "INCREASE", quantity
        if quantity < 0:
            return "DECREASE", abs(quantity)
        return "NO CHANGE", 0
    return "UNKNOWN", abs(quantity)


def build_activity_summary(movements: list[dict], days: int) -> str:
    if not movements:
        return f"No inventory movements were recorded during the last {days} day(s)."

    items = defaultdict(
        lambda: {
            "name": None,
            "sku": None,
            "transaction_count": 0,
            "units_in": 0,
            "units_out": 0,
            "adjustment_increase": 0,
            "adjustment_decrease": 0,
            "asset_movements": 0,
        }
    )
    notable = []

    for movement in movements:
        item = items[movement["item_id"]]
        item["name"], item["sku"] = movement.get("item_name"), movement.get("sku")
        item["transaction_count"] += 1
        transaction_type = (movement.get("transaction_type") or "").upper()
        quantity = movement.get("quantity") or 0
        effect, effect_quantity = get_stock_effect(transaction_type, quantity)

        if transaction_type == "IN":
            item["units_in"] += effect_quantity
        elif transaction_type == "OUT":
            item["units_out"] += effect_quantity
        elif transaction_type == "ADJUSTMENT":
            key = "adjustment_increase" if effect == "INCREASE" else "adjustment_decrease" if effect == "DECREASE" else None
            if key:
                item[key] += effect_quantity
            if effect_quantity >= NOTABLE_ADJUSTMENT_QUANTITY:
                notable.append(
                    {
                        "transaction_id": movement["transaction_id"],
                        "date": format_movement_date(movement.get("movement_date")),
                        "item_name": movement.get("item_name"),
                        "sku": movement.get("sku"),
                        "stock_effect": effect,
                        "quantity": effect_quantity,
                        "signed_quantity": quantity,
                        "reason": movement.get("reason") or "Not recorded",
                        "actor": movement.get("actor") or "Not recorded",
                    }
                )
        if movement.get("asset_id") is not None:
            item["asset_movements"] += 1

    blocks = [
        "DETERMINISTIC ACTIVITY SUMMARY\n"
        f"Period reviewed: last {days} day(s)\n"
        f"Transactions reviewed: {len(movements)}"
    ]
    for item in items.values():
        net = item["units_in"] - item["units_out"] + item["adjustment_increase"] - item["adjustment_decrease"]
        blocks.append(
            "\n".join(
                (
                    f"ITEM: {item['name']}",
                    f"SKU: {item['sku']}",
                    f"Transactions: {item['transaction_count']}",
                    f"Units received through IN: {item['units_in']}",
                    f"Units issued through OUT: {item['units_out']}",
                    f"Positive adjustments: {item['adjustment_increase']}",
                    f"Negative adjustments: {item['adjustment_decrease']}",
                    f"Calculated net stock effect: {net}",
                    f"Asset-related movements: {item['asset_movements']}",
                )
            )
        )

    if notable:
        lines = ["NOTABLE ADJUSTMENTS"]
        lines += [
            f"Transaction {a['transaction_id']}: {a['item_name']} ({a['sku']}); date {a['date']}; "
            f"stock effect {a['stock_effect']} by {a['quantity']} units; signed database quantity {a['signed_quantity']}; "
            f"reason {a['reason']}; recorded by {a['actor']}."
            for a in notable
        ]
        blocks.append("\n".join(lines))
    return SEPARATOR.join(blocks)


def build_recent_activity_context(movements: list[dict]) -> str:
    if not movements:
        return "No transaction records are available."

    blocks = []
    for movement in movements:
        transaction_type = (movement.get("transaction_type") or "UNKNOWN").upper()
        signed_quantity = movement.get("quantity") or 0
        effect, effect_quantity = get_stock_effect(transaction_type, signed_quantity)
        value = lambda key, default="None": movement.get(key) or default
        blocks.append(
            "\n".join(
                (
                    f"TRANSACTION {movement['transaction_id']}",
                    f"DATE: {format_movement_date(movement.get('movement_date'))}",
                    f"TRANSACTION TYPE: {transaction_type}",
                    f"STOCK EFFECT: {effect}",
                    f"EFFECT QUANTITY: {effect_quantity}",
                    f"SIGNED DATABASE QUANTITY: {signed_quantity}",
                    f"ITEM: {movement.get('item_name')}",
                    f"SKU: {movement.get('sku')}",
                    f"REASON: {value('reason', 'Not recorded')}",
                    f"REFERENCE: {value('reference', 'Not recorded')}",
                    f"RECORDED BY: {value('actor', 'Not recorded')}",
                    f"ASSET CODE: {value('asset_code')}",
                    f"ASSET NAME: {value('asset_name')}",
                    f"ASSET TYPE: {value('asset_type')}",
                    f"STORAGE LOCATION CODE: {value('storage_location_code')}",
                    f"STORAGE LOCATION NAME: {value('storage_location_name')}",
                    f"SITE CODE: {value('site_code')}",
                    f"SITE NAME: {value('site_name')}",
                )
            )
        )
    return SEPARATOR.join(blocks)


def ask_drei_about_recent_activity(*, db: Session, question: str, days: int = 7) -> dict:
    question = validate_question(question)
    days = max(1, min(days, 90))
    movements = get_recent_inventory_movements(db=db, days=days, limit=50)
    summary = build_activity_summary(movements, days)
    context = build_recent_activity_context(movements)
    prompt = (
        f"{organization_scope_text(db)}\n\n"
        "DreiTrack has supplied a deterministically calculated inventory activity summary followed by verified transaction records.\n\n"
        "The deterministic summary is authoritative.\n\n"
        f"{summary}\n\n"
        "VERIFIED TRANSACTION RECORDS\n\n"
        f"{context}\n\n"
        "STRICT RULES\n"
        "Use only the information above.\n"
        "Never invent a transaction ID.\n"
        "Never change a transaction type.\n"
        "Never change a transaction date.\n"
        "Never reverse an increase or decrease.\n"
        "Never change a quantity or its sign.\n"
        "IN means stock increased.\n"
        "OUT means stock decreased.\n"
        "For ADJUSTMENT transactions, use the explicit STOCK EFFECT field instead of interpreting the signed quantity yourself.\n"
        "Do not claim misconduct, stock loss or employee fault from an adjustment.\n"
        "Do not invent reasons for a transaction.\n"
        "For broad summary questions, do not repeat every transaction individually. Summarise the important changes using the deterministic totals.\n"
        "Only list individual transactions if the user's question specifically requires them.\n\n"
        "USER QUESTION\n"
        f"{question}"
    )
    answer = chat_with_local_model([{"role": "user", "content": prompt}])
    return {"answer": answer, "movements": movements, "summary": summary, "days": days}
