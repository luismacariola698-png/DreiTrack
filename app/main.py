from __future__ import annotations
from datetime import datetime
import os
from pathlib import Path
from types import SimpleNamespace
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
from app.ai.agent import DreiAgentError, ask_drei_about_attention, ask_drei_about_item, ask_drei_about_overdue_orders
from app.ai.local_model import LocalAIError, get_local_ai_status
from app.anomalies import generate_inventory_anomalies
from app.database import Base, SessionLocal, engine, get_db
from app.insights import generate_inventory_insights, incoming_stock_for_item
from app.importer import (
    IMPORT_FIELDS,
    delete_import_file,
    load_import_file,
    parse_inventory_file,
    store_import_file,
    suggest_column_mapping,
    validate_inventory_rows,
)
from app.network import is_allowed_private_client, network_access_context, same_origin_or_local_request
from app.models import AppUser, Asset, AssetComponent, AssetType, Item, Organization, PurchaseOrder, PurchaseOrderLine, Site, StockRequest, StorageLocation, Transaction
from app.security import ROLE_ADMIN, ROLE_MANAGER, ROLE_STAFF, VALID_ROLES, hash_password, require_roles, session_secret, verify_password
from app.services import approve_request, available_for_item, collect_request, create_item, create_purchase_order, create_request, create_stock_adjustment, create_stock_in, create_stock_out, create_stock_transfer, receive_purchase_order, reject_request, reserved_for_item, return_component_from_asset, stock_for_item
from app.tenancy import create_organization_defaults, current_organization_id, location_label, unique_organization_slug
Base.metadata.create_all(bind=engine)
BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(
    title='DreiTrack',
    description='Private Company Physical Inventory, Procurement & Asset Management System',
    version='0.4.2'
)
app.mount('/static', StaticFiles(directory=str(BASE_DIR / 'static')), name='static')
templates = Jinja2Templates(directory=str(BASE_DIR / 'templates'))
PUBLIC_PATHS = {'/login', '/setup'}
UNSAFE_HTTP_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}

@app.middleware('http')
async def private_network_security(request: Request, call_next):
    """Reject public-source traffic and obvious cross-site browser writes.

    DreiTrack v0.4.1 is a private-LAN build. Real Uvicorn clients arrive with a
    numeric IP address, so public numeric addresses are rejected at the app
    layer in addition to the Windows Firewall rule installed by the LAN setup
    helper.
    """
    client_host = request.client.host if request.client is not None else None
    if not is_allowed_private_client(client_host):
        return PlainTextResponse('DreiTrack is restricted to this computer and its private company network.', status_code=403)
    if request.method.upper() in UNSAFE_HTTP_METHODS:
        if not same_origin_or_local_request(host_header=request.headers.get('host'), origin_header=request.headers.get('origin'), referer_header=request.headers.get('referer')):
            return PlainTextResponse('Cross-site request blocked by DreiTrack.', status_code=403)
    return await call_next(request)

@app.middleware('http')
async def authentication_context(request: Request, call_next):
    path = request.url.path
    if path.startswith('/static/'):
        return await call_next(request)
    with SessionLocal() as db:
        user_count = db.scalar(select(func.count(AppUser.id))) or 0
        organization_count = db.scalar(select(func.count(Organization.id))) or 0
        if user_count == 0 and organization_count == 0:
            if path != '/setup' and (not path.startswith('/static/')):
                return RedirectResponse('/setup', status_code=303)
            return await call_next(request)
        if user_count == 0 and organization_count > 0:
            if path == '/login':
                return await call_next(request)
            return RedirectResponse('/login', status_code=303)
        if path in PUBLIC_PATHS:
            return await call_next(request)
        user_id = request.session.get('user_id')
        if user_id is None:
            return RedirectResponse('/login', status_code=303)
        user = db.get(AppUser, int(user_id))
        if user is None or not user.is_active:
            request.session.clear()
            return RedirectResponse('/login', status_code=303)
        organization = db.get(Organization, user.organization_id)
        if organization is None or not organization.is_active:
            request.session.clear()
            return RedirectResponse('/login', status_code=303)
        request.state.user = SimpleNamespace(id=user.id, organization_id=user.organization_id, email=user.email, display_name=user.display_name, role=user.role)
        request.state.organization = SimpleNamespace(id=organization.id, name=organization.name, slug=organization.slug)
        request.state.organization_id = organization.id
    return await call_next(request)
app.add_middleware(SessionMiddleware, secret_key=session_secret(), same_site='lax', https_only=os.getenv('DREITRACK_HTTPS_ONLY', '0').strip().lower() in {'1', 'true', 'yes', 'on'}, max_age=60 * 60 * 12)

def actor_name(request: Request) -> str:
    return request.state.user.display_name

def asset_display_label(asset: Asset | None) -> str:
    if asset is None:
        return '-'
    if asset.name and asset.name.strip() and (asset.name.strip() != asset.code):
        return f'{asset.code} - {asset.name.strip()}'
    return asset.code

def site_display_label(site: Site | None) -> str:
    if site is None:
        return '-'
    return f'{site.code} - {site.name}'

def on_order_for_item(db: Session, item_id: int) -> int:
    return incoming_stock_for_item(db, item_id)['total_on_order']

def parse_optional_int(value: str, label: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f'Invalid {label}.') from exc

def active_locations(db: Session) -> list[StorageLocation]:
    return db.scalars(select(StorageLocation).where(StorageLocation.is_active.is_(True)).order_by(StorageLocation.name)).all()

def active_sites(db: Session) -> list[Site]:
    return db.scalars(select(Site).where(Site.is_active.is_(True)).order_by(Site.name)).all()

