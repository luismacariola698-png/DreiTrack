from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Asset, AssetComponent, Item, PurchaseOrder, PurchaseOrderLine, StockRequest, StorageLocation, Transaction
from app.tenancy import current_organization_id

def _validate_item(db: Session, item_id: int) -> Item:
    item = db.get(Item, item_id)
    if item is None:
        raise ValueError('Inventory item not found.')
    return item

def _validate_asset(db: Session, asset_id: int | None) -> Asset | None:
    if asset_id is None:
        return None
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise ValueError('Asset not found.')
    return asset

def _validate_location(db: Session, storage_location_id: int | None) -> StorageLocation | None:
    if storage_location_id is None:
        return None
    location = db.get(StorageLocation, storage_location_id)
    if location is None:
        raise ValueError('Storage location not found.')
    if not location.is_active:
        raise ValueError('Storage location is inactive.')
    return location

def _resolve_location(db: Session, item: Item, storage_location_id: int | None) -> StorageLocation | None:
    if storage_location_id is not None:
        return _validate_location(db, storage_location_id)
    if item.default_storage_location_id is not None:
        return _validate_location(db, item.default_storage_location_id)
    return None

def create_item(
    db: Session,
    sku: str,
    name: str,
    category: str,
    storage_location_id: int,
    min_stock: int=0,
    supplier: str | None=None,
    unit_cost: float | None=None,
    lead_time_days: int=14,
    lead_time_mode: str='AUTOMATIC',
    commit: bool=True,
) -> Item:
    sku = sku.strip()
    name = name.strip()
    category = category.strip()
    mode = lead_time_mode.strip().upper()

    if not sku or not name or not category:
        raise ValueError('SKU, name and category are required.')

    if min_stock < 0 or lead_time_days < 0:
        raise ValueError('Stock and lead time values cannot be negative.')

    if unit_cost is not None and unit_cost < 0:
        raise ValueError('Unit cost cannot be negative.')

    if mode not in {'AUTOMATIC', 'CONFIGURED'}:
        raise ValueError('Invalid lead time mode.')

    location = _validate_location(db, storage_location_id)

    if location is None:
        raise ValueError('A storage location is required.')

    if db.scalar(select(Item).where(Item.sku == sku)) is not None:
        raise ValueError(
            'An item with this SKU already exists in this organization.'
        )

    item = Item(
        organization_id=current_organization_id(db),
        sku=sku,
        name=name,
        category=category,
        default_storage_location_id=location.id,
        location=location.name,
        min_stock=min_stock,
        supplier=supplier.strip() if supplier and supplier.strip() else None,
        unit_cost=unit_cost,
        lead_time_days=lead_time_days,
        lead_time_mode=mode,
    )

    db.add(item)

    if commit:
        db.commit()
        db.refresh(item)
    else:
        db.flush()

    return item

def stock_for_item(db: Session, item_id: int, storage_location_id: int | None=None) -> int:
    query = select(Transaction).where(Transaction.item_id == item_id)
    if storage_location_id is not None:
        query = query.where(Transaction.storage_location_id == storage_location_id)
    transactions = db.scalars(query).all()
    total = 0
    for transaction in transactions:
        if transaction.transaction_type == 'IN':
            total += transaction.quantity
        elif transaction.transaction_type == 'OUT':
            total -= transaction.quantity
        elif transaction.transaction_type == 'ADJUSTMENT':
            total += transaction.quantity
    return total

def reserved_for_item(db: Session, item_id: int, storage_location_id: int | None=None) -> int:
    query = select(StockRequest).where(StockRequest.item_id == item_id, StockRequest.status == 'APPROVED')
    if storage_location_id is not None:
        query = query.where(StockRequest.storage_location_id == storage_location_id)
    requests = db.scalars(query).all()
    return sum((request.quantity for request in requests))

def available_for_item(db: Session, item_id: int, storage_location_id: int | None=None) -> int:
    return stock_for_item(db, item_id, storage_location_id) - reserved_for_item(db, item_id, storage_location_id)

