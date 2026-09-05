from collections import defaultdict
from datetime import datetime

from sqlalchemy.orm import Session

from app.ai.activity_tools import (
    get_recent_inventory_movements,
)

from app.ai.agent import (
    organization_scope_text,
    validate_question,
)

from app.ai.local_model import (
    chat_with_local_model,
)


# =========================================================
# SETTINGS
# =========================================================

NOTABLE_ADJUSTMENT_QUANTITY = 10


# =========================================================
# DATE FORMATTING
# =========================================================

def format_movement_date(
    value,
) -> str:
    """
    Format a transaction date consistently.

    The AI receives one explicit date representation
    instead of interpreting raw Python datetime text.
    """

    if value is None:
        return "Not recorded"


    if isinstance(
        value,
        datetime,
    ):
        return value.strftime(
            "%Y-%m-%d %H:%M:%S"
        )


    return str(value)


# =========================================================
# DETERMINE STOCK EFFECT
# =========================================================

def get_stock_effect(
    transaction_type: str,
    quantity: int,
) -> tuple[str, int]:
    """
    Determine the actual stock effect from a
    DreiTrack transaction.

    Returns:

        ("INCREASE", quantity)
        ("DECREASE", quantity)
        ("NO CHANGE", 0)

    This is calculated by Python, not the AI.
    """

    transaction_type = (
        transaction_type
        or ""
    ).upper()


    if transaction_type == "IN":

        return (
            "INCREASE",
            abs(quantity),
        )


    if transaction_type == "OUT":

        return (
            "DECREASE",
            abs(quantity),
        )


    if transaction_type == "ADJUSTMENT":

        if quantity > 0:

            return (
                "INCREASE",
                quantity,
            )


        if quantity < 0:

            return (
                "DECREASE",
                abs(quantity),
            )


        return (
            "NO CHANGE",
            0,
        )


    return (
        "UNKNOWN",
        abs(quantity),
    )


# =========================================================
# BUILD DETERMINISTIC ACTIVITY SUMMARY
# =========================================================