def active_asset_types(db: Session) -> list[AssetType]:
    return db.scalars(select(AssetType).where(AssetType.is_active.is_(True)).order_by(AssetType.name)).all()

def safe_commit(db: Session, detail: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=detail) from exc

def service_or_400(function, /, **kwargs):
    try:
        return function(**kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.get('/setup', response_class=HTMLResponse)
def setup_page(request: Request, db: Session=Depends(get_db)):
    user_count = db.scalar(select(func.count(AppUser.id))) or 0
    organization_count = db.scalar(select(func.count(Organization.id))) or 0
    if user_count > 0 or organization_count > 0:
        return RedirectResponse('/login', status_code=303)
    return templates.TemplateResponse(request=request, name='setup.html', context={})

@app.post('/setup')
def setup_create(request: Request, organization_name: str=Form(...), admin_name: str=Form(...), email: str=Form(...), password: str=Form(...), db: Session=Depends(get_db)):
    user_count = db.scalar(select(func.count(AppUser.id))) or 0
    organization_count = db.scalar(select(func.count(Organization.id))) or 0
    if user_count > 0 or organization_count > 0:
        raise HTTPException(status_code=400, detail='Initial company setup is already complete.')
    clean_org = organization_name.strip()
    clean_name = admin_name.strip()
    clean_email = email.strip().lower()
    if not clean_org or not clean_name or (not clean_email):
        raise HTTPException(status_code=400, detail='All setup fields are required.')
    try:
        password_hash = hash_password(password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    organization = Organization(name=clean_org, slug=unique_organization_slug(db, clean_org), is_active=True)
    db.add(organization)
    db.flush()
    create_organization_defaults(db, organization)
    user = AppUser(organization_id=organization.id, email=clean_email, display_name=clean_name, password_hash=password_hash, role=ROLE_ADMIN, is_active=True)
    db.add(user)
    safe_commit(db, 'Could not complete initial company setup.')
    db.refresh(user)
    request.session['user_id'] = user.id
    return RedirectResponse('/', status_code=303)

@app.get('/login', response_class=HTMLResponse)
def login_page(request: Request):
    if request.session.get('user_id'):
        return RedirectResponse('/', status_code=303)
    return templates.TemplateResponse(request=request, name='login.html', context={'error': None})

@app.post('/login', response_class=HTMLResponse)
def login_submit(request: Request, email: str=Form(...), password: str=Form(...), db: Session=Depends(get_db)):
    user = db.scalar(select(AppUser).where(AppUser.email == email.strip().lower()))
    if user is None or not user.is_active or (not verify_password(password, user.password_hash)):
        return templates.TemplateResponse(request=request, name='login.html', context={'error': 'Invalid email or password.'}, status_code=400)
    request.session['user_id'] = user.id
    return RedirectResponse('/', status_code=303)

@app.post('/logout')
def logout(request: Request):
    request.session.clear()
    return RedirectResponse('/login', status_code=303)

@app.post('/account/password')
def change_password(request: Request, current_password: str=Form(...), new_password: str=Form(...), db: Session=Depends(get_db)):
    user = db.get(AppUser, request.state.user.id)
    if user is None:
        raise HTTPException(status_code=404, detail='User not found.')
    if not verify_password(current_password, user.password_hash):
        raise HTTPException(status_code=400, detail='Current password is incorrect.')
    try:
        user.password_hash = hash_password(new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return RedirectResponse('/settings', status_code=303)

@app.get('/', response_class=HTMLResponse)
def dashboard_page(request: Request, db: Session=Depends(get_db)):
    items = db.scalars(select(Item).order_by(Item.name)).all()
    stock_requests = db.scalars(select(StockRequest)).all()
    purchase_orders = db.scalars(select(PurchaseOrder)).all()
    assets = db.scalars(select(Asset)).all()
    total_physical_stock = 0
    total_reserved_stock = 0
    low_stock_items = []
    for item in items:
        physical = stock_for_item(db, item.id)
        reserved = reserved_for_item(db, item.id)
        available = available_for_item(db, item.id)
        total_physical_stock += physical
        total_reserved_stock += reserved
        if available <= item.min_stock:
            low_stock_items.append({'id': item.id, 'sku': item.sku, 'name': item.name, 'available': available, 'minimum': item.min_stock})
    pending_requests = sum((r.status == 'PENDING' for r in stock_requests))
    approved_requests = sum((r.status == 'APPROVED' for r in stock_requests))
    today = datetime.now().date()
    open_orders = 0
    overdue_orders = 0
    for purchase_order in purchase_orders:
        if purchase_order.status in ('ORDERED', 'PARTIALLY RECEIVED'):
            open_orders += 1
            if purchase_order.expected_delivery_date is not None and purchase_order.expected_delivery_date.date() < today:
                overdue_orders += 1
    return templates.TemplateResponse(request=request, name='dashboard.html', context={'total_items': len(items), 'total_physical_stock': total_physical_stock, 'total_reserved_stock': total_reserved_stock, 'low_stock_count': len(low_stock_items), 'low_stock_items': low_stock_items, 'pending_requests': pending_requests, 'approved_requests': approved_requests, 'open_orders': open_orders, 'overdue_orders': overdue_orders, 'total_assets': len(assets), 'total_sites': db.scalar(select(func.count(Site.id))) or 0, 'total_locations': db.scalar(select(func.count(StorageLocation.id))) or 0})

@app.get('/api/inventory')
def inventory_api(db: Session=Depends(get_db)):
    items = db.scalars(select(Item).order_by(Item.name)).all()
    return [{'id': item.id, 'sku': item.sku, 'name': item.name, 'category': item.category, 'default_location': location_label(db, item.default_storage_location_id), 'physical_stock': stock_for_item(db, item.id), 'reserved_stock': reserved_for_item(db, item.id), 'available_stock': available_for_item(db, item.id), 'on_order': on_order_for_item(db, item.id), 'minimum_stock': item.min_stock, 'supplier': item.supplier, 'unit_cost': item.unit_cost, 'lead_time_days': item.lead_time_days, 'lead_time_mode': item.lead_time_mode} for item in items]

@app.get('/inventory', response_class=HTMLResponse)
def inventory_page(request: Request, imported: int=0, db: Session=Depends(get_db)):
    items = db.scalars(select(Item).order_by(Item.name)).all()
    inventory = [{'id': item.id, 'sku': item.sku, 'name': item.name, 'category': item.category, 'location': location_label(db, item.default_storage_location_id), 'physical_stock': stock_for_item(db, item.id), 'reserved_stock': reserved_for_item(db, item.id), 'available_stock': available_for_item(db, item.id), 'on_order': on_order_for_item(db, item.id), 'minimum_stock': item.min_stock} for item in items]
    return templates.TemplateResponse(request=request, name='inventory.html', context={'items': inventory, 'storage_locations': active_locations(db), 'imported': imported})

@app.get('/inventory/import', response_class=HTMLResponse)
def inventory_import_page(request: Request, db: Session=Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN, ROLE_MANAGER))):
    return templates.TemplateResponse(
        request=request,
        name='inventory_import.html',
        context={
            'error': None,
            'preview': None,
            'import_fields': IMPORT_FIELDS,
            'storage_locations': active_locations(db),
        },
    )

@app.post('/inventory/import/preview', response_class=HTMLResponse)
async def inventory_import_preview(request: Request, file: UploadFile=File(...), db: Session=Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN, ROLE_MANAGER))):
    filename = file.filename or ''
    try:
        content = await file.read()
        headers, rows = parse_inventory_file(filename, content)
        token = store_import_file(request.state.user.id, filename, content)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request,
            name='inventory_import.html',
            context={
                'error': str(exc),
                'preview': None,
                'import_fields': IMPORT_FIELDS,
                'storage_locations': active_locations(db),
            },
            status_code=400,
        )
    finally:
        await file.close()

    suggestions = suggest_column_mapping(headers)
    return templates.TemplateResponse(
        request=request,
        name='inventory_import.html',
        context={
            'error': None,
            'import_fields': IMPORT_FIELDS,
            'storage_locations': active_locations(db),
            'preview': {
                'token': token,
                'filename': filename,
                'headers': headers,
                'rows': rows[:25],
                'total_rows': len(rows),
                'mapping': {
                    index: suggestions.get(header, '')
                    for index, header in enumerate(headers)
                },
            },
        },
    )

