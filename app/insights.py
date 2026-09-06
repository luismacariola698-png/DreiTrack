from datetime import datetime, timedelta
from math import ceil
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Item, PurchaseOrder, PurchaseOrderLine, Transaction
from app.services import available_for_item
SAFETY_BUFFER_DAYS = 7

def usage_for_period(db: Session, item_id: int, start_date: datetime, end_date: datetime) -> int:
    transactions = db.scalars(select(Transaction).where(Transaction.item_id == item_id, Transaction.transaction_type == 'OUT', Transaction.movement_date >= start_date, Transaction.movement_date < end_date)).all()
    total_used = 0
    for transaction in transactions:
        total_used += transaction.quantity
    return total_used

def incoming_stock_for_item(db: Session, item_id: int) -> dict:
    order_lines = db.scalars(select(PurchaseOrderLine).where(PurchaseOrderLine.item_id == item_id)).all()
    today = datetime.now().date()
    total_on_order = 0
    trusted_on_order = 0
    overdue_on_order = 0
    overdue_po_ids = set()
    maximum_days_overdue = 0
    for line in order_lines:
        outstanding = line.quantity_ordered - line.quantity_received
        if outstanding <= 0:
            continue
        purchase_order = db.get(PurchaseOrder, line.purchase_order_id)
        if purchase_order is None:
            continue
        total_on_order += outstanding
        is_overdue = False
        days_overdue = 0
        if purchase_order.expected_delivery_date is not None:
            expected_date = purchase_order.expected_delivery_date.date()
            if expected_date < today:
                is_overdue = True
                days_overdue = (today - expected_date).days
        if is_overdue:
            overdue_on_order += outstanding
            overdue_po_ids.add(purchase_order.id)
            maximum_days_overdue = max(maximum_days_overdue, days_overdue)
        else:
            trusted_on_order += outstanding
    return {'total_on_order': total_on_order, 'trusted_on_order': trusted_on_order, 'overdue_on_order': overdue_on_order, 'overdue_order_count': len(overdue_po_ids), 'maximum_days_overdue': maximum_days_overdue}

def learned_lead_time_for_item(db: Session, item_id: int) -> dict:
    order_lines = db.scalars(select(PurchaseOrderLine).where(PurchaseOrderLine.item_id == item_id)).all()
    lead_times = []
    for line in order_lines:
        purchase_order = db.get(PurchaseOrder, line.purchase_order_id)
        if purchase_order is None:
            continue
        if purchase_order.status != 'RECEIVED':
            continue
        receipt_transactions = db.scalars(select(Transaction).where(Transaction.item_id == item_id, Transaction.transaction_type == 'IN', Transaction.reference == purchase_order.po_number).order_by(Transaction.movement_date)).all()
        if not receipt_transactions:
            continue
        final_receipt = receipt_transactions[-1]
        actual_lead_time = (final_receipt.movement_date - purchase_order.order_date).total_seconds() / 86400
        if actual_lead_time >= 0:
            lead_times.append(actual_lead_time)
    if not lead_times:
        return {'average_days': None, 'completed_orders': 0}
    average_days = sum(lead_times) / len(lead_times)
    return {'average_days': round(average_days, 1), 'completed_orders': len(lead_times)}

