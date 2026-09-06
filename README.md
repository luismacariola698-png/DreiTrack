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