@app.post('/inventory/import/commit')
async def inventory_import_commit(request: Request, db: Session=Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN, ROLE_MANAGER))):
    form = await request.form()
    token = str(form.get('token', ''))
    filename = Path(str(form.get('filename', 'Inventory Import'))).name[:255]
    default_category = str(form.get('default_category', '')).strip()

    try:
        default_location_id = int(str(form.get('default_storage_location_id', '')))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='Invalid default storage location.') from exc

    default_location = db.get(StorageLocation, default_location_id)
    if default_location is None or not default_location.is_active:
        raise HTTPException(status_code=400, detail='Invalid default storage location.')

    try:
        stored_filename, content = load_import_file(request.state.user.id, token)
        headers, rows = parse_inventory_file(stored_filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    mapping = {}
    used_fields = set()
    for index in range(len(headers)):
        field = str(form.get(f'map_{index}', '')).strip()
        if not field:
            continue
        if field not in IMPORT_FIELDS:
            raise HTTPException(status_code=400, detail='Invalid inventory column mapping.')
        if field in used_fields:
            raise HTTPException(status_code=400, detail=f'{IMPORT_FIELDS[field]} was mapped more than once.')
        mapping[index] = field
        used_fields.add(field)

    for required in ('sku', 'name'):
        if required not in used_fields:
            raise HTTPException(status_code=400, detail=f'{IMPORT_FIELDS[required]} must be mapped.')

    locations = active_locations(db)
    location_lookup = {}
    for location in locations:
        location_lookup[location.code.casefold()] = location.id
        location_lookup[location.name.casefold()] = location.id

    existing_skus = set(db.scalars(select(Item.sku)).all())
    validated_rows, errors = validate_inventory_rows(
        rows=rows,
        mapping=mapping,
        existing_skus=existing_skus,
        default_category=default_category,
        default_location_id=default_location.id,
        location_lookup=location_lookup,
    )

    if errors:
        return templates.TemplateResponse(
            request=request,
            name='inventory_import.html',
            context={
                'error': 'Nothing was imported because the file contains validation errors.',
                'import_errors': errors,
                'import_fields': IMPORT_FIELDS,
                'storage_locations': locations,
                'preview': {
                    'token': token,
                    'filename': filename,
                    'headers': headers,
                    'rows': rows[:25],
                    'total_rows': len(rows),
                    'mapping': mapping,
                },
            },
            status_code=400,
        )

    try:
        for row in validated_rows:
            item = create_item(
                db=db,
                sku=row['sku'],
                name=row['name'],
                category=row['category'],
                storage_location_id=row['storage_location_id'],
                min_stock=row['minimum_stock'],
                supplier=row['supplier'],
                unit_cost=row['unit_cost'],
                lead_time_days=row['lead_time_days'],
                lead_time_mode='AUTOMATIC',
                commit=False,
            )
            if row['quantity']:
                create_stock_in(
                    db=db,
                    item_id=item.id,
                    quantity=row['quantity'],
                    reason='Initial inventory import',
                    actor=actor_name(request),
                    storage_location_id=row['storage_location_id'],
                    reference=f'IMPORT: {filename}',
                    commit=False,
                )
        db.commit()
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=f'Inventory import failed: {exc}') from exc

    delete_import_file(request.state.user.id, token)
    return RedirectResponse(f'/inventory?imported={len(validated_rows)}', status_code=303)