def generate_item_insight(db: Session, item: Item) -> dict:
    now = datetime.now()
    last_30_days = now - timedelta(days=30)
    last_90_days = now - timedelta(days=90)
    recent_usage = usage_for_period(db=db, item_id=item.id, start_date=last_30_days, end_date=now)
    older_usage = usage_for_period(db=db, item_id=item.id, start_date=last_90_days, end_date=last_30_days)
    recent_daily_usage = recent_usage / 30
    older_daily_usage = older_usage / 60
    weighted_daily_usage = recent_daily_usage * 0.7 + older_daily_usage * 0.3
    available_stock = available_for_item(db, item.id)
    incoming = incoming_stock_for_item(db, item.id)
    on_order = incoming['total_on_order']
    trusted_on_order = incoming['trusted_on_order']
    overdue_on_order = incoming['overdue_on_order']
    overdue_order_count = incoming['overdue_order_count']
    maximum_days_overdue = incoming['maximum_days_overdue']
    projected_stock = available_stock + on_order
    reliable_projected_stock = available_stock + trusted_on_order
    lead_time_learning = learned_lead_time_for_item(db, item.id)
    learned_lead_time = lead_time_learning['average_days']
    completed_orders = lead_time_learning['completed_orders']
    lead_time_mode = (item.lead_time_mode or 'AUTOMATIC').upper()
    if lead_time_mode == 'CONFIGURED':
        effective_lead_time = float(item.lead_time_days)
        lead_time_source = 'CONFIGURED'
    elif learned_lead_time is not None and completed_orders >= 3:
        effective_lead_time = learned_lead_time
        lead_time_source = 'LEARNED'
    else:
        effective_lead_time = float(item.lead_time_days)
        lead_time_source = 'CONFIGURED'
    if weighted_daily_usage > 0:
        estimated_days_remaining = available_stock / weighted_daily_usage
        projected_days_remaining = projected_stock / weighted_daily_usage
        reliable_projected_days = reliable_projected_stock / weighted_daily_usage
    else:
        estimated_days_remaining = None
        projected_days_remaining = None
        reliable_projected_days = None
    coverage_days = effective_lead_time + SAFETY_BUFFER_DAYS
    demand_target_stock = ceil(weighted_daily_usage * coverage_days)
    target_stock = max(item.min_stock, demand_target_stock)
    suggested_reorder_quantity = max(target_stock - reliable_projected_stock, 0)
    reasons = []
    if available_stock <= item.min_stock:
        reasons.append(f'Available stock ({available_stock}) is at or below the minimum level ({item.min_stock}).')
    if estimated_days_remaining is not None and estimated_days_remaining <= effective_lead_time:
        reasons.append(f'Current stock is estimated to last {estimated_days_remaining:.1f} days, while the effective supplier lead time is {effective_lead_time:.1f} days.')
    if trusted_on_order > 0:
        reasons.append(f'{trusted_on_order} unit(s) are on active purchase orders and have not yet been received.')
    if overdue_on_order > 0:
        reasons.append(f'{overdue_on_order} unit(s) are on overdue purchase orders. DreiTrack does not rely on this stock when calculating the suggested reorder quantity.')
    if overdue_order_count > 0:
        reasons.append(f'{overdue_order_count} purchase order(s) are overdue. The oldest current delay is approximately {maximum_days_overdue} day(s).')
    if weighted_daily_usage == 0:
        reasons.append('There is not enough outbound usage history to estimate consumption reliably.')
    if lead_time_mode == 'AUTOMATIC' and completed_orders < 3:
        reasons.append('Automatic lead-time learning does not have enough completed purchase orders yet, so the configured lead time is being used.')
    if lead_time_mode == 'CONFIGURED':
        reasons.append('Lead-time mode is set to Configured, so the manually entered supplier lead time is being used.')
    if suggested_reorder_quantity > 0:
        reasons.append(f'DreiTrack estimates a target stock level of {target_stock} unit(s), including a {SAFETY_BUFFER_DAYS}-day safety buffer. After considering available stock and non-overdue incoming stock, approximately {suggested_reorder_quantity} additional unit(s) may be needed.')
    reorder_risk = False
    if available_stock <= item.min_stock:
        reorder_risk = True
    if estimated_days_remaining is not None and estimated_days_remaining <= effective_lead_time:
        reorder_risk = True
    if suggested_reorder_quantity > 0:
        reorder_risk = True
    if overdue_on_order > 0:
        reorder_risk = True
    if overdue_on_order > 0:
        if suggested_reorder_quantity > 0:
            recommendation = f'Some incoming stock is overdue. Confirm the delayed purchase order with the supplier and consider approximately {suggested_reorder_quantity} additional unit(s) if replacement stock is required.'
        else:
            recommendation = 'Incoming stock is overdue. Confirm the delivery status with the supplier.'
    elif reorder_risk:
        if on_order > 0 and suggested_reorder_quantity == 0:
            recommendation = 'Incoming stock appears sufficient, but monitor the purchase order and confirm that it arrives on time.'
        elif on_order > 0 and suggested_reorder_quantity > 0:
            recommendation = f'Existing purchase orders may not provide enough stock. Consider ordering approximately {suggested_reorder_quantity} additional unit(s).'
        elif suggested_reorder_quantity > 0:
            recommendation = f'Consider reordering approximately {suggested_reorder_quantity} unit(s).'
        else:
            recommendation = "Review this item's stock level."
    elif weighted_daily_usage == 0:
        recommendation = 'Not enough usage data yet.'
    else:
        recommendation = 'Current stock level appears sufficient.'
    total_usage = recent_usage + older_usage
    if total_usage == 0:
        confidence = 'LOW'
    elif total_usage < 10:
        confidence = 'LOW'
    elif total_usage < 30:
        confidence = 'MEDIUM'
    else:
        confidence = 'HIGH'
    return {'item_id': item.id, 'sku': item.sku, 'name': item.name, 'available_stock': available_stock, 'on_order': on_order, 'trusted_on_order': trusted_on_order, 'overdue_on_order': overdue_on_order, 'projected_stock': projected_stock, 'reliable_projected_stock': reliable_projected_stock, 'minimum_stock': item.min_stock, 'overdue_order_count': overdue_order_count, 'maximum_days_overdue': maximum_days_overdue, 'configured_lead_time': item.lead_time_days, 'learned_lead_time': learned_lead_time, 'lead_time_mode': lead_time_mode, 'effective_lead_time': round(effective_lead_time, 1), 'lead_time_source': lead_time_source, 'completed_orders': completed_orders, 'usage_30_days': recent_usage, 'usage_31_to_90_days': older_usage, 'weighted_daily_usage': round(weighted_daily_usage, 3), 'estimated_days_remaining': round(estimated_days_remaining, 1) if estimated_days_remaining is not None else None, 'projected_days_remaining': round(projected_days_remaining, 1) if projected_days_remaining is not None else None, 'reliable_projected_days': round(reliable_projected_days, 1) if reliable_projected_days is not None else None, 'safety_buffer_days': SAFETY_BUFFER_DAYS, 'coverage_days': round(coverage_days, 1), 'target_stock': target_stock, 'suggested_reorder_quantity': suggested_reorder_quantity, 'reorder_recommended': reorder_risk, 'confidence': confidence, 'recommendation': recommendation, 'reasons': reasons}

def generate_inventory_insights(db: Session) -> list[dict]:
    items = db.scalars(select(Item).order_by(Item.name)).all()
    insights = []
    for item in items:
        insight = generate_item_insight(db, item)
        insights.append(insight)
    return insights