def build_activity_summary(
    movements: list[dict],
    days: int,
) -> str:
    """
    Build a factual activity summary using Python.

    Important quantities, transaction types and stock
    effects are determined here before data reaches
    the language model.
    """

    if not movements:

        return (
            f"No inventory movements were recorded "
            f"during the last {days} day(s)."
        )


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


    notable_adjustments = []


    for movement in movements:

        item_id = movement[
            "item_id"
        ]


        item_summary = items[
            item_id
        ]


        item_summary[
            "name"
        ] = movement.get(
            "item_name"
        )


        item_summary[
            "sku"
        ] = movement.get(
            "sku"
        )


        item_summary[
            "transaction_count"
        ] += 1


        transaction_type = (
            movement.get(
                "transaction_type"
            )
            or ""
        ).upper()


        quantity = movement.get(
            "quantity"
        ) or 0


        effect, effect_quantity = (
            get_stock_effect(
                transaction_type,
                quantity,
            )
        )


        if transaction_type == "IN":

            item_summary[
                "units_in"
            ] += effect_quantity


        elif transaction_type == "OUT":

            item_summary[
                "units_out"
            ] += effect_quantity


        elif (
            transaction_type
            == "ADJUSTMENT"
        ):

            if effect == "INCREASE":

                item_summary[
                    "adjustment_increase"
                ] += effect_quantity


            elif effect == "DECREASE":

                item_summary[
                    "adjustment_decrease"
                ] += effect_quantity


            if (
                effect_quantity
                >= NOTABLE_ADJUSTMENT_QUANTITY
            ):

                notable_adjustments.append(
                    {
                        "transaction_id":
                            movement[
                                "transaction_id"
                            ],

                        "date":
                            format_movement_date(
                                movement.get(
                                    "movement_date"
                                )
                            ),

                        "item_name":
                            movement.get(
                                "item_name"
                            ),

                        "sku":
                            movement.get(
                                "sku"
                            ),

                        "stock_effect":
                            effect,

                        "quantity":
                            effect_quantity,

                        "signed_quantity":
                            quantity,

                        "reason":
                            movement.get(
                                "reason"
                            )
                            or "Not recorded",

                        "actor":
                            movement.get(
                                "actor"
                            )
                            or "Not recorded",
                    }
                )


        if (
            movement.get(
                "asset_id"
            )
            is not None
        ):

            item_summary[
                "asset_movements"
            ] += 1


    # -----------------------------------------------------
    # ITEM SUMMARY
    # -----------------------------------------------------

    lines = [
        (
            "DETERMINISTIC ACTIVITY SUMMARY\n"
            f"Period reviewed: last {days} day(s)\n"
            f"Transactions reviewed: {len(movements)}"
        )
    ]


    for item in items.values():

        net_change = (
            item[
                "units_in"
            ]
            -
            item[
                "units_out"
            ]
            +
            item[
                "adjustment_increase"
            ]
            -
            item[
                "adjustment_decrease"
            ]
        )


        lines.append(
            (
                f"ITEM: {item['name']}\n"
                f"SKU: {item['sku']}\n"
                f"Transactions: "
                f"{item['transaction_count']}\n"
                f"Units received through IN: "
                f"{item['units_in']}\n"
                f"Units issued through OUT: "
                f"{item['units_out']}\n"
                f"Positive adjustments: "
                f"{item['adjustment_increase']}\n"
                f"Negative adjustments: "
                f"{item['adjustment_decrease']}\n"
                f"Calculated net stock effect: "
                f"{net_change}\n"
                f"Asset-related movements: "
                f"{item['asset_movements']}"
            )
        )


    # -----------------------------------------------------
    # NOTABLE ADJUSTMENTS
    # -----------------------------------------------------

    if notable_adjustments:

        adjustment_lines = [
            "NOTABLE ADJUSTMENTS"
        ]


        for adjustment in (
            notable_adjustments
        ):

            adjustment_lines.append(
                (
                    f"Transaction "
                    f"{adjustment['transaction_id']}: "
                    f"{adjustment['item_name']} "
                    f"({adjustment['sku']}); "
                    f"date "
                    f"{adjustment['date']}; "
                    f"stock effect "
                    f"{adjustment['stock_effect']} "
                    f"by "
                    f"{adjustment['quantity']} units; "
                    f"signed database quantity "
                    f"{adjustment['signed_quantity']}; "
                    f"reason "
                    f"{adjustment['reason']}; "
                    f"recorded by "
                    f"{adjustment['actor']}."
                )
            )


        lines.append(
            "\n".join(
                adjustment_lines
            )
        )


    return (
        "\n\n"
        "------------------------------\n\n"
    ).join(
        lines
    )


# =========================================================
# BUILD NORMALISED TRANSACTION CONTEXT
# =========================================================