@app.get('/inventory/{item_id}', response_class=HTMLResponse)
def inventory_item_page(item_id: int, request: Request, db: Session=Depends(get_db)):
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail='Item not found.')
    transactions = db.scalars(select(Transaction).where(Transaction.item_id == item_id).order_by(Transaction.movement_date.desc())).all()
    movement_history = []
    for transaction in transactions:
        asset = db.get(Asset, transaction.asset_id) if transaction.asset_id else None
        movement_history.append({'id': transaction.id, 'transaction_type': transaction.transaction_type, 'quantity': transaction.quantity, 'reason': transaction.reason, 'actor': transaction.actor, 'reference': transaction.reference, 'asset_name': asset_display_label(asset), 'location_name': location_label(db, transaction.storage_location_id), 'movement_date': transaction.movement_date, 'notes': transaction.notes})
    locations = active_locations(db)
    location_balances = [{'id': location.id, 'name': location_label(db, location.id), 'physical': stock_for_item(db, item.id, location.id), 'reserved': reserved_for_item(db, item.id, location.id), 'available': available_for_item(db, item.id, location.id)} for location in locations if stock_for_item(db, item.id, location.id) != 0 or reserved_for_item(db, item.id, location.id) != 0 or item.default_storage_location_id == location.id]
    item_data = {'id': item.id, 'sku': item.sku, 'name': item.name, 'category': item.category, 'location': location_label(db, item.default_storage_location_id), 'default_storage_location_id': item.default_storage_location_id, 'supplier': item.supplier, 'unit_cost': item.unit_cost, 'minimum_stock': item.min_stock, 'lead_time_days': item.lead_time_days, 'lead_time_mode': item.lead_time_mode, 'physical_stock': stock_for_item(db, item.id), 'reserved_stock': reserved_for_item(db, item.id), 'available_stock': available_for_item(db, item.id), 'on_order': on_order_for_item(db, item.id)}
    return templates.TemplateResponse(request=request, name='inventory_item.html', context={'item': item_data, 'movements': movement_history, 'storage_locations': locations, 'location_balances': location_balances})

@app.post('/inventory/create')
def create_inventory_item(
    sku: str=Form(...),
    name: str=Form(...),
    category: str=Form(...),
    storage_location_id: int=Form(...),
    min_stock: int=Form(0),
    supplier: str=Form(''),
    unit_cost: str=Form(''),
    lead_time_days: int=Form(14),
    lead_time_mode: str=Form('AUTOMATIC'),
    db: Session=Depends(get_db),
    _user=Depends(require_roles(ROLE_ADMIN, ROLE_MANAGER)),
):
    parsed_unit_cost = None
    if unit_cost.strip():
        try:
            parsed_unit_cost = float(unit_cost)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail='Unit cost must be a valid number.') from exc

    service_or_400(
        create_item,
        db=db,
        sku=sku,
        name=name,
        category=category,
        storage_location_id=storage_location_id,
        min_stock=min_stock,
        supplier=supplier,
        unit_cost=parsed_unit_cost,
        lead_time_days=lead_time_days,
        lead_time_mode=lead_time_mode,
    )
    return RedirectResponse('/inventory', status_code=303)

@app.post('/inventory/{item_id}/edit')
def edit_inventory_item(item_id: int, request: Request, name: str=Form(...), category: str=Form(...), storage_location_id: int=Form(...), min_stock: int=Form(0), supplier: str=Form(''), unit_cost: str=Form(''), lead_time_days: int=Form(14), lead_time_mode: str=Form('AUTOMATIC'), db: Session=Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN, ROLE_MANAGER))):
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail='Item not found.')
    location = db.get(StorageLocation, storage_location_id)
    if location is None or not location.is_active:
        raise HTTPException(status_code=400, detail='Invalid storage location.')
    parsed_unit_cost = None
    if unit_cost.strip():
        try:
            parsed_unit_cost = float(unit_cost)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail='Unit cost must be a valid number.') from exc
    clean_mode = lead_time_mode.strip().upper()
    if clean_mode not in {'AUTOMATIC', 'CONFIGURED'}:
        raise HTTPException(status_code=400, detail='Invalid lead time mode.')
    item.name = name.strip()
    item.category = category.strip()
    item.default_storage_location_id = location.id
    item.location = location.name
    item.min_stock = min_stock
    item.supplier = supplier.strip() or None
    item.unit_cost = parsed_unit_cost
    item.lead_time_days = lead_time_days
    item.lead_time_mode = clean_mode
    db.commit()
    return RedirectResponse(f'/inventory/{item.id}', status_code=303)

@app.post('/inventory/{item_id}/adjust')
def adjust_inventory_item(item_id: int, request: Request, actual_quantity: int=Form(...), storage_location_id: int=Form(...), reason: str=Form('Audit count correction'), notes: str=Form(''), db: Session=Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN, ROLE_MANAGER))):
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail='Item not found.')
    if actual_quantity < 0:
        raise HTTPException(status_code=400, detail='Actual quantity cannot be negative.')
    current_quantity = stock_for_item(db, item_id, storage_location_id)
    adjustment = actual_quantity - current_quantity
    if adjustment:
        service_or_400(create_stock_adjustment, db=db, item_id=item_id, adjustment=adjustment, storage_location_id=storage_location_id, reason=reason, actor=actor_name(request), reference='AUDIT', notes=notes or None)
    return RedirectResponse(f'/inventory/{item_id}', status_code=303)

