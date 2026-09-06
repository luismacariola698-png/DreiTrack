from typing import Any

MAX_REASON_LENGTH = 500
MAX_ANOMALY_LENGTH = 500
MAX_ANOMALIES_PER_ITEM = 10


def clean_context_text(value: Any, max_length: int = 500) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        return "Not available"
    return text if len(text) <= max_length else text[:max_length] + "..."


def build_item_context(*, insight: dict, anomalies: list[dict]) -> str:
    reasons = [f"- {clean_context_text(r, MAX_REASON_LENGTH)}" for r in insight.get("reasons", [])]
    if not reasons:
        reasons = ["- No supporting reasons were recorded."]

    anomaly_lines = [
        f"- [{clean_context_text(a.get('severity'))}] {clean_context_text(a.get('title'))}: "
        f"{clean_context_text(a.get('summary'), MAX_ANOMALY_LENGTH)}"
        for a in anomalies[:MAX_ANOMALIES_PER_ITEM]
    ] or ["- No anomaly thresholds were triggered."]

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
{clean_context_text(insight.get("recommendation"), 1000)}

SUPPORTING FACTORS
{chr(10).join(reasons)}

DETECTED ANOMALIES
{chr(10).join(anomaly_lines)}

</dreitrack_verified_context>
""".strip()
