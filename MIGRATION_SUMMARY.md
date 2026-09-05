# DreiTrack v0.3 Migration Summary

## Deployment model

DreiTrack now uses a private single-company deployment model:

- one installation = one company
- first-time setup runs once
- `/register` has been removed
- only administrators can create users
- operational and API pages require authentication
- unauthenticated API documentation is no longer exposed by the authentication middleware

The existing `Organization` model remains internally so all operational records continue to have an explicit company boundary. Existing v0.2 databases with one organization require no schema migration.

## User administration

Administrators can create users, change roles, activate accounts and deactivate accounts. DreiTrack prevents an administrator from deactivating their own account and prevents removal of the last active administrator.

## Windows launcher

Added:

- `Setup DreiTrack.bat` — one-time virtual environment/dependency setup
- `DreiTrack.vbs` — silent normal launcher
- `launcher.py` — starts Uvicorn and Ollama without a terminal window
- `launcher_settings.json` — local launcher settings
- `Enable Auto Start.vbs` — starts DreiTrack at Windows sign-in
- `Disable Auto Start.vbs` — removes automatic startup

The default launcher binds to `127.0.0.1`, keeping the app local to the host computer until private-network hardening is completed.

## Version

Application version updated from 0.2.0 to 0.3.0.