@app.get('/movements', response_class=HTMLResponse)
def movements_page(request: Request, db: Session=Depends(get_db)):
    items = db.scalars(select(Item).order_by(Item.name)).all()
    assets = db.scalars(select(Asset).order_by(Asset.code)).all()
    transactions = db.scalars(select(Transaction).order_by(Transaction.movement_date.desc())).all()
    movement_history = []
    for transaction in transactions:
        item = db.get(Item, transaction.item_id)
        asset = db.get(Asset, transaction.asset_id) if transaction.asset_id else None
        movement_history.append({'id': transaction.id, 'item_name': item.name if item else 'Unknown Item', 'sku': item.sku if item else 'Unknown', 'transaction_type': transaction.transaction_type, 'quantity': transaction.quantity, 'reason': transaction.reason, 'actor': transaction.actor, 'reference': transaction.reference, 'asset_name': asset_display_label(asset), 'location_name': location_label(db, transaction.storage_location_id), 'movement_date': transaction.movement_date, 'notes': transaction.notes})
    return templates.TemplateResponse(request=request, name='movements.html', context={'items': items, 'assets': assets, 'storage_locations': active_locations(db), 'movements': movement_history})

@app.post('/movements/in')
def movement_stock_in(request: Request, item_id: int=Form(...), quantity: int=Form(...), reason: str=Form(...), storage_location_id: int=Form(...), reference: str=Form(''), asset_id: str=Form(''), db: Session=Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN, ROLE_MANAGER, ROLE_STAFF))):
    service_or_400(create_stock_in, db=db, item_id=item_id, quantity=quantity, reason=reason, actor=actor_name(request), asset_id=parse_optional_int(asset_id, 'asset ID'), storage_location_id=storage_location_id, reference=reference or None)
    return RedirectResponse('/movements', status_code=303)

@app.post('/movements/out')
def movement_stock_out(request: Request, item_id: int=Form(...), quantity: int=Form(...), reason: str=Form(...), storage_location_id: int=Form(...), reference: str=Form(''), asset_id: str=Form(''), db: Session=Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN, ROLE_MANAGER, ROLE_STAFF))):
    service_or_400(create_stock_out, db=db, item_id=item_id, quantity=quantity, reason=reason, actor=actor_name(request), asset_id=parse_optional_int(asset_id, 'asset ID'), storage_location_id=storage_location_id, reference=reference or None)
    return RedirectResponse('/movements', status_code=303)

@app.post('/movements/transfer')
def movement_stock_transfer(request: Request, item_id: int=Form(...), quantity: int=Form(...), from_storage_location_id: int=Form(...), to_storage_location_id: int=Form(...), reference: str=Form(''), notes: str=Form(''), db: Session=Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN, ROLE_MANAGER, ROLE_STAFF))):
    service_or_400(create_stock_transfer, db=db, item_id=item_id, quantity=quantity, from_storage_location_id=from_storage_location_id, to_storage_location_id=to_storage_location_id, actor=actor_name(request), reference=reference.strip() or None, notes=notes.strip() or None)
    return RedirectResponse('/movements', status_code=303)

@app.get('/orders', response_class=HTMLResponse)
def orders_page(request: Request, db: Session=Depends(get_db)):
    items = db.scalars(select(Item).order_by(Item.name)).all()
    purchase_orders = db.scalars(select(PurchaseOrder).order_by(PurchaseOrder.order_date.desc())).all()
    orders = []
    today = datetime.now().date()
    for purchase_order in purchase_orders:
        lines = db.scalars(select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == purchase_order.id)).all()
        for line in lines:
            item = db.get(Item, line.item_id)
            outstanding = line.quantity_ordered - line.quantity_received
            is_overdue = False
            days_until_delivery = None
            if purchase_order.expected_delivery_date is not None and outstanding > 0:
                expected_date = purchase_order.expected_delivery_date.date()
                days_until_delivery = (expected_date - today).days
                is_overdue = expected_date < today
            display_status = 'RECEIVED' if outstanding == 0 else 'OVERDUE' if is_overdue else purchase_order.status
            orders.append({'line_id': line.id, 'po_number': purchase_order.po_number, 'supplier': purchase_order.supplier, 'status': purchase_order.status, 'display_status': display_status, 'item_name': item.name if item else 'Unknown Item', 'quantity_ordered': line.quantity_ordered, 'quantity_received': line.quantity_received, 'quantity_outstanding': outstanding, 'unit_cost': line.unit_cost, 'expected_delivery_date': purchase_order.expected_delivery_date, 'days_until_delivery': days_until_delivery, 'is_overdue': is_overdue})
    return templates.TemplateResponse(request=request, name='orders.html', context={'items': items, 'orders': orders, 'storage_locations': active_locations(db)})

@app.post('/orders/create')
def create_order_page(request: Request, po_number: str=Form(...), supplier: str=Form(...), item_id: int=Form(...), quantity: int=Form(...), unit_cost: str=Form(''), expected_delivery_date: str=Form(''), notes: str=Form(''), db: Session=Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN, ROLE_MANAGER))):
    parsed_unit_cost = None
    if unit_cost.strip():
        try:
            parsed_unit_cost = float(unit_cost)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail='Unit cost must be a valid number.') from exc
    parsed_expected_date = None
    if expected_delivery_date.strip():
        try:
            parsed_expected_date = datetime.strptime(expected_delivery_date, '%Y-%m-%d')
        except ValueError as exc:
            raise HTTPException(status_code=400, detail='Invalid expected delivery date.') from exc
    service_or_400(create_purchase_order, db=db, po_number=po_number, supplier=supplier, item_id=item_id, quantity=quantity, created_by=actor_name(request), unit_cost=parsed_unit_cost, expected_delivery_date=parsed_expected_date, notes=notes or None)
    return RedirectResponse('/orders', status_code=303)