def create_stock_in(
    db: Session,
    item_id: int,
    quantity: int,
    reason: str,
    actor: str | None=None,
    asset_id: int | None=None,
    storage_location_id: int | None=None,
    reference: str | None=None,
    notes: str | None=None,
    commit: bool=True,
) -> Transaction:
    if quantity <= 0:
        raise ValueError('Stock-in quantity must be greater than zero.')

    item = _validate_item(db, item_id)
    _validate_asset(db, asset_id)
    location = _resolve_location(db, item, storage_location_id)

    transaction = Transaction(
        organization_id=current_organization_id(db),
        item_id=item_id,
        asset_id=asset_id,
        storage_location_id=location.id if location else None,
        transaction_type='IN',
        quantity=quantity,
        reason=reason,
        actor=actor,
        reference=reference,
        notes=notes,
    )

    db.add(transaction)

    if commit:
        db.commit()
        db.refresh(transaction)
    else:
        db.flush()

    return transaction

def create_stock_out(db: Session, item_id: int, quantity: int, reason: str, actor: str | None=None, asset_id: int | None=None, storage_location_id: int | None=None, reference: str | None=None, notes: str | None=None) -> Transaction:
    if quantity <= 0:
        raise ValueError('Stock-out quantity must be greater than zero.')
    item = _validate_item(db, item_id)
    _validate_asset(db, asset_id)
    location = _resolve_location(db, item, storage_location_id)
    location_id = location.id if location else None
    available_stock = available_for_item(db, item_id, location_id)
    if quantity > available_stock:
        label = 'selected location' if location_id is not None else 'organization'
        raise ValueError(f'Not enough unreserved stock available at the {label}.')
    transaction = Transaction(organization_id=current_organization_id(db), item_id=item_id, asset_id=asset_id, storage_location_id=location_id, transaction_type='OUT', quantity=quantity, reason=reason, actor=actor, reference=reference, notes=notes)
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return transaction

def issue_component_to_asset(db: Session, asset_component_id: int, quantity: int, reason: str, actor: str | None=None, storage_location_id: int | None=None, reference: str | None=None, notes: str | None=None) -> Transaction:
    if quantity <= 0:
        raise ValueError('Issue quantity must be greater than zero.')
    component = db.get(AssetComponent, asset_component_id)
    if component is None:
        raise ValueError('Asset component requirement not found.')
    remaining_required = component.quantity_required - component.quantity_assigned
    if quantity > remaining_required:
        raise ValueError('Cannot assign more than the asset requires.')
    transaction = create_stock_out(db=db, item_id=component.item_id, quantity=quantity, reason=reason, actor=actor, asset_id=component.asset_id, storage_location_id=storage_location_id, reference=reference, notes=notes)
    component.quantity_assigned += quantity
    db.commit()
    db.refresh(component)
    return transaction

def create_stock_transfer(db: Session, item_id: int, quantity: int, from_storage_location_id: int, to_storage_location_id: int, actor: str | None=None, reference: str | None=None, notes: str | None=None) -> tuple[Transaction, Transaction]:
    """Atomically transfer stock between two locations in one organization."""
    if quantity <= 0:
        raise ValueError('Transfer quantity must be greater than zero.')
    if from_storage_location_id == to_storage_location_id:
        raise ValueError('Source and destination locations must be different.')
    item = _validate_item(db, item_id)
    from_location = _validate_location(db, from_storage_location_id)
    to_location = _validate_location(db, to_storage_location_id)
    if from_location is None or to_location is None:
        raise ValueError('Both transfer locations are required.')
    available = available_for_item(db, item.id, from_location.id)
    if quantity > available:
        raise ValueError('Not enough unreserved stock at the source location.')
    organization_id = current_organization_id(db)
    transfer_reference = reference or f'TRANSFER-{datetime.now():%Y%m%d-%H%M%S}'
    outgoing = Transaction(organization_id=organization_id, item_id=item.id, storage_location_id=from_location.id, transaction_type='OUT', quantity=quantity, reason=f'Transfer to {to_location.code}', actor=actor, reference=transfer_reference, notes=notes)
    incoming = Transaction(organization_id=organization_id, item_id=item.id, storage_location_id=to_location.id, transaction_type='IN', quantity=quantity, reason=f'Transfer from {from_location.code}', actor=actor, reference=transfer_reference, notes=notes)
    db.add_all([outgoing, incoming])
    db.commit()
    db.refresh(outgoing)
    db.refresh(incoming)
    return (outgoing, incoming)

