## v0.4.3 - Mobile Browser Support

DreiTrack now provides a responsive interface for desktop and mobile browsers while using the same backend, database, and private-LAN installation.

The mobile update includes:

- Responsive navigation and page layouts
- Mobile inventory cards
- Mobile stock movement history
- Mobile purchase order and receiving workflows
- Mobile stock request management
- Mobile-friendly inventory import and column mapping
- Touch-friendly forms and controls
- Responsive forms for stock movements, transfers and inventory management
- Real-phone testing over a trusted private LAN
- No separate mobile application or duplicate backend

DreiTrack automatically adapts its interface based on the browser width. Desktop users retain the normal table-based interface, while smaller screens use layouts designed for touch and limited screen space.

## v0.4.2 - Inventory Import

DreiTrack can now import existing inventory lists from CSV and Excel (.xlsx) files.

The importer includes:

- CSV and Excel file support
- Automatic column suggestions
- Manual column mapping
- Import preview before database changes
- Validation for missing or invalid data
- Duplicate SKU detection
- Storage location validation
- Configurable default category and storage location
- Initial quantities recorded through DreiTrack's stock transaction system
- Atomic imports, preventing partially imported spreadsheets
- Temporary uploaded files automatically removed after use or expiry

The importer reuses DreiTrack's existing inventory and stock services rather than maintaining a separate inventory calculation path.