@app.post('/orders/receive')
def receive_order_page(request: Request, order_line_id: int=Form(...), quantity: int=Form(...), storage_location_id: int=Form(...), notes: str=Form(''), db: Session=Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN, ROLE_MANAGER))):
    service_or_400(receive_purchase_order, db=db, order_line_id=order_line_id, quantity=quantity, received_by=actor_name(request), storage_location_id=storage_location_id, notes=notes or None)
    return RedirectResponse('/orders', status_code=303)

@app.get('/assets', response_class=HTMLResponse)
def assets_page(request: Request, db: Session=Depends(get_db)):
    items = db.scalars(select(Item).order_by(Item.name)).all()
    assets = db.scalars(select(Asset).order_by(Asset.code)).all()
    asset_data = []
    for asset in assets:
        components = db.scalars(select(AssetComponent).where(AssetComponent.asset_id == asset.id)).all()
        component_data = []
        total_required = 0
        total_assigned = 0
        for component in components:
            item = db.get(Item, component.item_id)
            missing = max(component.quantity_required - component.quantity_assigned, 0)
            total_required += component.quantity_required
            total_assigned += component.quantity_assigned
            component_data.append({'id': component.id, 'item_name': item.name if item else 'Unknown Item', 'sku': item.sku if item else 'Unknown', 'required': component.quantity_required, 'assigned': component.quantity_assigned, 'missing': missing})
        asset_data.append({'id': asset.id, 'code': asset.code, 'name': asset.name, 'asset_type': asset.asset_type, 'serial_number': asset.serial_number, 'site': site_display_label(db.get(Site, asset.site_id) if asset.site_id else None), 'location': asset.location, 'status': asset.status, 'notes': asset.notes, 'components': component_data, 'total_required': total_required, 'total_assigned': total_assigned, 'completion': round(total_assigned / total_required * 100) if total_required else 0})
    return templates.TemplateResponse(request=request, name='assets.html', context={'assets': asset_data, 'items': items, 'sites': active_sites(db), 'asset_types': active_asset_types(db), 'storage_locations': active_locations(db)})

@app.post('/assets/create')
def create_asset(request: Request, code: str=Form(...), asset_type_id: int=Form(...), site_id: int=Form(...), name: str=Form(''), serial_number: str=Form(''), location: str=Form(''), status: str=Form('ACTIVE'), notes: str=Form(''), db: Session=Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN, ROLE_MANAGER))):
    clean_code = code.strip().upper()
    clean_serial = serial_number.strip()
    if not clean_code:
        raise HTTPException(status_code=400, detail='Asset code cannot be empty.')
    asset_type = db.get(AssetType, asset_type_id)
    site = db.get(Site, site_id)
    if asset_type is None or not asset_type.is_active:
        raise HTTPException(status_code=400, detail='Invalid asset type.')
    if site is None or not site.is_active:
        raise HTTPException(status_code=400, detail='Invalid site.')
    if db.scalar(select(Asset).where(Asset.code == clean_code)) is not None:
        raise HTTPException(status_code=400, detail='An asset with this code already exists in this organization.')
    if clean_serial and db.scalar(select(Asset).where(Asset.serial_number == clean_serial)) is not None:
        raise HTTPException(status_code=400, detail='An asset with this serial number already exists in this organization.')
    asset = Asset(organization_id=current_organization_id(db), code=clean_code, name=name.strip() or None, asset_type_id=asset_type.id, asset_type=asset_type.name, site_id=site.id, serial_number=clean_serial or None, location=location.strip() or None, status=status.strip().upper() or 'ACTIVE', notes=notes.strip() or None)
    db.add(asset)
    safe_commit(db, 'Could not create the asset.')
    return RedirectResponse('/assets', status_code=303)

@app.post('/assets/{asset_id}/components/add')
def add_asset_component(asset_id: int, item_id: int=Form(...), quantity_required: int=Form(...), db: Session=Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN, ROLE_MANAGER))):
    asset = db.get(Asset, asset_id)
    item = db.get(Item, item_id)
    if asset is None:
        raise HTTPException(status_code=404, detail='Asset not found.')
    if item is None:
        raise HTTPException(status_code=404, detail='Inventory item not found.')
    if quantity_required <= 0:
        raise HTTPException(status_code=400, detail='Required quantity must be greater than zero.')
    existing = db.scalar(select(AssetComponent).where(AssetComponent.asset_id == asset_id, AssetComponent.item_id == item_id))
    if existing is not None:
        raise HTTPException(status_code=400, detail='This item is already tracked for this asset.')
    db.add(AssetComponent(organization_id=current_organization_id(db), asset_id=asset_id, item_id=item_id, quantity_required=quantity_required, quantity_assigned=0))
    db.commit()
    return RedirectResponse('/assets', status_code=303)

@app.post('/assets/components/{asset_component_id}/edit')
def edit_asset_component(asset_component_id: int, quantity_required: int=Form(...), db: Session=Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN, ROLE_MANAGER))):
    component = db.get(AssetComponent, asset_component_id)
    if component is None:
        raise HTTPException(status_code=404, detail='Asset component not found.')
    if quantity_required <= 0 or quantity_required < component.quantity_assigned:
        raise HTTPException(status_code=400, detail='Required quantity is invalid for the amount already assigned.')
    component.quantity_required = quantity_required
    db.commit()
    return RedirectResponse('/assets', status_code=303)