def create_request(db: Session, item_id: int, quantity: int, requested_by: str, reason: str, asset_id: int | None=None, storage_location_id: int | None=None, notes: str | None=None) -> StockRequest:
    if quantity <= 0:
        raise ValueError('Request quantity must be greater than zero.')
    item = _validate_item(db, item_id)
    _validate_asset(db, asset_id)
    location = _resolve_location(db, item, storage_location_id)
    request = StockRequest(organization_id=current_organization_id(db), item_id=item_id, asset_id=asset_id, storage_location_id=location.id if location else None, quantity=quantity, requested_by=requested_by, reason=reason, status='PENDING', notes=notes)
    db.add(request)
    db.commit()
    db.refresh(request)
    return request

def approve_request(db: Session, request_id: int, approved_by: str) -> StockRequest:
    request = db.get(StockRequest, request_id)
    if request is None:
        raise ValueError('Request not found.')
    if request.status != 'PENDING':
        raise ValueError('Only pending requests can be approved.')
    available_stock = available_for_item(db, request.item_id, request.storage_location_id)
    if request.quantity > available_stock:
        raise ValueError('Not enough available stock to approve this request.')
    request.status = 'APPROVED'
    request.approved_by = approved_by
    request.approved_at = datetime.now()
    db.commit()
    db.refresh(request)
    return request

def collect_request(db: Session, request_id: int, collected_by: str) -> StockRequest:
    request = db.get(StockRequest, request_id)
    if request is None:
        raise ValueError('Request not found.')
    if request.status != 'APPROVED':
        raise ValueError('Only approved requests can be collected.')
    physical_stock = stock_for_item(db, request.item_id, request.storage_location_id)
    if request.quantity > physical_stock:
        raise ValueError('Physical stock is no longer sufficient at this location.')
    component = None
    if request.asset_id is not None:
        _validate_asset(db, request.asset_id)
        component = db.scalar(select(AssetComponent).where(AssetComponent.asset_id == request.asset_id, AssetComponent.item_id == request.item_id))
        if component is not None:
            remaining_required = component.quantity_required - component.quantity_assigned
            if request.quantity > remaining_required:
                raise ValueError("Requested quantity exceeds the asset's remaining tracked requirement.")
    transaction = Transaction(organization_id=current_organization_id(db), item_id=request.item_id, asset_id=request.asset_id, storage_location_id=request.storage_location_id, transaction_type='OUT', quantity=request.quantity, reason=request.reason, actor=collected_by, reference=f'REQ-{request.id}')
    db.add(transaction)
    if component is not None:
        component.quantity_assigned += request.quantity
    request.status = 'COLLECTED'
    request.collected_at = datetime.now()
    db.commit()
    db.refresh(request)
    db.refresh(transaction)
    if component is not None:
        db.refresh(component)
    return request

def create_purchase_order(db: Session, po_number: str, supplier: str, item_id: int, quantity: int, created_by: str | None=None, unit_cost: float | None=None, expected_delivery_date: datetime | None=None, notes: str | None=None) -> PurchaseOrder:
    if quantity <= 0:
        raise ValueError('Purchase order quantity must be greater than zero.')
    _validate_item(db, item_id)
    existing_po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == po_number.strip()))
    if existing_po is not None:
        raise ValueError('A purchase order with this PO number already exists.')
    organization_id = current_organization_id(db)
    purchase_order = PurchaseOrder(organization_id=organization_id, po_number=po_number.strip(), supplier=supplier.strip(), expected_delivery_date=expected_delivery_date, status='ORDERED', created_by=created_by, notes=notes)
    db.add(purchase_order)
    db.flush()
    purchase_order_line = PurchaseOrderLine(organization_id=organization_id, purchase_order_id=purchase_order.id, item_id=item_id, quantity_ordered=quantity, quantity_received=0, unit_cost=unit_cost)
    db.add(purchase_order_line)
    db.commit()
    db.refresh(purchase_order)
    return purchase_order