def build_recent_activity_context(
    movements: list[dict],
) -> str:
    """
    Build explicit transaction records for Drei.

    Transaction type, stock direction and quantity
    are stated separately to reduce interpretation
    mistakes.
    """

    if not movements:

        return (
            "No transaction records are available."
        )


    blocks = []


    for movement in movements:

        transaction_type = (
            movement.get(
                "transaction_type"
            )
            or "UNKNOWN"
        ).upper()


        signed_quantity = (
            movement.get(
                "quantity"
            )
            or 0
        )


        stock_effect, effect_quantity = (
            get_stock_effect(
                transaction_type,
                signed_quantity,
            )
        )


        asset_code = (
            movement.get("asset_code")
            or "None"
        )

        asset_name = (
            movement.get(
                "asset_name"
            )
            or "None"
        )


        asset_type = (
            movement.get(
                "asset_type"
            )
            or "None"
        )


        location_code = movement.get("storage_location_code") or "None"
        location_name = movement.get("storage_location_name") or "None"
        site_code = movement.get("site_code") or "None"
        site_name = movement.get("site_name") or "None"

        blocks.append(
            (
                f"TRANSACTION "
                f"{movement['transaction_id']}\n"

                f"DATE: "
                f"{format_movement_date(movement.get('movement_date'))}\n"

                f"TRANSACTION TYPE: "
                f"{transaction_type}\n"

                f"STOCK EFFECT: "
                f"{stock_effect}\n"

                f"EFFECT QUANTITY: "
                f"{effect_quantity}\n"

                f"SIGNED DATABASE QUANTITY: "
                f"{signed_quantity}\n"

                f"ITEM: "
                f"{movement.get('item_name')}\n"

                f"SKU: "
                f"{movement.get('sku')}\n"

                f"REASON: "
                f"{movement.get('reason') or 'Not recorded'}\n"

                f"REFERENCE: "
                f"{movement.get('reference') or 'Not recorded'}\n"

                f"RECORDED BY: "
                f"{movement.get('actor') or 'Not recorded'}\n"

                f"ASSET CODE: "
                f"{asset_code}\n"

                f"ASSET NAME: "
                f"{asset_name}\n"

                f"ASSET TYPE: "
                f"{asset_type}\n"

                f"STORAGE LOCATION CODE: "
                f"{location_code}\n"

                f"STORAGE LOCATION NAME: "
                f"{location_name}\n"

                f"SITE CODE: "
                f"{site_code}\n"

                f"SITE NAME: "
                f"{site_name}"
            )
        )


    return (
        "\n\n"
        "------------------------------\n\n"
    ).join(
        blocks
    )


# =========================================================
# ASK DREI ABOUT RECENT ACTIVITY
# =========================================================

def ask_drei_about_recent_activity(
    *,
    db: Session,
    question: str,
    days: int = 7,
) -> dict:
    """
    Ask Drei about recent inventory activity.

    Transaction interpretation is performed
    deterministically before the data reaches Drei.
    """

    clean_question = validate_question(
        question
    )


    if days < 1:
        days = 1


    if days > 90:
        days = 90


    movements = (
        get_recent_inventory_movements(
            db=db,
            days=days,
            limit=50,
        )
    )


    activity_summary = (
        build_activity_summary(
            movements=movements,
            days=days,
        )
    )


    transaction_context = (
        build_recent_activity_context(
            movements=movements,
        )
    )


    messages = [
        {
            "role":
                "user",

            "content":
                (
                    f"{organization_scope_text(db)}\n\n"
                    "DreiTrack has supplied a "
                    "deterministically calculated "
                    "inventory activity summary followed "
                    "by verified transaction records.\n\n"

                    "The deterministic summary is "
                    "authoritative.\n\n"

                    f"{activity_summary}\n\n"

                    "VERIFIED TRANSACTION RECORDS\n\n"

                    f"{transaction_context}\n\n"

                    "STRICT RULES\n"

                    "Use only the information above.\n"

                    "Never invent a transaction ID.\n"

                    "Never change a transaction type.\n"

                    "Never change a transaction date.\n"

                    "Never reverse an increase or decrease.\n"

                    "Never change a quantity or its sign.\n"

                    "IN means stock increased.\n"

                    "OUT means stock decreased.\n"

                    "For ADJUSTMENT transactions, use the "
                    "explicit STOCK EFFECT field instead "
                    "of interpreting the signed quantity "
                    "yourself.\n"

                    "Do not claim misconduct, stock loss "
                    "or employee fault from an adjustment.\n"

                    "Do not invent reasons for a "
                    "transaction.\n"

                    "For broad summary questions, do not "
                    "repeat every transaction individually. "
                    "Summarise the important changes using "
                    "the deterministic totals.\n"

                    "Only list individual transactions if "
                    "the user's question specifically "
                    "requires them.\n\n"

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

        "movements":
            movements,

        "summary":
            activity_summary,

        "days":
            days,
    }