@app.post('/assets/components/{asset_component_id}/remove')
def remove_asset_component(asset_component_id: int, db: Session=Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN, ROLE_MANAGER))):
    component = db.get(AssetComponent, asset_component_id)
    if component is None:
        raise HTTPException(status_code=404, detail='Asset component not found.')
    if component.quantity_assigned > 0:
        raise HTTPException(status_code=400, detail='Return assigned inventory before removing this requirement.')
    db.delete(component)
    db.commit()
    return RedirectResponse('/assets', status_code=303)

@app.post('/assets/components/{asset_component_id}/return')
def return_asset_component(asset_component_id: int, request: Request, quantity: int=Form(...), storage_location_id: int=Form(...), notes: str=Form(''), db: Session=Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN, ROLE_MANAGER, ROLE_STAFF))):
    service_or_400(return_component_from_asset, db=db, asset_component_id=asset_component_id, quantity=quantity, returned_by=actor_name(request), storage_location_id=storage_location_id, notes=notes or None)
    return RedirectResponse('/assets', status_code=303)

@app.get('/requests', response_class=HTMLResponse)
def requests_page(request: Request, db: Session=Depends(get_db)):
    items = db.scalars(select(Item).order_by(Item.name)).all()
    assets = db.scalars(select(Asset).order_by(Asset.code)).all()
    stock_requests = db.scalars(select(StockRequest).order_by(StockRequest.request_date.desc())).all()
    requests_data = []
    for stock_request in stock_requests:
        item = db.get(Item, stock_request.item_id)
        asset = db.get(Asset, stock_request.asset_id) if stock_request.asset_id else None
        requests_data.append({'id': stock_request.id, 'item_name': item.name if item else 'Unknown Item', 'sku': item.sku if item else 'Unknown', 'asset_name': asset_display_label(asset), 'location_name': location_label(db, stock_request.storage_location_id), 'quantity': stock_request.quantity, 'requested_by': stock_request.requested_by, 'reason': stock_request.reason, 'request_date': stock_request.request_date, 'status': stock_request.status, 'approved_by': stock_request.approved_by, 'approved_at': stock_request.approved_at, 'collected_at': stock_request.collected_at, 'notes': stock_request.notes})
    return templates.TemplateResponse(request=request, name='requests.html', context={'items': items, 'assets': assets, 'storage_locations': active_locations(db), 'requests': requests_data})

@app.post('/requests/create')
def create_request_page(request: Request, item_id: int=Form(...), quantity: int=Form(...), reason: str=Form(...), storage_location_id: int=Form(...), asset_id: str=Form(''), notes: str=Form(''), db: Session=Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN, ROLE_MANAGER, ROLE_STAFF))):
    service_or_400(create_request, db=db, item_id=item_id, quantity=quantity, requested_by=actor_name(request), reason=reason, asset_id=parse_optional_int(asset_id, 'asset ID'), storage_location_id=storage_location_id, notes=notes or None)
    return RedirectResponse('/requests', status_code=303)

@app.post('/requests/approve')
def approve_request_page(request: Request, request_id: int=Form(...), db: Session=Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN, ROLE_MANAGER))):
    service_or_400(approve_request, db=db, request_id=request_id, approved_by=actor_name(request))
    return RedirectResponse('/requests', status_code=303)

@app.post('/requests/reject')
def reject_request_page(request: Request, request_id: int=Form(...), notes: str=Form(''), db: Session=Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN, ROLE_MANAGER))):
    service_or_400(reject_request, db=db, request_id=request_id, rejected_by=actor_name(request), notes=notes or None)
    return RedirectResponse('/requests', status_code=303)

@app.post('/requests/collect')
def collect_request_page(request: Request, request_id: int=Form(...), db: Session=Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN, ROLE_MANAGER, ROLE_STAFF))):
    service_or_400(collect_request, db=db, request_id=request_id, collected_by=actor_name(request))
    return RedirectResponse('/requests', status_code=303)

@app.get('/settings', response_class=HTMLResponse)
def settings_page(request: Request, db: Session=Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN))):
    organization = db.get(Organization, request.state.organization_id)
    return templates.TemplateResponse(request=request, name='settings.html', context={'organization': organization, 'sites': db.scalars(select(Site).order_by(Site.name)).all(), 'storage_locations': db.scalars(select(StorageLocation).order_by(StorageLocation.name)).all(), 'asset_types': db.scalars(select(AssetType).order_by(AssetType.name)).all(), 'users': db.scalars(select(AppUser).order_by(AppUser.display_name)).all(), 'valid_roles': sorted(VALID_ROLES), 'network': network_access_context()})

@app.post('/settings/organization')
def update_organization(request: Request, name: str=Form(...), db: Session=Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN))):
    organization = db.get(Organization, request.state.organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail='Organization not found.')
    if not name.strip():
        raise HTTPException(status_code=400, detail='Organization name cannot be empty.')
    organization.name = name.strip()
    db.commit()
    return RedirectResponse('/settings', status_code=303)

@app.post('/settings/sites/create')
def create_site(request: Request, code: str=Form(...), name: str=Form(...), address: str=Form(''), db: Session=Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN))):
    db.add(Site(organization_id=current_organization_id(db), code=code.strip().upper(), name=name.strip(), address=address.strip() or None, is_active=True))
    safe_commit(db, 'A site with this code already exists in this organization.')
    return RedirectResponse('/settings', status_code=303)

@app.post('/settings/locations/create')
def create_storage_location(request: Request, site_id: int=Form(...), code: str=Form(...), name: str=Form(...), location_type: str=Form('STORAGE'), db: Session=Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN))):
    site = db.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=400, detail='Invalid site.')
    db.add(StorageLocation(organization_id=current_organization_id(db), site_id=site.id, code=code.strip().upper(), name=name.strip(), location_type=location_type.strip().upper() or 'STORAGE', is_active=True))
    safe_commit(db, 'A storage location with this code already exists in this organization.')
    return RedirectResponse('/settings', status_code=303)

