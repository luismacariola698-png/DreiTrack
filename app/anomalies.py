from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.insights import incoming_stock_for_item, learned_lead_time_for_item, usage_for_period
from app.models import Item, Transaction
USAGE_SPIKE_MULTIPLIER = 1.75
HIGH_USAGE_SPIKE_MULTIPLIER = 2.5
MIN_RECENT_USAGE_FOR_SPIKE = 6
MIN_BASELINE_MONTHLY_USAGE = 2
ADJUSTMENT_REVIEW_COUNT = 3
HIGH_ADJUSTMENT_COUNT = 5
LEAD_TIME_DRIFT_MULTIPLIER = 1.25
HIGH_LEAD_TIME_DRIFT_MULTIPLIER = 1.5
MIN_LEAD_TIME_DRIFT_DAYS = 3
HIGH_OVERDUE_DAYS = 7

def adjustment_activity_for_item(db: Session, item_id: int, start_date: datetime, end_date: datetime) -> dict:
    adjustments = db.scalars(select(Transaction).where(Transaction.item_id == item_id, Transaction.transaction_type == 'ADJUSTMENT', Transaction.movement_date >= start_date, Transaction.movement_date < end_date).order_by(Transaction.movement_date)).all()
    net_adjustment = sum((transaction.quantity for transaction in adjustments))
    absolute_units_adjusted = sum((abs(transaction.quantity) for transaction in adjustments))
    return {'count': len(adjustments), 'net_adjustment': net_adjustment, 'absolute_units_adjusted': absolute_units_adjusted}

def build_anomaly(*, anomaly_type: str, severity: str, item: Item, title: str, summary: str, details: list[str]) -> dict:
    return {'type': anomaly_type, 'severity': severity, 'item_id': item.id, 'sku': item.sku, 'item_name': item.name, 'title': title, 'summary': summary, 'details': details}

def detect_item_anomalies(db: Session, item: Item) -> list[dict]:
    now = datetime.now()
    last_30_days = now - timedelta(days=30)
    last_90_days = now - timedelta(days=90)
    anomalies = []
    recent_usage = usage_for_period(db=db, item_id=item.id, start_date=last_30_days, end_date=now)
    older_usage = usage_for_period(db=db, item_id=item.id, start_date=last_90_days, end_date=last_30_days)
    baseline_monthly_usage = older_usage / 2
    if recent_usage >= MIN_RECENT_USAGE_FOR_SPIKE and baseline_monthly_usage >= MIN_BASELINE_MONTHLY_USAGE:
        usage_ratio = recent_usage / baseline_monthly_usage
        if usage_ratio >= USAGE_SPIKE_MULTIPLIER:
            if usage_ratio >= HIGH_USAGE_SPIKE_MULTIPLIER:
                severity = 'HIGH'
            else:
                severity = 'MEDIUM'
            percentage_change = (usage_ratio - 1) * 100
            anomaly = build_anomaly(anomaly_type='USAGE_SPIKE', severity=severity, item=item, title='Unusual outbound usage', summary=f'Usage during the last 30 days is {percentage_change:.0f}% above the previous monthly baseline.', details=[f'Last 30 days: {recent_usage} unit(s).', f'Previous 60-day monthly baseline: {baseline_monthly_usage:.1f} unit(s).', 'This alert identifies a change in recorded usage, not the cause of the change.'])
            anomalies.append(anomaly)
    adjustment_activity = adjustment_activity_for_item(db=db, item_id=item.id, start_date=last_30_days, end_date=now)
    adjustment_count = adjustment_activity['count']
    if adjustment_count >= ADJUSTMENT_REVIEW_COUNT:
        if adjustment_count >= HIGH_ADJUSTMENT_COUNT:
            severity = 'HIGH'
        else:
            severity = 'MEDIUM'
        anomaly = build_anomaly(anomaly_type='REPEATED_ADJUSTMENTS', severity=severity, item=item, title='Repeated stock adjustments', summary=f'{adjustment_count} manual stock adjustments were recorded during the last 30 days.', details=[f"Total units affected by adjustments: {adjustment_activity['absolute_units_adjusted']}.", f"Net stock change from adjustments: {adjustment_activity['net_adjustment']:+d}.", 'Repeated adjustments may be legitimate, but they are worth reviewing during inventory audits.'])
        anomalies.append(anomaly)
    lead_time_learning = learned_lead_time_for_item(db=db, item_id=item.id)
    learned_lead_time = lead_time_learning['average_days']
    completed_orders = lead_time_learning['completed_orders']
    configured_lead_time = float(item.lead_time_days or 0)
    if learned_lead_time is not None and completed_orders >= 3 and (configured_lead_time > 0):
        lead_time_difference = learned_lead_time - configured_lead_time
        lead_time_ratio = learned_lead_time / configured_lead_time
        if lead_time_difference >= MIN_LEAD_TIME_DRIFT_DAYS and lead_time_ratio >= LEAD_TIME_DRIFT_MULTIPLIER:
            if lead_time_ratio >= HIGH_LEAD_TIME_DRIFT_MULTIPLIER:
                severity = 'HIGH'
            else:
                severity = 'MEDIUM'
            anomaly = build_anomaly(anomaly_type='LEAD_TIME_DRIFT', severity=severity, item=item, title='Supplier lead time is trending longer', summary=f'Completed orders averaged {learned_lead_time:.1f} days compared with the configured {configured_lead_time:.1f} days.', details=[f'Completed orders analysed: {completed_orders}.', f'Observed difference: +{lead_time_difference:.1f} day(s).', 'Consider reviewing the configured lead time or discussing delivery performance with the supplier.'])
            anomalies.append(anomaly)
    incoming = incoming_stock_for_item(db=db, item_id=item.id)
    overdue_on_order = incoming['overdue_on_order']
    overdue_order_count = incoming['overdue_order_count']
    maximum_days_overdue = incoming['maximum_days_overdue']
    if overdue_on_order > 0:
        if maximum_days_overdue >= HIGH_OVERDUE_DAYS:
            severity = 'HIGH'
        else:
            severity = 'MEDIUM'
        anomaly = build_anomaly(anomaly_type='OVERDUE_PO', severity=severity, item=item, title='Purchase order delivery is overdue', summary=f'{overdue_on_order} unit(s) remain outstanding across {overdue_order_count} overdue purchase order(s).', details=[f'Oldest current delay: approximately {maximum_days_overdue} day(s).', 'Overdue incoming stock should not be treated as reliable until delivery is confirmed.'])
        anomalies.append(anomaly)
    return anomalies

def generate_inventory_anomalies(db: Session) -> list[dict]:
    items = db.scalars(select(Item).order_by(Item.name)).all()
    anomalies = []
    for item in items:
        item_anomalies = detect_item_anomalies(db=db, item=item)
        anomalies.extend(item_anomalies)
    severity_order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}
    anomalies.sort(key=lambda anomaly: (severity_order.get(anomaly['severity'], 99), anomaly['item_name'].lower(), anomaly['title'].lower()))
    return anomalies