def receive_purchase_order(db: Session, order_line_id: int, quantity: int, received_by: str | None=None, storage_location_id: int | None=None, notes: str | None=None) -> PurchaseOrderLine:
    if quantity <= 0:
        raise ValueError('Received quantity must be greater than zero.')
    order_line = db.get(PurchaseOrderLine, order_line_id)
    if order_line is None:
        raise ValueError('Purchase order line not found.')
    purchase_order = db.get(PurchaseOrder, order_line.purchase_order_id)
    if purchase_order is None:
        raise ValueError('Purchase order not found.')
    item = _validate_item(db, order_line.item_id)
    location = _resolve_location(db, item, storage_location_id)
    remaining_quantity = order_line.quantity_ordered - order_line.quantity_received
    if quantity > remaining_quantity:
        raise ValueError('Cannot receive more than the outstanding quantity.')
    transaction = Transaction(organization_id=current_organization_id(db), item_id=order_line.item_id, storage_location_id=location.id if location else None, transaction_type='IN', quantity=quantity, reason='New Supplier Delivery', actor=received_by, reference=purchase_order.po_number, notes=notes)
    db.add(transaction)
    order_line.quantity_received += quantity
    order_lines = db.scalars(select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == purchase_order.id)).all()
    all_received = all((line.quantity_received >= line.quantity_ordered for line in order_lines))
    any_received = any((line.quantity_received > 0 for line in order_lines))
    if all_received:
        purchase_order.status = 'RECEIVED'
    elif any_received:
        purchase_order.status = 'PARTIALLY RECEIVED'
    else:
        purchase_order.status = 'ORDERED'
    db.commit()
    db.refresh(order_line)
    db.refresh(purchase_order)
    db.refresh(transaction)
    return order_line

def create_stock_adjustment(db: Session, item_id: int, adjustment: int, reason: str, actor: str | None=None, storage_location_id: int | None=None, reference: str | None=None, notes: str | None=None) -> Transaction:
    if adjustment == 0:
        raise ValueError('Adjustment cannot be zero.')
    item = _validate_item(db, item_id)
    location = _resolve_location(db, item, storage_location_id)
    location_id = location.id if location else None
    current_stock = stock_for_item(db, item_id, location_id)
    new_stock = current_stock + adjustment
    if new_stock < 0:
        raise ValueError('Adjustment would make physical stock negative at this location.')
    transaction = Transaction(organization_id=current_organization_id(db), item_id=item_id, storage_location_id=location_id, transaction_type='ADJUSTMENT', quantity=adjustment, reason=reason, actor=actor, reference=reference, notes=notes)
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return transaction

def reject_request(db: Session, request_id: int, rejected_by: str, notes: str | None=None) -> StockRequest:
    request = db.get(StockRequest, request_id)
    if request is None:
        raise ValueError('Request not found.')
    if request.status != 'PENDING':
        raise ValueError('Only pending requests can be rejected.')
    request.status = 'REJECTED'
    request.approved_by = rejected_by
    if notes:
        request.notes = notes
    db.commit()
    db.refresh(request)
    return request

def return_component_from_asset(db: Session, asset_component_id: int, quantity: int, returned_by: str | None=None, storage_location_id: int | None=None, notes: str | None=None) -> Transaction:
    if quantity <= 0:
        raise ValueError('Return quantity must be greater than zero.')
    component = db.get(AssetComponent, asset_component_id)
    if component is None:
        raise ValueError('Asset component requirement not found.')
    if quantity > component.quantity_assigned:
        raise ValueError('Cannot return more than the quantity assigned.')
    item = _validate_item(db, component.item_id)
    location = _resolve_location(db, item, storage_location_id)
    transaction = Transaction(organization_id=current_organization_id(db), item_id=component.item_id, asset_id=component.asset_id, storage_location_id=location.id if location else None, transaction_type='IN', quantity=quantity, reason='Returned from asset', actor=returned_by, reference=f'ASSET-{component.asset_id}', notes=notes)
    db.add(transaction)
    component.quantity_assigned -= quantity
    db.commit()
    db.refresh(transaction)
    db.refresh(component)
    return transaction