@app.post('/settings/asset-types/create')
def create_asset_type(request: Request, name: str=Form(...), description: str=Form(''), db: Session=Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN))):
    db.add(AssetType(organization_id=current_organization_id(db), name=name.strip(), description=description.strip() or None, is_active=True))
    safe_commit(db, 'This asset type already exists in this organization.')
    return RedirectResponse('/settings', status_code=303)

@app.post('/settings/users/create')
def create_user(request: Request, display_name: str=Form(...), email: str=Form(...), password: str=Form(...), role: str=Form('VIEWER'), db: Session=Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN))):
    clean_role = role.strip().upper()
    if clean_role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail='Invalid role.')
    try:
        password_hash = hash_password(password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.add(AppUser(organization_id=current_organization_id(db), email=email.strip().lower(), display_name=display_name.strip(), password_hash=password_hash, role=clean_role, is_active=True))
    safe_commit(db, 'A user with this email already exists.')
    return RedirectResponse('/settings', status_code=303)

@app.post('/settings/users/{user_id}/role')
def update_user_role(user_id: int, request: Request, role: str=Form(...), db: Session=Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN))):
    user = db.get(AppUser, user_id)
    clean_role = role.strip().upper()
    if user is None:
        raise HTTPException(status_code=404, detail='User not found.')
    if clean_role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail='Invalid role.')
    if user.id == request.state.user.id and clean_role != ROLE_ADMIN:
        raise HTTPException(status_code=400, detail='You cannot remove your own administrator role.')
    user.role = clean_role
    db.commit()
    return RedirectResponse('/settings', status_code=303)

@app.post('/settings/users/{user_id}/active')
def update_user_active(user_id: int, request: Request, is_active: str=Form(...), db: Session=Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN))):
    user = db.get(AppUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail='User not found.')
    should_be_active = is_active.strip().lower() in {'1', 'true', 'yes', 'on'}
    if user.id == request.state.user.id and (not should_be_active):
        raise HTTPException(status_code=400, detail='You cannot deactivate your own administrator account.')
    if user.role == ROLE_ADMIN and (not should_be_active):
        active_admin_count = db.scalar(select(func.count(AppUser.id)).where(AppUser.role == ROLE_ADMIN, AppUser.is_active.is_(True))) or 0
        if active_admin_count <= 1:
            raise HTTPException(status_code=400, detail='At least one active administrator is required.')
    user.is_active = should_be_active
    db.commit()
    return RedirectResponse('/settings', status_code=303)

def intelligence_context(db: Session) -> dict:
    insights = generate_inventory_insights(db)
    anomalies = generate_inventory_anomalies(db)
    return {
        "insights": insights,
        "anomalies": anomalies,
        "high_anomaly_count": sum(a["severity"] == "HIGH" for a in anomalies),
        "medium_anomaly_count": sum(a["severity"] == "MEDIUM" for a in anomalies),
        "ai_status": get_local_ai_status(),
        "assistant_answer": None,
        "assistant_error": None,
        "assistant_question": "",
        "selected_item_id": None,
        "selected_insight": None,
        "selected_anomalies": [],
        "attention_answer": None,
        "attention_error": None,
        "attention_items": [],
        "overdue_answer": None,
        "overdue_error": None,
        "overdue_orders": [],
    }

def apply_drei(context: dict, error_key: str, action, result_map: dict[str, str], **kwargs) -> None:
    if not context["ai_status"]["available"]:
        context[error_key] = context["ai_status"]["message"]
        return
    try:
        result = action(**kwargs)
    except (DreiAgentError, LocalAIError) as exc:
        context[error_key] = str(exc)
        return
    context.update({target: result[source] for target, source in result_map.items()})

@app.get('/insights', response_class=HTMLResponse)
def insights_page(request: Request, db: Session=Depends(get_db)):
    return templates.TemplateResponse(request=request, name='insights.html', context=intelligence_context(db))

@app.post('/insights/assistant', response_class=HTMLResponse)
def post_drei_item_assistant(request: Request, item_id: int=Form(...), question: str=Form(...), db: Session=Depends(get_db)):
    context = intelligence_context(db)
    context.update({'assistant_question': question, 'selected_item_id': item_id})
    apply_drei(context, 'assistant_error', ask_drei_about_item, {'assistant_answer': 'answer', 'selected_insight': 'insight', 'selected_anomalies': 'anomalies'}, db=db, item_id=item_id, question=question)
    return templates.TemplateResponse(request=request, name='insights.html', context=context)

@app.post('/insights/attention', response_class=HTMLResponse)
def post_drei_attention(request: Request, question: str=Form('What needs my attention right now?'), db: Session=Depends(get_db)):
    context = intelligence_context(db)
    apply_drei(context, 'attention_error', ask_drei_about_attention, {'attention_answer': 'answer', 'attention_items': 'attention_items'}, db=db, question=question)
    return templates.TemplateResponse(request=request, name='insights.html', context=context)

@app.post('/insights/overdue-orders', response_class=HTMLResponse)
def post_drei_overdue_orders(request: Request, question: str=Form('Which purchase orders are overdue?'), db: Session=Depends(get_db)):
    context = intelligence_context(db)
    apply_drei(context, 'overdue_error', ask_drei_about_overdue_orders, {'overdue_answer': 'answer', 'overdue_orders': 'overdue_orders'}, db=db, question=question)
    return templates.TemplateResponse(request=request, name='insights.html', context=context)
