from typing import Any


# =========================================================
# CONTEXT LIMITS
# =========================================================

MAX_REASON_LENGTH = 500

MAX_ANOMALY_LENGTH = 500

MAX_ANOMALIES_PER_ITEM = 10


# =========================================================
# SAFE TEXT CONVERSION
# =========================================================

def clean_context_text(
    value: Any,
    max_length: int = 500,
) -> str:
    """
    Convert DreiTrack data to bounded plain text
    before supplying it to the local model.
    """

    if value is None:

        return "Not available"


    text = str(
        value
    ).strip()


    if not text:

        return "Not available"


    if len(text) > max_length:

        text = (
            text[:max_length]
            + "..."
        )


    return text


# =========================================================
# BUILD ITEM CONTEXT
# =========================================================

def build_item_context(
    *,
    insight: dict,
    anomalies: list[dict],
) -> str:
    """
    Convert verified DreiTrack planning and anomaly
    data into a bounded context block for Drei.

    The context contains data, not instructions.
    """


    # -----------------------------------------------------
    # PLANNING REASONS
    # -----------------------------------------------------

    reasons = insight.get(
        "reasons",
        []
    )


    reason_lines = []


    for reason in reasons:

        reason_lines.append(
            (
                "- "
                + clean_context_text(
                    reason,
                    MAX_REASON_LENGTH,
                )
            )
        )


    if not reason_lines:

        reason_lines.append(
            "- No supporting reasons were recorded."
        )


    # -----------------------------------------------------
    # ANOMALIES
    # -----------------------------------------------------

    anomaly_lines = []


    for anomaly in anomalies[
        :MAX_ANOMALIES_PER_ITEM
    ]:

        severity = (
            clean_context_text(
                anomaly.get(
                    "severity"
                )
            )
        )


        title = (
            clean_context_text(
                anomaly.get(
                    "title"
                )
            )
        )


        summary = (
            clean_context_text(
                anomaly.get(
                    "summary"
                ),
                MAX_ANOMALY_LENGTH,
            )
        )


        anomaly_lines.append(
            (
                f"- [{severity}] "
                f"{title}: "
                f"{summary}"
            )
        )


    if not anomaly_lines:

        anomaly_lines.append(
            "- No anomaly thresholds were triggered."
        )


    # -----------------------------------------------------
    # VERIFIED CONTEXT
    # -----------------------------------------------------

    return f"""
<dreitrack_verified_context>

ITEM
SKU: {clean_context_text(insight.get("sku"))}
Name: {clean_context_text(insight.get("name"))}

STOCK POSITION
Available stock: {insight.get("available_stock")}
Minimum stock: {insight.get("minimum_stock")}
Stock on order: {insight.get("on_order")}
Projected stock: {insight.get("projected_stock")}

USAGE
Usage during last 30 days: {insight.get("usage_30_days")}
Usage during days 31 to 90: {insight.get("usage_31_to_90_days")}
Estimated weighted daily usage: {insight.get("weighted_daily_usage")}

STOCK COVERAGE
Estimated current days remaining: {insight.get("estimated_days_remaining")}
Projected days remaining: {insight.get("projected_days_remaining")}

SUPPLIER LEAD TIME
Configured lead time: {insight.get("configured_lead_time")} days
Learned lead time: {insight.get("learned_lead_time")}
Effective lead time: {insight.get("effective_lead_time")} days
Lead-time mode: {clean_context_text(insight.get("lead_time_mode"))}
Lead-time source: {clean_context_text(insight.get("lead_time_source"))}
Completed orders analysed: {insight.get("completed_orders")}

PROCUREMENT PLANNING
Safety buffer: {insight.get("safety_buffer_days")} days
Coverage target: {insight.get("coverage_days")} days
Target stock level: {insight.get("target_stock")}
Suggested reorder quantity: {insight.get("suggested_reorder_quantity")}
Reorder recommended: {insight.get("reorder_recommended")}
Confidence: {clean_context_text(insight.get("confidence"))}

DREITRACK RECOMMENDATION
{clean_context_text(
    insight.get("recommendation"),
    1000,
)}

SUPPORTING FACTORS
{chr(10).join(reason_lines)}

DETECTED ANOMALIES
{chr(10).join(anomaly_lines)}

</dreitrack_verified_context>
""".strip()