"""Optional organization-scoped demo seed data."""
from sqlalchemy import select
from app.database import SessionLocal
from app.models import AppUser, Asset, AssetComponent, AssetType, Item, Organization, StorageLocation
from app.security import ROLE_ADMIN, hash_password
from app.services import create_stock_in, stock_for_item
from app.tenancy import create_organization_defaults, unique_organization_slug

def main() -> None:
    db = SessionLocal()
    try:
        organization = db.scalar(select(Organization).order_by(Organization.id))
        if organization is None:
            organization = Organization(name='Demo Organization', slug=unique_organization_slug(db, 'Demo Organization'), is_active=True)
            db.add(organization)
            db.flush()
            create_organization_defaults(db, organization)
            db.add(AppUser(organization_id=organization.id, email='admin@demo.dreitrack', display_name='Demo Administrator', password_hash=hash_password('ChangeMe123!'), role=ROLE_ADMIN, is_active=True))
            db.commit()
        db.info['organization_id'] = organization.id
        location = db.scalar(select(StorageLocation).order_by(StorageLocation.id))
        asset_type = db.scalar(select(AssetType).where(AssetType.name == 'Equipment')) or db.scalar(select(AssetType).order_by(AssetType.id))
        if location is None or asset_type is None:
            raise RuntimeError('Organization defaults are missing. Run setup first.')
        item = db.scalar(select(Item).where(Item.sku == 'SAMPLE-001'))
        if item is None:
            item = Item(organization_id=organization.id, sku='SAMPLE-001', name='Sample Servo Motor', category='Motor', default_storage_location_id=location.id, location=location.name, min_stock=10, supplier='Sample Supplier', unit_cost=50.0, lead_time_days=14, lead_time_mode='AUTOMATIC')
            db.add(item)
            db.commit()
            db.refresh(item)
            create_stock_in(db=db, item_id=item.id, storage_location_id=location.id, quantity=50, reason='Initial demo stock', actor='Demo Administrator')
            print('Demo item created.')
        else:
            print('Demo item already exists.')
        asset = db.scalar(select(Asset).where(Asset.code == 'ASSET-001'))
        if asset is None:
            asset = Asset(organization_id=organization.id, code='ASSET-001', name='Assembly Unit 001', asset_type_id=asset_type.id, asset_type=asset_type.name, site_id=location.site_id, serial_number='DEMO-A001', location='Workshop A', status='ACTIVE', notes='Generic demonstration asset.')
            db.add(asset)
            db.commit()
            db.refresh(asset)
            print('Demo asset created.')
        else:
            print('Demo asset already exists.')
        component = db.scalar(select(AssetComponent).where(AssetComponent.asset_id == asset.id, AssetComponent.item_id == item.id))
        if component is None:
            component = AssetComponent(organization_id=organization.id, asset_id=asset.id, item_id=item.id, quantity_required=6, quantity_assigned=0)
            db.add(component)
            db.commit()
            print('Demo asset component requirement created.')
        print('----- DREITRACK DEMO -----')
        print(f'Organization: {organization.name}')
        print(f'Item: {item.name}')
        print(f'Current stock: {stock_for_item(db, item.id)}')
        print(f'Asset: {asset.code} - {asset.name}')
    finally:
        db.close()
if __name__ == '__main__':
    main()
